"""SQLite allowlist for operator session ids (SEC-03).

HMAC on the cookie proves it was issued by us; this table is what makes logout
and a full wipe real. Fail closed: a DB error is treated as unauthenticated.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from ..db import get_engine
from ..models import OperatorSession
from .security import parse_session_cookie


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def create_operator_session(session_id: str, *, ttl_seconds: int) -> None:
    now = _now()
    row = OperatorSession(
        id=session_id,
        created_at=now,
        expires_at=now + timedelta(seconds=int(ttl_seconds)),
    )
    with Session(get_engine()) as db:
        db.add(row)
        _purge_expired(db, now=now)
        db.commit()


def operator_session_is_active(session_id: str, *, now: datetime | None = None) -> bool:
    if not session_id:
        return False
    moment = now or _now()
    try:
        with Session(get_engine()) as db:
            row = db.get(OperatorSession, session_id)
    except Exception:
        return False
    if row is None or row.revoked_at is not None:
        return False
    return _aware(row.expires_at) > moment


def revoke_operator_session(session_id: str) -> None:
    if not session_id:
        return
    with Session(get_engine()) as db:
        row = db.get(OperatorSession, session_id)
        if row is None or row.revoked_at is not None:
            return
        row.revoked_at = _now()
        db.add(row)
        db.commit()


def revoke_all_operator_sessions() -> int:
    """Invalidate every live session (secret rotation / wipe)."""
    now = _now()
    with Session(get_engine()) as db:
        live = list(
            db.exec(select(OperatorSession).where(OperatorSession.revoked_at.is_(None)))
        )
        for row in live:
            row.revoked_at = now
            db.add(row)
        db.commit()
        return len(live)


def is_live_session_cookie(secret: str, value: str, *, now: int | None = None) -> bool:
    payload = parse_session_cookie(secret, value, now=now)
    if not payload:
        return False
    return operator_session_is_active(str(payload["sid"]))


def _purge_expired(db: Session, *, now: datetime) -> None:
    stale = list(db.exec(select(OperatorSession).where(OperatorSession.expires_at <= now)))
    for row in stale:
        db.delete(row)
