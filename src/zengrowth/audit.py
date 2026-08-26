"""Audit logging helper. Every meaningful agent/human action calls log_action()."""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from sqlmodel import Session

from .models import ActorType, AuditLog

logger = logging.getLogger(__name__)


def log_action(
    session: Session,
    *,
    actor: ActorType,
    action: str,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        detail=detail,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def log_action_safe(session: Session, **kwargs: Any) -> AuditLog | None:
    """Fail-open variant for instrumentation-only call sites.

    Pure telemetry must never block or break the request it instruments, so any
    failure is swallowed and logged. Business-critical audit rows keep using the
    fail-closed ``log_action`` so a lost record surfaces as an error.
    """
    try:
        return log_action(session, **kwargs)
    except Exception:  # noqa: BLE001 - instrumentation must not propagate
        logger.warning("log_action_safe swallowed an audit failure", exc_info=True)
        with contextlib.suppress(Exception):
            session.rollback()
        return None
