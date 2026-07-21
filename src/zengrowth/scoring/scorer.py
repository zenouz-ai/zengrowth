"""Single-agent Claude scoring.

One API call per job. Strict JSON output. Stores the full rationale on the
Job row and writes an AuditLog entry including token counts so Phase 5 cost
analytics has data from day one.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from sqlmodel import Session

from ..audit import log_action, log_action_safe
from ..config import Settings, get_settings
from ..knowledge.facets import (
    FacetAssignmentClient,
    assign_job_facets,
    build_default_facet_assigner,
    facets_available,
)
from ..models import ActorType, Job, LifecycleState
from ..observability.client import InstrumentedLLM, build_instrumented_llm
from .expected_value import DIMENSION_WEIGHTS, ranked_priority, success_band
from .prompts import REQUIRED_KEYS, SYSTEM_PROMPT, build_user_prompt


class _LLMClient(Protocol):
    def score(self, system: str, user: str, model: str) -> dict[str, Any]: ...


# Every scored dimension the repair path must validate as numeric — not just
# the four that happen to feed match/EV-era fields. ``summary`` stays textual.
_NUMERIC_DIMS = tuple(key for key in REQUIRED_KEYS if key != "summary")


def _dim_score(value: Any) -> float:
    if isinstance(value, dict) and "score" in value:
        return float(value["score"])
    return float(value)


def validate_scoring_response(parsed: dict[str, Any]) -> None:
    """Reject responses missing required keys or with non-numeric dimensions.

    Passed into ``chat_json`` so a malformed shape triggers the bounded repair
    re-ask (EA-03) instead of surfacing as a hard 502 / silent batch skip.
    """
    missing = [k for k in REQUIRED_KEYS if k not in parsed]
    if missing:
        raise ValueError(f"scoring response missing keys: {missing}")
    for dim in _NUMERIC_DIMS:
        try:
            _dim_score(parsed[dim])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"scoring dimension {dim!r} is not numeric: {parsed[dim]!r}") from exc


class InstrumentedScorer:
    """Scorer backed by the central instrumented LLM client."""

    def __init__(self, llm: InstrumentedLLM, *, session: Session | None = None, entity_id: int | None = None) -> None:
        self._llm = llm
        self._session = session
        self._entity_id = entity_id
        self._last_usage: dict[str, int] = {}

    def score(self, system: str, user: str, model: str) -> dict[str, Any]:
        parsed = self._llm.chat_json(
            system=system,
            user=user,
            model=model,
            max_tokens=1500,
            operation_name="score_job",
            session=self._session,
            entity_type="job",
            entity_id=self._entity_id,
            validate=validate_scoring_response,
            # TP-07: pin scoring to temperature 0 so the same job scores the same
            # across runs — a precondition for an auditable, calibratable signal.
            temperature=0.0,
        )
        usage = parsed.pop("_usage", None) or {}
        if usage:
            self._last_usage = {
                "input_tokens": int(usage.get("input_tokens", 0)),
                "output_tokens": int(usage.get("output_tokens", 0)),
            }
            parsed["_usage"] = self._last_usage
        return parsed


def _build_llm(settings: Settings, session: Session | None = None, entity_id: int | None = None) -> _LLMClient:
    return InstrumentedScorer(build_instrumented_llm(settings), session=session, entity_id=entity_id)


def score_job(
    session: Session,
    job: Job,
    *,
    client: _LLMClient | None = None,
    facet_assigner: FacetAssignmentClient | None = None,
    settings: Settings | None = None,
) -> Job:
    """Score one Job, persist rationale + EV, write an audit entry."""
    settings = settings or get_settings()
    client = client or _build_llm(settings, session=session, entity_id=job.id)

    age_days = (date.today() - job.posting_date).days if job.posting_date else None
    user_prompt = build_user_prompt(
        settings,
        job={
            "company": job.company,
            "title": job.title,
            "location": job.location,
            "hybrid_policy": job.hybrid_policy,
            "compensation": job.compensation,
            "seniority": job.seniority,
            "description": (job.description or "")[:8000],
            "application_url": job.application_url,
            "source": job.source.value,
        },
        posting_age_days=age_days,
    )

    rationale = client.score(SYSTEM_PROMPT, user_prompt, settings.scoring_model)
    missing = [k for k in REQUIRED_KEYS if k not in rationale]
    if missing:
        raise ValueError(f"scoring response missing keys: {missing}")

    match_quality = _dim_score(rationale["match_quality"])
    success_probability = _dim_score(rationale["success_probability"])
    application_effort = _dim_score(rationale["application_effort"])

    # TA-04: rank on observable fit (weighted sum of the scored dimensions);
    # success_probability only breaks ties via its band, effort stays a
    # separate cost axis shown to the operator, never a divisor.
    dimensions = {
        dim: _dim_score(rationale[dim]) for dim in DIMENSION_WEIGHTS if dim in rationale
    }
    ev = ranked_priority(dimensions, success_probability)
    job.fit_score = match_quality
    job.expected_value = ev
    job.score_rationale = rationale
    # TP-08 companion: a successful score means the job is pipeline-ready.
    # Batch precheck already transitions on pass; the operator paste path
    # (manual jobs skip batch precheck) needs the same discovered→shortlisted
    # move so scored manuals leave the Discovered column.
    if job.lifecycle_state == LifecycleState.discovered:
        job.lifecycle_state = LifecycleState.shortlisted
    session.add(job)
    session.commit()
    session.refresh(job)

    usage = rationale.get("_usage") or {}
    log_action(
        session,
        actor=ActorType.agent,
        action="score_job",
        entity_type="job",
        entity_id=job.id,
        detail={
            "model": settings.scoring_model,
            "fit_score": job.fit_score,
            "expected_value": job.expected_value,
            "success_band": success_band(success_probability),
            "application_effort": application_effort,
            "summary": rationale.get("summary"),
            "tokens_in": usage.get("input_tokens"),
            "tokens_out": usage.get("output_tokens"),
            # TP-07: persist the full rationale so a re-score (which overwrites
            # job.score_rationale in place) stays reconstructable from the audit log.
            "rationale": {k: v for k, v in rationale.items() if k != "_usage"},
        },
    )

    # KG-02: extract the scored JD's demand facets for the coverage map.
    # Derived metadata only — skipped without an Anthropic key (or an injected
    # assigner), and a failure never fails the scoring path.
    if facet_assigner is None and facets_available(settings):
        facet_assigner = build_default_facet_assigner(
            settings, session=session, entity_type="job", entity_id=job.id
        )
    if facet_assigner is not None:
        try:
            assign_job_facets(session, job, assigner=facet_assigner, settings=settings)
        except Exception as exc:
            session.rollback()
            log_action_safe(
                session,
                actor=ActorType.system,
                action="job_facets_failed",
                entity_type="job",
                entity_id=job.id,
                detail={"error": str(exc)},
            )
    return job
