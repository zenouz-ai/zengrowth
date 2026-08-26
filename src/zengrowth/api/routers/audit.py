"""Audit domain: recent audit-log entries (operator-only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ...db import get_session
from ...models import AuditLog

router = APIRouter(tags=["audit"])


@router.get("/audit")
def audit_recent(limit: int = 100, session: Session = Depends(get_session)) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit)  # type: ignore[union-attr]
    return list(session.exec(stmt))
