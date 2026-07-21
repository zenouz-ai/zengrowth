"""EA-04: cross-process advisory lock + lock-guarded run_all."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from zengrowth.ingestion.locking import (
    acquire_lock,
    last_completed_at,
    release_lock,
    scheduler_lock,
)
from zengrowth.ingestion.runner import INGEST_LOCK_NAME, run_all
from zengrowth.models import SchedulerLock


def test_acquire_is_mutually_exclusive(session: Session):
    engine = session.get_bind()
    assert acquire_lock(engine, "job", ttl_seconds=3600) is True
    # A second acquire while held must fail.
    assert acquire_lock(engine, "job", ttl_seconds=3600) is False
    release_lock(engine, "job")
    # After release it is free again.
    assert acquire_lock(engine, "job", ttl_seconds=3600) is True


def test_expired_lock_self_heals(session: Session):
    engine = session.get_bind()
    assert acquire_lock(engine, "job", ttl_seconds=3600) is True
    # Force the lock to look expired (simulate a crashed holder).
    row = session.get(SchedulerLock, "job")
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.add(row)
    session.commit()
    assert acquire_lock(engine, "job", ttl_seconds=3600) is True


def test_release_records_last_completed(session: Session):
    engine = session.get_bind()
    acquire_lock(engine, "job", ttl_seconds=3600)
    assert last_completed_at(engine, "job") is None
    release_lock(engine, "job", completed=True)
    assert last_completed_at(engine, "job") is not None


def test_release_does_not_clear_a_taken_over_lock(session: Session):
    # EA-04 review: if our lock expired and another holder took it over, our
    # release must not free the new holder's lock.
    engine = session.get_bind()
    assert acquire_lock(engine, "job", ttl_seconds=3600, holder="runner-A") is True
    # Simulate expiry + takeover by a second runner.
    row = session.get(SchedulerLock, "job")
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.add(row)
    session.commit()
    assert acquire_lock(engine, "job", ttl_seconds=3600, holder="runner-B") is True
    # Runner A finishes late and releases with its own token: must be a no-op.
    release_lock(engine, "job", holder="runner-A")
    refreshed = Session(engine).get(SchedulerLock, "job")
    assert refreshed.locked is True
    assert refreshed.holder == "runner-B"


def test_scheduler_lock_contextmanager_yields_false_when_held(session: Session):
    engine = session.get_bind()
    acquire_lock(engine, "job", ttl_seconds=3600)
    with scheduler_lock(engine, "job", ttl_seconds=3600) as acquired:
        assert acquired is False


def test_run_all_skips_when_lock_held(session: Session, monkeypatch):
    # Hold the ingest lock, then run_all must skip without fetching any board.
    engine = session.get_bind()
    assert acquire_lock(engine, INGEST_LOCK_NAME, ttl_seconds=3600) is True

    def _boom(*args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("run_all should not fetch boards while locked")

    monkeypatch.setattr("zengrowth.ingestion.runner.fetch_greenhouse", _boom)
    monkeypatch.setattr("zengrowth.ingestion.runner.fetch_lever", _boom)

    result = run_all(session=session)
    assert result.skipped_locked is True
    assert result.added == 0


def test_run_all_runs_when_lock_free(session: Session, monkeypatch):
    # With no boards configured the body runs to completion and stamps the lock.
    from zengrowth.config import Settings

    monkeypatch.setattr(
        "zengrowth.ingestion.runner.get_settings",
        lambda: Settings(ats_boards=[], ingestion_precheck_on_run=False),
    )
    result = run_all(session=session)
    assert result.skipped_locked is False
    # Lock was released and completion stamped.
    assert last_completed_at(session.get_bind(), INGEST_LOCK_NAME) is not None
