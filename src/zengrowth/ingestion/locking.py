"""Cross-process advisory lock for scheduled ingestion (EA-04).

APScheduler runs in-process, so without coordination two API replicas (or a
manual ``POST /ingestion/run`` colliding with the nightly cron) would each run
``run_all`` at once and double-spend LLM calls. This module provides a small
SQLite-backed advisory lock keyed by job name, acquired via a single atomic
conditional ``UPDATE`` so only one holder can win, with a TTL that self-heals a
crashed holder. It also records ``last_completed_at`` for startup catch-up.
"""

from __future__ import annotations

import logging
import os
import socket
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, update

from ..models import SchedulerLock

_logger = logging.getLogger(__name__)


def holder_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _ensure_row(session: Session, name: str) -> None:
    if session.get(SchedulerLock, name) is None:
        try:
            session.add(SchedulerLock(name=name, locked=False))
            session.commit()
        except Exception:
            # A concurrent acquirer created it first; that is fine.
            session.rollback()


def acquire_lock(engine: Engine, name: str, *, ttl_seconds: int, holder: str | None = None) -> bool:
    """Atomically take the named lock. Returns True iff this caller won it.

    The conditional UPDATE only matches when the lock is free or its TTL has
    expired, so concurrent callers serialize on SQLite's write lock and exactly
    one sees ``rowcount == 1``.
    """
    holder = holder or holder_id()
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=max(1, ttl_seconds))
    try:
        with Session(engine) as session:
            _ensure_row(session, name)
            stmt = (
                update(SchedulerLock)
                .where(SchedulerLock.name == name)
                .where(
                    (SchedulerLock.locked == False)  # noqa: E712 - SQL column comparison
                    | (SchedulerLock.expires_at == None)  # noqa: E711
                    | (SchedulerLock.expires_at < now)
                )
                .values(locked=True, holder=holder, acquired_at=now, expires_at=expires)
            )
            result = session.execute(stmt)
            session.commit()
            return result.rowcount == 1
    except OperationalError:
        # Another writer holds the database lock — treat as "already running".
        _logger.warning("scheduler lock %s contended; skipping run", name)
        return False


def release_lock(
    engine: Engine, name: str, *, holder: str | None = None, completed: bool = True
) -> None:
    """Release the named lock; record ``last_completed_at`` on a successful run.

    When ``holder`` is given, only release if the row is still held by that
    token: if this runner's lock already expired and was taken over by another
    replica, clearing it unconditionally would free the *new* holder's lock and
    let a third run start concurrently (EA-04 review).
    """
    now = datetime.now(UTC)
    with Session(engine) as session:
        row = session.get(SchedulerLock, name)
        if row is None:
            return
        if holder is not None and row.holder != holder:
            return  # our lock was taken over; leave the current holder alone
        row.locked = False
        row.holder = None
        row.expires_at = None
        if completed:
            row.last_completed_at = now
        session.add(row)
        session.commit()


def last_completed_at(engine: Engine, name: str) -> datetime | None:
    with Session(engine) as session:
        row = session.get(SchedulerLock, name)
        return row.last_completed_at if row else None


@contextmanager
def scheduler_lock(engine: Engine, name: str, *, ttl_seconds: int):
    """Context manager that yields True if the lock was acquired, else False.

    Releases only when this caller actually held it, and stamps completion only
    when the guarded body finished without raising — a crashed run must not look
    "completed" or it would suppress the startup catch-up.
    """
    token = f"{holder_id()}:{uuid.uuid4().hex[:8]}"
    acquired = acquire_lock(engine, name, ttl_seconds=ttl_seconds, holder=token)
    completed = False
    try:
        yield acquired
        completed = True
    finally:
        if acquired:
            release_lock(engine, name, holder=token, completed=completed)
