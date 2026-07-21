"""Public, anonymous observability surface.

Every endpoint returns aggregates only — counts, histogram buckets, weekly
transition tallies — with small-count suppression (k-anonymity) so a single job
can never be singled out. No company/title/url/comp/material data is exposed.
Gated by ``feature_public_observability``: when off, the surface returns 503.

k-anonymity (SEC-05): partition endpoints (pipeline / scores / velocity) use
*complementary* suppression — hiding a lone small cell would let an observer
recover it as ``total - sum(revealed)``, so a second cell is hidden too. The
honest limit is that at audience-of-one scale these aggregates describe one known
person's search; this prevents singling out a *job*, not identifying the
*operator*. That caveat is stated on the public page.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ...config import get_settings
from ...db import get_session
from ...models import AuditLog, Job, LifecycleState
from ..kanon import suppress_count as _suppress_small_count
from ..kanon import suppress_partition
from ..schemas_public import (
    PublicPipelineOut,
    PublicScoreBucketOut,
    PublicScoreHistogramOut,
    PublicStateCountOut,
    PublicSummaryOut,
    PublicVelocityOut,
    PublicVelocityPointOut,
)

router = APIRouter(tags=["public"])

# Cap on how many weeks of velocity history are exposed.
_MAX_WEEKS = 12
_SCORE_BUCKETS = ((0, 20), (20, 40), (40, 60), (60, 80), (80, 100))


def _week_label(value: date | datetime) -> str:
    iso = value.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _recent_week_labels(*, anchor: date | None = None) -> list[str]:
    today = anchor or datetime.now(UTC).date()
    week_start = today - timedelta(days=today.weekday())
    starts = [week_start - timedelta(weeks=offset) for offset in range(_MAX_WEEKS - 1, -1, -1)]
    return [_week_label(start) for start in starts]


def _require_enabled() -> None:
    if not get_settings().feature_public_observability:
        raise HTTPException(status_code=503, detail="public observability is disabled")


@router.get("/public/summary", response_model=PublicSummaryOut)
def public_summary(session: Session = Depends(get_session)) -> PublicSummaryOut:
    _require_enabled()
    jobs = session.exec(select(Job)).all()
    counts = Counter(j.lifecycle_state for j in jobs)
    total_jobs, total_suppressed = _suppress_small_count(len(jobs))
    applied, applied_suppressed = _suppress_small_count(counts.get(LifecycleState.applied, 0))
    interviewing, interviewing_suppressed = _suppress_small_count(
        counts.get(LifecycleState.interviewing, 0)
    )
    offers, offers_suppressed = _suppress_small_count(counts.get(LifecycleState.offer, 0))
    return PublicSummaryOut(
        total_jobs=total_jobs,
        applied=applied,
        interviewing=interviewing,
        offers=offers,
        suppressed=max(
            total_suppressed,
            applied_suppressed + interviewing_suppressed + offers_suppressed,
        ),
    )


@router.get("/public/pipeline", response_model=PublicPipelineOut)
def public_pipeline(session: Session = Depends(get_session)) -> PublicPipelineOut:
    _require_enabled()
    counts = Counter(j.lifecycle_state for j in session.exec(select(Job)).all())
    # Enum order is the canonical board order; expose every state (counts only).
    # A full partition, so use complementary suppression (SEC-05): a single hidden
    # state is otherwise recoverable as total - sum(revealed states).
    ordered = list(LifecycleState)
    public_counts, suppressed = suppress_partition([counts.get(state, 0) for state in ordered])
    states = [
        PublicStateCountOut(state=state.value, count=count)
        for state, count in zip(ordered, public_counts, strict=True)
    ]
    return PublicPipelineOut(
        states=states,
        suppressed=suppressed,
    )


@router.get("/public/scores", response_model=PublicScoreHistogramOut)
def public_scores(session: Session = Depends(get_session)) -> PublicScoreHistogramOut:
    _require_enabled()
    scores = [j.fit_score for j in session.exec(select(Job)).all() if j.fit_score is not None]
    raw_counts: list[int] = []
    for low, high in _SCORE_BUCKETS:
        # Top bucket is inclusive of the max so a perfect score still lands.
        in_bucket = [s for s in scores if low <= s < high or (high == 100 and s == 100)]
        raw_counts.append(len(in_bucket))
    # The buckets partition all scored jobs, so complementary suppression (SEC-05).
    public_counts, suppressed = suppress_partition(raw_counts)
    buckets = [
        PublicScoreBucketOut(label=f"{low}-{high}", count=count)
        for (low, high), count in zip(_SCORE_BUCKETS, public_counts, strict=True)
    ]
    return PublicScoreHistogramOut(buckets=buckets, suppressed=suppressed)


@router.get("/public/velocity", response_model=PublicVelocityOut)
def public_velocity(session: Session = Depends(get_session)) -> PublicVelocityOut:
    _require_enabled()
    rows = session.exec(select(AuditLog).where(AuditLog.action == "change_state")).all()
    per_week: Counter[str] = Counter()
    for row in rows:
        per_week[_week_label(row.timestamp)] += 1
    weeks = _recent_week_labels()
    # The exposed weeks partition the recent transition history, so complementary
    # suppression (SEC-05) keeps a single active week from being differenced out.
    public_counts, suppressed = suppress_partition([per_week.get(week, 0) for week in weeks])
    points = [
        PublicVelocityPointOut(week=week, transitions=count)
        for week, count in zip(weeks, public_counts, strict=True)
    ]
    return PublicVelocityOut(
        points=points,
        suppressed=suppressed,
    )
