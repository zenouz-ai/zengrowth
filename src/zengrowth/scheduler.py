"""APScheduler in-process. Nightly ATS pull at INGESTION_HOUR.

Celery is # TODO(phase-3) if scale demands it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import get_settings
from .db import get_engine
from .ingestion.locking import last_completed_at
from .ingestion.runner import INGEST_LOCK_NAME, run_all

_logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None

# A nightly cadence is "missed" once the last completed run is older than a day
# plus a buffer — catch up on boot so a process down at INGESTION_HOUR still runs.
_CATCHUP_STALE = timedelta(hours=25)


def _ingest_job() -> None:
    try:
        result = run_all()
        if result.skipped_locked:
            _logger.info("scheduled ingestion skipped: another run holds the lock")
            return
        _logger.info(
            "scheduled ingestion done: +%d added, %d dup, %d stale, %d boards failed",
            result.added,
            result.skipped_duplicate,
            result.skipped_stale,
            len(result.failed_boards),
        )
    except Exception:  # pragma: no cover  # defensive: keep scheduler alive
        _logger.exception("scheduled ingestion failed")


def _maybe_catch_up(sched: BackgroundScheduler) -> None:
    """Run one ingest shortly after boot when the last completed run is stale.

    The advisory lock makes this safe even if the regular cron fires concurrently.
    """
    last = last_completed_at(get_engine(), INGEST_LOCK_NAME)
    if last is None:
        return  # never ran (fresh install) — don't surprise a new operator with spend
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    if datetime.now(UTC) - last < _CATCHUP_STALE:
        return
    sched.add_job(
        _ingest_job,
        id="ingest_catchup",
        replace_existing=True,
        next_run_time=datetime.now(UTC) + timedelta(seconds=20),
    )
    _logger.info("scheduled catch-up ingest; last completed run was %s", last.isoformat())


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    settings = get_settings()
    sched = BackgroundScheduler(daemon=True)
    sched.add_job(
        _ingest_job,
        CronTrigger(hour=settings.ingestion_hour, minute=0),
        id="nightly_ingest",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=settings.ingestion_misfire_grace_seconds,
    )
    sched.start()
    _scheduler = sched
    if settings.ingestion_catchup_on_start:
        try:
            _maybe_catch_up(sched)
        except Exception:  # pragma: no cover - catch-up must never block boot
            _logger.exception("ingest catch-up check failed")
    _logger.info("scheduler started; nightly ingest at hour=%d", settings.ingestion_hour)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
