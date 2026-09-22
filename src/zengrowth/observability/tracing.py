"""Trace/span context and pipeline step recording (OpenTelemetry-aligned IDs)."""

from __future__ import annotations

import contextvars
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session

_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)
_span_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("span_id", default=None)
_pipeline_run_id: contextvars.ContextVar[int | None] = contextvars.ContextVar("pipeline_run_id", default=None)


def _new_id() -> str:
    return uuid.uuid4().hex


def current_trace_id() -> str | None:
    return _trace_id.get()


def current_span_id() -> str | None:
    return _span_id.get()


def start_trace() -> str:
    trace = _new_id()
    _trace_id.set(trace)
    _span_id.set(None)
    return trace


@contextmanager
def span(
    operation_name: str,
    *,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
) -> Iterator[str]:
    """Create a child span; restores parent span on exit."""
    span_id = _new_id()
    if _trace_id.get() is None:
        start_trace()
    token = _span_id.set(span_id)
    try:
        yield span_id
    finally:
        _span_id.reset(token)


@contextmanager
def pipeline_run(
    session: Session,
    *,
    pipeline_type: str,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    detail: dict[str, Any] | None = None,
) -> Iterator[str]:
    """Open a PipelineRun row and set trace context for nested steps."""
    from ..models import PipelineRun, PipelineRunStatus

    trace_id = start_trace()
    started_at = datetime.now(UTC)
    run = PipelineRun(
        trace_id=trace_id,
        pipeline_type=pipeline_type,
        started_at=started_at,
        status=PipelineRunStatus.running,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        detail=detail,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    run_token = _pipeline_run_id.set(run.id)
    try:
        yield trace_id
        run.status = PipelineRunStatus.completed
    except Exception as exc:
        run.status = PipelineRunStatus.failed
        run.detail = {**(run.detail or {}), "error": str(exc)}
        raise
    finally:
        run.finished_at = datetime.now(UTC)
        session.add(run)
        session.commit()
        _pipeline_run_id.reset(run_token)


def annotate_pipeline_run(session: Session, **detail: Any) -> None:
    """Merge ``detail`` into the active PipelineRun's ``detail`` JSON (fail-open).

    Lets a long-running pipeline stamp its outcome summary (e.g. ingestion's
    added / zero-row / failed-board counts) onto the run row so readiness probes
    (SEC-01/SEC-09) can read "what happened last night" without re-deriving it.
    """
    from ..models import PipelineRun

    run_id = _pipeline_run_id.get()
    if run_id is None:
        return
    try:
        run = session.get(PipelineRun, run_id)
        if run is None:
            return
        run.detail = {**(run.detail or {}), **detail}
        session.add(run)
        session.commit()
    except Exception:  # pragma: no cover - annotation must never break the run
        session.rollback()


def record_step(
    session: Session,
    *,
    step_name: str,
    step_type: str,
    duration_ms: int,
    status: str = "ok",
    decision: str | None = None,
    parent_span_id: str | None = None,
    span_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Persist a PipelineStep; fail-open on errors."""
    from ..models import PipelineStep

    trace_id = _trace_id.get()
    if not trace_id:
        return
    try:
        step = PipelineStep(
            trace_id=trace_id,
            span_id=span_id or _new_id(),
            parent_span_id=parent_span_id or _span_id.get(),
            step_name=step_name,
            step_type=step_type,
            decision=decision,
            started_at=datetime.now(UTC),
            duration_ms=duration_ms,
            status=status,
            detail=detail,
        )
        session.add(step)
        session.commit()
        run_id = _pipeline_run_id.get()
        if run_id is not None:
            from ..models import PipelineRun

            run = session.get(PipelineRun, run_id)
            if run is not None:
                run.step_count = (run.step_count or 0) + 1
                if detail:
                    cost = detail.get("cost_usd")
                    tokens = detail.get("total_tokens")
                    if cost:
                        run.total_cost_usd = (run.total_cost_usd or 0.0) + float(cost)
                    if tokens:
                        run.total_tokens = (run.total_tokens or 0) + int(tokens)
                session.add(run)
                session.commit()
    except Exception:
        session.rollback()


@contextmanager
def tool_step(
    session: Session,
    *,
    step_name: str,
    step_type: str = "tool",
    decision: str | None = None,
    detail: dict[str, Any] | None = None,
) -> Iterator[None]:
    """Record a non-LLM pipeline step (ATS fetch, Tavily, DB)."""
    started = time.perf_counter()
    span_id = _new_id()
    parent = _span_id.get()
    token = _span_id.set(span_id)
    try:
        yield
        duration_ms = int((time.perf_counter() - started) * 1000)
        record_step(
            session,
            step_name=step_name,
            step_type=step_type,
            duration_ms=duration_ms,
            status="ok",
            decision=decision,
            parent_span_id=parent,
            span_id=span_id,
            detail=detail,
        )
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        record_step(
            session,
            step_name=step_name,
            step_type=step_type,
            duration_ms=duration_ms,
            status="error",
            decision=decision,
            parent_span_id=parent,
            span_id=span_id,
            detail={**(detail or {}), "error": str(exc)},
        )
        raise
    finally:
        _span_id.reset(token)
