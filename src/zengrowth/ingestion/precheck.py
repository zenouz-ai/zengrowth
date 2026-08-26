"""Pre-pipeline intake checks for newly discovered jobs.

The pipeline is an operator surface, not a raw ATS dump. This module keeps
obvious noise out cheaply, then uses the existing summarizer/scorer for roles
that look plausibly relevant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlmodel import Session, select

from ..audit import log_action
from ..config import Settings, get_settings
from ..jobs.curation import is_curated_pipeline_job
from ..models import ActorType, Job, JobSource, LifecycleState
from ..observability.tracing import record_step, tool_step
from ..scoring.scorer import score_job
from .job_summarizer import summarize_job

_AI_TERMS = (
    "ai",
    "artificial intelligence",
    "machine learning",
    "ml",
    "llm",
    "nlp",
    "deep learning",
    "data science",
    "data scientist",
    "applied scientist",
    "research scientist",
    "research engineer",
    "analytics",
    "genai",
    "generative",
    "agentic",
    "automation",
)
# Seniority markers. Includes flat/odd senior titles used at frontier labs and
# startups ("Member of Technical Staff", "Founding ...", "Distinguished ...").
_SENIOR_TERMS = (
    "head",
    "director",
    "vp",
    "vice president",
    "chief",
    "lead",
    "principal",
    "staff",
    "senior",
    "manager",
    "founding",
    "founder",
    "distinguished",
    "fellow",
    "member of technical staff",
    "architect",
    "strategy",
    "strategic",
)
# Unambiguous non-target roles. Title-only and deliberately narrow: we no longer
# blanket-exclude "engineer"/"developer" titles, which were archiving genuinely
# senior AI roles (e.g. "Staff ML Engineer", "Founding ML Engineer").
_HARD_EXCLUDE_TERMS = (
    "customer support",
    "technical support",
    "support specialist",
    "sales",
    "account executive",
    "recruiter",
    "intern",
    "graduate",
    "business development",
    "campaign",
    "creative director",
    "design program",
    "finops",
    "marketing",
    "paid digital",
    "partner marketing",
)

# How much of the description to scan when the title alone is ambiguous.
_DESCRIPTION_LEAD_CHARS = 600


def _compile_terms(terms: tuple[str, ...]) -> re.Pattern[str]:
    # Word-boundary matching so short tokens like "ai"/"ml"/"vp" don't fire on
    # substrings ("maintain", "html", "vpc") when scanning free-text descriptions.
    return re.compile(r"\b(?:" + "|".join(re.escape(t) for t in terms) + r")\b", re.IGNORECASE)


_AI_RE = _compile_terms(_AI_TERMS)
_SENIOR_RE = _compile_terms(_SENIOR_TERMS)


@dataclass
class PrecheckResult:
    prechecked: int = 0
    archived: int = 0
    failed: int = 0


@dataclass(frozen=True)
class RelevanceSignal:
    """Why a job did or didn't pass the cheap precheck.

    ``matched_on`` lets a later review surface (TA-06) distinguish confident
    title matches from softer description-assisted ones.
    """

    relevant: bool
    reason: str  # title_match | description_assisted | hard_excluded | no_signal
    matched_on: str  # title | description | none


def _matches(text: str, pattern: re.Pattern[str]) -> bool:
    return pattern.search(text) is not None


def _excluded(title: str) -> bool:
    # Substring (not word-boundary) so the curated denylist also catches plurals
    # like "Campaigns". Title-only and deliberately narrow.
    low = title.lower()
    return any(term in low for term in _HARD_EXCLUDE_TERMS)


def relevance_signal(job: Job) -> RelevanceSignal:
    """Cheap, no-LLM relevance check.

    A senior AI/data role needs both an AI signal and a seniority signal. The
    title is checked first; when it is ambiguous, the start of the description
    can supply the missing signal (recall over precision — the scorer makes the
    final call). Unambiguous non-target titles are excluded outright.
    """
    title = job.title or ""
    if _excluded(title):
        return RelevanceSignal(False, "hard_excluded", "title")
    if _matches(title, _AI_RE) and _matches(title, _SENIOR_RE):
        return RelevanceSignal(True, "title_match", "title")
    lead = f"{title} {(job.description or '')[:_DESCRIPTION_LEAD_CHARS]}"
    if _matches(lead, _AI_RE) and _matches(lead, _SENIOR_RE):
        return RelevanceSignal(True, "description_assisted", "description")
    return RelevanceSignal(False, "no_signal", "none")


def looks_plausibly_relevant(job: Job) -> bool:
    """Cheap first-pass filter for roles worth spending LLM calls on."""
    return relevance_signal(job).relevant


def is_pipeline_ready(job: Job, *, settings: Settings | None = None) -> bool:
    """True when a job belongs on the curated board (used after batch precheck)."""
    return is_curated_pipeline_job(job, settings=settings)


def _archive(session: Session, job: Job, reason: str, detail: dict | None = None) -> None:
    job.lifecycle_state = LifecycleState.archived
    job.updated_at = datetime.now(UTC)
    session.add(job)
    session.commit()
    session.refresh(job)
    log_action(
        session,
        actor=ActorType.agent,
        action="precheck_archive_job",
        entity_type="job",
        entity_id=job.id,
        detail={"reason": reason, **(detail or {})},
    )


def precheck_job(
    session: Session,
    job: Job,
    *,
    settings: Settings | None = None,
) -> bool:
    """Clean and score one job. Returns True when it is pipeline-ready."""
    settings = settings or get_settings()
    signal = relevance_signal(job)
    if not signal.relevant:
        record_step(
            session,
            step_name="relevance_filter",
            step_type="decision",
            duration_ms=0,
            decision="archive",
            detail={"reason": signal.reason, "job_id": job.id},
        )
        _archive(session, job, "cheap_filter_not_target_role", {"signal": signal.reason})
        return False

    if job.summary_updated_at is None or job.job_summary is None:
        with tool_step(session, step_name="summarize_job", step_type="llm", detail={"job_id": job.id}):
            summarize_job(session, job, settings=settings)
    if job.fit_score is None or job.expected_value is None or job.score_rationale is None:
        with tool_step(session, step_name="score_job", step_type="llm", detail={"job_id": job.id}):
            score_job(session, job, settings=settings)

    if not is_pipeline_ready(job, settings=settings):
        record_step(
            session,
            step_name="pipeline_threshold",
            step_type="decision",
            duration_ms=0,
            decision="archive",
            detail={"fit_score": job.fit_score, "expected_value": job.expected_value},
        )
        _archive(
            session,
            job,
            "below_pipeline_threshold",
            {"fit_score": job.fit_score, "expected_value": job.expected_value},
        )
        return False

    # TP-08: a passed job leaves `discovered` so "pipeline-ready" is a state,
    # not a predicate — the nightly batch (which selects `discovered` only)
    # stops re-selecting and re-checking jobs that already passed.
    if job.lifecycle_state == LifecycleState.discovered:
        job.lifecycle_state = LifecycleState.shortlisted
        job.updated_at = datetime.now(UTC)
        session.add(job)
        session.commit()
        session.refresh(job)
    record_step(
        session,
        step_name="precheck_pass",
        step_type="decision",
        duration_ms=0,
        decision="keep",
        detail={"fit_score": job.fit_score, "matched_on": signal.matched_on},
    )
    log_action(
        session,
        actor=ActorType.agent,
        action="precheck_job",
        entity_type="job",
        entity_id=job.id,
        detail={
            "fit_score": job.fit_score,
            "expected_value": job.expected_value,
            "matched_on": signal.matched_on,
            "lifecycle_state": job.lifecycle_state.value,
        },
    )
    return True


def precheck_jobs(
    session: Session,
    *,
    limit: int = 50,
    settings: Settings | None = None,
) -> PrecheckResult:
    settings = settings or get_settings()
    stmt = (
        select(Job)
        .where(Job.lifecycle_state == LifecycleState.discovered)
        .order_by(Job.created_at.desc())  # type: ignore[union-attr]
        .limit(limit)
    )
    result = PrecheckResult()
    for job in list(session.exec(stmt)):
        # Operator-pasted jobs are never batch-prechecked; they stay visible once prepared.
        if job.source == JobSource.manual:
            continue
        try:
            ready = precheck_job(session, job, settings=settings)
            result.prechecked += 1
            if not ready:
                result.archived += 1
        except (RuntimeError, ValueError):
            result.failed += 1
            log_action(
                session,
                actor=ActorType.agent,
                action="precheck_job_failed",
                entity_type="job",
                entity_id=job.id,
                detail={"company": job.company, "title": job.title},
            )
    return result
