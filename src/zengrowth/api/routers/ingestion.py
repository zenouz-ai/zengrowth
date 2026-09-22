"""Ingestion domain: trigger ATS pulls and report configured boards."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlmodel import Session

from ...config import get_settings
from ...db import get_session
from ...ingestion.health import ingestion_health
from ...ingestion.runner import run_all
from ..schemas import IngestionConfigOut, IngestionHealthOut, IngestionStartedOut

router = APIRouter(tags=["ingestion"])

_logger = logging.getLogger(__name__)


def run_ingestion_job() -> None:
    """Run a full ingest in the background.

    ``POST /ingestion/run`` returns immediately (202) and schedules this, because
    the pull plus the bounded precheck can be ~150s of inline LLM scoring — far
    longer than the edge proxy's ~100s request timeout, which otherwise surfaced a
    false "ingestion failed" while the work actually completed. ``run_all`` opens
    its own session (never the request-scoped one, which is closed once the
    response is sent) and takes the advisory lock, so a click overlapping the
    nightly cron — or a double-click — simply no-ops instead of double-spending.
    """
    try:
        result = run_all()
        if result.skipped_locked:
            _logger.info("manual ingestion skipped: another run holds the lock")
        else:
            _logger.info(
                "manual ingestion done: +%d added, %d dup, %d stale, "
                "prechecked=%d archived=%d boards_failed=%d",
                result.added,
                result.skipped_duplicate,
                result.skipped_stale,
                result.prechecked,
                result.archived,
                len(result.failed_boards),
            )
    except Exception:  # pragma: no cover - a background failure must not crash the worker
        _logger.exception("manual ingestion failed")


@router.post("/ingestion/run", response_model=IngestionStartedOut, status_code=202)
def ingest(background_tasks: BackgroundTasks) -> IngestionStartedOut:
    """Kick off ingestion in the background and return immediately.

    Progress streams to the dashboard over the live audit feed (ingest/score
    events); new roles appear on the Jobs board once scored.
    """
    background_tasks.add_task(run_ingestion_job)
    return IngestionStartedOut(status="started")


@router.get("/ingestion/config", response_model=IngestionConfigOut)
def ingestion_config() -> IngestionConfigOut:
    settings = get_settings()
    return IngestionConfigOut(
        ats_boards=settings.ats_boards,
        max_posting_age_days=settings.max_posting_age_days,
        ingestion_hour=settings.ingestion_hour,
        tavily_configured=bool(settings.tavily_api_key),
    )


@router.get("/ingestion/health", response_model=IngestionHealthOut)
def ingestion_health_status(session: Session = Depends(get_session)) -> IngestionHealthOut:
    """Operator-gated ingestion health for the dashboard staleness banner (SEC-01)."""
    health = ingestion_health(session, get_settings())
    return IngestionHealthOut(
        last_completed_at=health.last_completed_at,
        age_seconds=health.age_seconds,
        stale=health.stale,
        never_run=health.never_run,
        degraded=health.degraded,
        added=health.added,
        zero_row_boards=health.zero_row_boards,
        failed_boards=health.failed_boards,
    )
