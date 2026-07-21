"""Central instrumented LLM client with cost, latency, and audit telemetry."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

from ..audit import log_action_safe
from ..config import Settings, get_settings
from ..llm_json import parse_json_strict
from ..models import ActorType, LlmCall, LlmCallStatus, LlmOperation
from .budget import check_daily_budget
from .pricing import TokenUsage, cost_usd
from .tracing import current_span_id, current_trace_id, span, start_trace

_logger = logging.getLogger(__name__)

# Bounded JSON-repair tuning (EA-03). A repair re-ask doubles the token budget
# up to this ceiling so a near-miss truncation gets enough room to complete.
_MAX_REPAIR_TOKENS = 8000
_JSON_REPAIR_NOTE = (
    "Your previous response was not valid, complete JSON. "
    "Reply with ONE complete JSON object and nothing else: no markdown, no code "
    "fences, no commentary, and do not truncate."
)


@contextmanager
def _telemetry_session(caller: Session) -> Iterator[Session | None]:
    """Yield a short-lived session bound to the caller's engine for telemetry.

    Isolating telemetry persistence from the caller's transaction is the whole
    point (EA-02), so we open a fresh session on the same bind and always close
    it. Fail-open: if a bound session can't be created, yield ``None`` and skip
    recording rather than break the instrumented call.
    """
    bind = caller.get_bind()
    if bind is None:
        yield None
        return
    tele = Session(bind)
    try:
        yield tele
    except Exception:  # pragma: no cover - defensive; recording must not propagate
        _logger.warning("telemetry session failed", exc_info=True)
        tele.rollback()
    finally:
        tele.close()


@dataclass
class ChatResult:
    text: str
    usage: TokenUsage
    response_model: str | None = None
    finish_reason: str | None = None


class InstrumentedLLM:
    """Wraps Anthropic and OpenAI SDK calls with unified telemetry."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._anthropic = None
        self._openai = None

    def _anthropic_client(self):
        if self._anthropic is None:
            from anthropic import Anthropic

            self._anthropic = Anthropic(api_key=self._settings.require_anthropic_key())
        return self._anthropic

    def _openai_client(self):
        if self._openai is None:
            from openai import OpenAI

            self._openai = OpenAI(api_key=self._settings.require_openai_key())
        return self._openai

    def _record_call(
        self,
        session: Session | None,
        *,
        operation: LlmOperation,
        provider: str,
        request_model: str,
        response_model: str | None,
        operation_name: str,
        usage: TokenUsage,
        latency_ms: int,
        status: LlmCallStatus,
        error_type: str | None = None,
        finish_reason: str | None = None,
        entity_type: str | None = None,
        entity_id: str | int | None = None,
        span_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        if not self._settings.feature_observability:
            return
        trace_id = current_trace_id() or start_trace()
        parent_span_id = current_span_id()
        cost = cost_usd(request_model, usage, price_overrides=self._settings.llm_price_overrides)
        call_detail = {
            "gen_ai.operation.name": operation.value,
            "gen_ai.provider.name": provider,
            "gen_ai.request.model": request_model,
            "gen_ai.response.model": response_model,
            "gen_ai.usage.input_tokens": usage.input_tokens,
            "gen_ai.usage.output_tokens": usage.output_tokens,
            "gen_ai.usage.cache_read.input_tokens": usage.cache_read_tokens,
            "gen_ai.usage.cache_creation.input_tokens": usage.cache_creation_tokens,
            "gen_ai.cost.usd": cost,
            **(detail or {}),
        }
        if session is None:
            return
        # EA-02: telemetry must never touch the caller's transaction. Writing the
        # LlmCall row + audit entry on the caller's session would commit (or roll
        # back) whatever business state is staged before an LLM call. Use a
        # dedicated session bound to the same engine so persistence is fully
        # isolated; in production this is a separate connection, and because the
        # business flows hold no open write transaction at call time there is no
        # SQLite writer contention.
        with _telemetry_session(session) as tele:
            if tele is None:
                return
            try:
                row = LlmCall(
                    trace_id=trace_id,
                    span_id=span_id or parent_span_id,
                    parent_span_id=parent_span_id,
                    operation=operation,
                    provider=provider,
                    request_model=request_model,
                    response_model=response_model,
                    operation_name=operation_name,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_read_tokens=usage.cache_read_tokens,
                    cache_creation_tokens=usage.cache_creation_tokens,
                    latency_ms=latency_ms,
                    cost_usd=cost,
                    status=status,
                    error_type=error_type,
                    finish_reason=finish_reason,
                    entity_type=entity_type,
                    entity_id=str(entity_id) if entity_id is not None else None,
                    detail=call_detail,
                )
                tele.add(row)
                tele.commit()
            except Exception:
                tele.rollback()
            log_action_safe(
                tele,
                actor=ActorType.agent,
                action="llm_call",
                entity_type=entity_type,
                entity_id=entity_id,
                detail={
                    "operation_name": operation_name,
                    "provider": provider,
                    "model": request_model,
                    "tokens_in": usage.input_tokens,
                    "tokens_out": usage.output_tokens,
                    "latency_ms": latency_ms,
                    "cost_usd": cost,
                    "status": status.value,
                    "trace_id": trace_id,
                },
            )

    def chat(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int,
        operation_name: str,
        session: Session | None = None,
        entity_type: str | None = None,
        entity_id: str | int | None = None,
        temperature: float | None = None,
    ) -> ChatResult:
        # Fail closed before spending if today's budget is exhausted (SEC-08).
        # No-op unless a cap is configured and a session is available to meter.
        check_daily_budget(session, self._settings.llm_daily_budget_usd)
        with span(operation_name, entity_type=entity_type, entity_id=entity_id) as span_id:
            started = time.perf_counter()
            try:
                # ``temperature`` is only forwarded when set, so existing callers
                # keep the SDK default; scoring pins it to 0 for reproducibility (TP-07).
                create_kwargs: dict[str, Any] = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                }
                if temperature is not None:
                    create_kwargs["temperature"] = temperature
                msg = self._anthropic_client().messages.create(**create_kwargs)
                text = "".join(
                    block.text for block in msg.content if getattr(block, "type", None) == "text"
                )
                usage = TokenUsage.from_anthropic(getattr(msg, "usage", None))
                latency_ms = int((time.perf_counter() - started) * 1000)
                response_model = getattr(msg, "model", None)
                stop_reason = getattr(msg, "stop_reason", None)
                self._record_call(
                    session,
                    operation=LlmOperation.chat,
                    provider="anthropic",
                    request_model=model,
                    response_model=response_model,
                    operation_name=operation_name,
                    usage=usage,
                    latency_ms=latency_ms,
                    status=LlmCallStatus.ok,
                    finish_reason=str(stop_reason) if stop_reason else None,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    span_id=span_id,
                )
                return ChatResult(text=text, usage=usage, response_model=response_model, finish_reason=stop_reason)
            except Exception as exc:
                latency_ms = int((time.perf_counter() - started) * 1000)
                self._record_call(
                    session,
                    operation=LlmOperation.chat,
                    provider="anthropic",
                    request_model=model,
                    response_model=None,
                    operation_name=operation_name,
                    usage=TokenUsage(),
                    latency_ms=latency_ms,
                    status=LlmCallStatus.error,
                    error_type=type(exc).__name__,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    span_id=span_id,
                    detail={"error": str(exc)},
                )
                raise

    def chat_json(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int,
        operation_name: str,
        session: Session | None = None,
        entity_type: str | None = None,
        entity_id: str | int | None = None,
        validate: Callable[[dict[str, Any]], None] | None = None,
        repair_attempts: int = 1,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Strict-JSON chat with a bounded repair path (EA-03).

        A single malformed or **truncated** response no longer poisons a run.
        When the model hits ``max_tokens`` (the JSON is cut off) or returns
        unparseable text, or when an optional ``validate`` callback rejects the
        shape, the call is re-issued up to ``repair_attempts`` times with a
        raised token budget and an explicit "return only valid JSON" reminder.
        Each attempt is recorded as its own ``LlmCall`` so cost stays auditable.
        """
        prompt = user
        budget = max_tokens
        last_error: Exception | None = None
        for attempt in range(repair_attempts + 1):
            result = self.chat(
                system=system,
                user=prompt,
                model=model,
                max_tokens=budget,
                operation_name=operation_name,
                session=session,
                entity_type=entity_type,
                entity_id=entity_id,
                temperature=temperature,
            )
            truncated = (result.finish_reason or "").lower() == "max_tokens"
            try:
                if truncated:
                    # A truncated response may still parse to a dict while being
                    # semantically incomplete; treat it as a failure to repair.
                    raise ValueError("response truncated at max_tokens")
                parsed = parse_json_strict(result.text)
                if validate is not None:
                    validate(parsed)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if attempt >= repair_attempts:
                    raise
                # Grow the budget toward the cap, but never below the original —
                # a caller passing max_tokens above the cap must not be shrunk on
                # a truncation retry.
                budget = max(budget, min(budget * 2, _MAX_REPAIR_TOKENS))
                prompt = f"{user}\n\n{_JSON_REPAIR_NOTE}"
                continue
            if result.usage.total_tokens:
                parsed["_usage"] = {
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                }
            return parsed
        # Unreachable: the loop either returns or raises. Kept for type-checkers.
        raise last_error or RuntimeError("chat_json failed without an error")

    def chat_with_web_search(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int,
        operation_name: str,
        max_searches: int = 5,
        session: Session | None = None,
        entity_type: str | None = None,
        entity_id: str | int | None = None,
    ) -> tuple[str, list[dict[str, str]]]:
        """Text completion with Anthropic's server-side ``web_search`` tool (INT-02).

        Returns ``(text, citations)`` where citations are deduped
        ``{"url", "title"}`` dicts harvested from the response's citation
        annotations. Telemetry mirrors ``chat`` and additionally records the
        number of web searches the server ran.
        """
        check_daily_budget(session, self._settings.llm_daily_budget_usd)
        with span(operation_name, entity_type=entity_type, entity_id=entity_id) as span_id:
            started = time.perf_counter()
            try:
                msg = self._anthropic_client().messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    tools=[
                        {
                            "type": "web_search_20250305",
                            "name": "web_search",
                            "max_uses": max_searches,
                        }
                    ],
                )
                text_parts: list[str] = []
                citations: list[dict[str, str]] = []
                seen_urls: set[str] = set()
                for block in msg.content:
                    if getattr(block, "type", None) != "text":
                        continue
                    text_parts.append(block.text)
                    for citation in getattr(block, "citations", None) or []:
                        url = getattr(citation, "url", None)
                        if not url or url in seen_urls:
                            continue
                        seen_urls.add(url)
                        citations.append({"url": url, "title": getattr(citation, "title", None) or url})
                usage = TokenUsage.from_anthropic(getattr(msg, "usage", None))
                latency_ms = int((time.perf_counter() - started) * 1000)
                server_tool_use = getattr(getattr(msg, "usage", None), "server_tool_use", None)
                web_searches = getattr(server_tool_use, "web_search_requests", None)
                self._record_call(
                    session,
                    operation=LlmOperation.chat,
                    provider="anthropic",
                    request_model=model,
                    response_model=getattr(msg, "model", None),
                    operation_name=operation_name,
                    usage=usage,
                    latency_ms=latency_ms,
                    status=LlmCallStatus.ok,
                    finish_reason=str(getattr(msg, "stop_reason", None) or "") or None,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    span_id=span_id,
                    detail={
                        "web_search_requests": web_searches,
                        "citation_count": len(citations),
                    },
                )
                return "".join(text_parts), citations
            except Exception as exc:
                latency_ms = int((time.perf_counter() - started) * 1000)
                self._record_call(
                    session,
                    operation=LlmOperation.chat,
                    provider="anthropic",
                    request_model=model,
                    response_model=None,
                    operation_name=operation_name,
                    usage=TokenUsage(),
                    latency_ms=latency_ms,
                    status=LlmCallStatus.error,
                    error_type=type(exc).__name__,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    span_id=span_id,
                    detail={"error": str(exc)},
                )
                raise

    def complete_text(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 8000,
        operation_name: str,
        session: Session | None = None,
        entity_type: str | None = None,
        entity_id: str | int | None = None,
    ) -> str:
        return self.chat(
            system=system,
            user=user,
            model=model,
            max_tokens=max_tokens,
            operation_name=operation_name,
            session=session,
            entity_type=entity_type,
            entity_id=entity_id,
        ).text

    def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
        operation_name: str = "embed_chunks",
        session: Session | None = None,
        entity_type: str | None = None,
        entity_id: str | int | None = None,
    ) -> list[list[float]]:
        if not texts:
            return []
        check_daily_budget(session, self._settings.llm_daily_budget_usd)
        model = model or self._settings.embedding_model
        with span(operation_name, entity_type=entity_type, entity_id=entity_id) as span_id:
            started = time.perf_counter()
            try:
                response = self._openai_client().embeddings.create(model=model, input=texts)
                latency_ms = int((time.perf_counter() - started) * 1000)
                usage = TokenUsage.from_openai_embedding(
                    getattr(response, "usage", None), text_count=len(texts)
                )
                self._record_call(
                    session,
                    operation=LlmOperation.embedding,
                    provider="openai",
                    request_model=model,
                    response_model=model,
                    operation_name=operation_name,
                    usage=usage,
                    latency_ms=latency_ms,
                    status=LlmCallStatus.ok,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    span_id=span_id,
                    detail={"text_count": len(texts)},
                )
                return [item.embedding for item in response.data]
            except Exception as exc:
                latency_ms = int((time.perf_counter() - started) * 1000)
                self._record_call(
                    session,
                    operation=LlmOperation.embedding,
                    provider="openai",
                    request_model=model,
                    response_model=None,
                    operation_name=operation_name,
                    usage=TokenUsage(),
                    latency_ms=latency_ms,
                    status=LlmCallStatus.error,
                    error_type=type(exc).__name__,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    span_id=span_id,
                    detail={"error": str(exc)},
                )
                raise


def build_instrumented_llm(settings: Settings | None = None) -> InstrumentedLLM:
    return InstrumentedLLM(settings)
