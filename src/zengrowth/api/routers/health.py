"""Health probes. Mounted unprefixed and on the auth allowlist.

``/health`` is the liveness probe (always ``{"status": "ok"}``). ``/health/ready``
is the readiness probe an external dead-man's-switch monitor polls (SEC-09): it
reports whether the DB is writable and how long it has been since ingestion last
*successfully* completed, so a silently-stopped pipeline can't masquerade as a
healthy service. It exposes only status booleans — board names stay behind
operator auth on ``/api/ingestion/health``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlmodel import Session

from ...config import get_settings
from ...db import get_session
from ...ingestion.health import ingestion_health
from ..schemas import HealthReadyOut

router = APIRouter(tags=["health"])

_logger = logging.getLogger(__name__)


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/health/ready", response_model=HealthReadyOut)
def health_ready(response: Response, session: Session = Depends(get_session)) -> HealthReadyOut:
    """Readiness: DB writable + ingestion freshness. 503 when a check fails."""
    settings = get_settings()

    db_writable = True
    try:
        session.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover - defensive; a dead DB is the whole point
        db_writable = False
        _logger.warning("readiness probe: database not reachable", exc_info=True)

    health = None
    try:
        health = ingestion_health(session, settings)
    except Exception:  # pragma: no cover - never let readiness itself 500
        _logger.warning("readiness probe: ingestion health unavailable", exc_info=True)

    stale = bool(health.stale) if health else False
    out = HealthReadyOut(
        status="ok" if (db_writable and not stale) else "degraded",
        db_writable=db_writable,
        last_ingest_age_seconds=health.age_seconds if health else None,
        ingest_stale=stale,
        ingest_never_run=health.never_run if health else True,
    )
    if not db_writable or stale:
        response.status_code = 503
    return out
