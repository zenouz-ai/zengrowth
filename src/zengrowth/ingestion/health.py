"""Ingestion liveness/readiness signals + the dead-man's-switch heartbeat (SEC-01/SEC-09).

A career tool that quietly stops is worse than one that loudly fails: an empty
board reads as "no new roles" when the truth is "the pull died days ago." These
helpers turn that invisible failure into a readable signal:

- ``ingestion_health`` reports when the pipeline last *successfully* completed,
  whether that is now stale, and which boards returned zero rows or failed in the
  most recent run — consumed by ``/health/ready`` (operator's external monitor)
  and ``/api/ingestion/health`` (the dashboard staleness banner).
- ``send_ingest_heartbeat`` pings an external uptime monitor after each successful
  run. The monitor alarms on the *absence* of a ping, so it catches the one
  failure the app itself can never report (the whole process being down).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import desc
from sqlmodel import Session, select

from ..config import Settings
from ..models import PipelineRun, SchedulerLock
from .runner import INGEST_LOCK_NAME

if TYPE_CHECKING:
    from .runner import IngestionResult

_logger = logging.getLogger(__name__)

_HEARTBEAT_TIMEOUT_SECONDS = 10.0


@dataclass
class IngestionHealth:
    """Snapshot of nightly-ingestion health for readiness probes and the banner."""

    last_completed_at: datetime | None = None
    age_seconds: float | None = None
    stale: bool = False
    never_run: bool = True
    added: int | None = None
    zero_row_boards: list[str] = field(default_factory=list)
    failed_boards: list[str] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        """True when the operator should look: stale, or last run lost a board."""
        return self.stale or bool(self.zero_row_boards) or bool(self.failed_boards)


def _last_ingestion_run_detail(session: Session) -> dict[str, Any]:
    row = session.exec(
        select(PipelineRun)
        .where(PipelineRun.pipeline_type == "ingestion")
        .order_by(desc(PipelineRun.started_at))
    ).first()
    if row is None or not row.detail:
        return {}
    result = row.detail.get("result")
    return result if isinstance(result, dict) else {}


def ingestion_health(session: Session, settings: Settings, *, now: datetime | None = None) -> IngestionHealth:
    """Derive ingestion health from the scheduler lock + the latest ingestion run."""
    now = now or datetime.now(UTC)
    health = IngestionHealth()

    lock = session.get(SchedulerLock, INGEST_LOCK_NAME)
    last = lock.last_completed_at if lock else None
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        health.last_completed_at = last
        health.never_run = False
        age = (now - last).total_seconds()
        health.age_seconds = age
        health.stale = age > settings.ingestion_stale_after_hours * 3600

    detail = _last_ingestion_run_detail(session)
    if detail:
        health.added = detail.get("added")
        zero = detail.get("zero_row_boards") or []
        failed = detail.get("failed_boards") or []
        health.zero_row_boards = [str(b) for b in zero]
        health.failed_boards = [str(b) for b in failed]
    return health


def send_ingest_heartbeat(settings: Settings, result: IngestionResult) -> None:
    """Ping the external dead-man's-switch monitor after a completed run (fail-open).

    No-op unless ``ingest_heartbeat_url`` is configured, so the test suite and
    unconfigured installs never make a network call. A failed ping must never
    affect ingestion — the monitor will simply notice a missing beat next cycle.
    """
    url = settings.ingest_heartbeat_url
    if not url:
        return
    try:
        httpx.get(url, timeout=_HEARTBEAT_TIMEOUT_SECONDS)
    except Exception:  # pragma: no cover - network best-effort; never break ingest
        _logger.warning("ingest heartbeat ping failed", exc_info=True)
