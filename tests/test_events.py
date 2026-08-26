"""Phase 5: SSE audit stream and the fail-open logger."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from zengrowth.api.main import create_app
from zengrowth.api.routers import events
from zengrowth.audit import log_action, log_action_safe
from zengrowth.config import Settings, get_settings
from zengrowth.models import ActorType, AuditLog


def _factory(session: Session):
    @contextmanager
    def factory() -> Iterator[Session]:
        yield session  # reuse the fixture session; do not close it

    return factory


async def _collect(gen) -> list[str]:
    return [frame async for frame in gen]


def _seed(session: Session, action: str, ts: datetime) -> AuditLog:
    entry = AuditLog(actor=ActorType.human, action=action, timestamp=ts)
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def test_stream_emits_frames_for_new_rows(session: Session):
    _seed(session, "create_job", datetime(2026, 6, 1, tzinfo=UTC))
    _seed(session, "score_job", datetime(2026, 6, 2, tzinfo=UTC))

    frames = asyncio.run(
        _collect(events.audit_event_stream(session_factory=_factory(session), max_polls=1))
    )
    audit_frames = [f for f in frames if f.startswith("id:")]
    assert len(audit_frames) == 2
    assert "event: audit" in audit_frames[0]
    assert "create_job" in audit_frames[0]


def test_stream_resumes_from_since_cursor(session: Session):
    first = _seed(session, "create_job", datetime(2026, 6, 1, tzinfo=UTC))
    _seed(session, "score_job", datetime(2026, 6, 2, tzinfo=UTC))

    frames = asyncio.run(
        _collect(
            events.audit_event_stream(
                since=first.id, session_factory=_factory(session), max_polls=1
            )
        )
    )
    audit_frames = [f for f in frames if f.startswith("id:")]
    assert len(audit_frames) == 1
    assert "score_job" in audit_frames[0]


def test_stream_does_not_drop_same_timestamp_rows(session: Session):
    """EA-06: rows sharing a timestamp must each advance the id cursor on resume."""
    ts = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
    first = _seed(session, "create_job", ts)
    _seed(session, "llm_call", ts)  # identical timestamp, higher id
    _seed(session, "score_job", ts)

    # Resume after the first row: both later same-timestamp rows must still arrive.
    frames = asyncio.run(
        _collect(
            events.audit_event_stream(
                since=first.id, session_factory=_factory(session), max_polls=1
            )
        )
    )
    audit_frames = [f for f in frames if f.startswith("id:")]
    assert len(audit_frames) == 2
    assert "llm_call" in audit_frames[0]
    assert "score_job" in audit_frames[1]
    # The emitted SSE id is the integer PK, not the timestamp.
    assert audit_frames[0].startswith(f"id: {first.id + 1}")


def test_stream_emits_keepalive_when_idle(session: Session):
    frames = asyncio.run(
        _collect(events.audit_event_stream(session_factory=_factory(session), max_polls=1))
    )
    assert frames == [": keepalive\n\n"]


def test_stream_returns_503_when_disabled(monkeypatch):
    monkeypatch.setattr(
        "zengrowth.api.routers.events.get_settings",
        lambda: Settings(_env_file=None, feature_sse=False),
    )
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        assert client.get("/api/events/stream").status_code == 503
    finally:
        get_settings.cache_clear()


def test_log_action_safe_swallows_failures(monkeypatch, session: Session):
    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr("zengrowth.audit.log_action", boom)
    # Must not raise, returns None on failure.
    assert log_action_safe(session, actor=ActorType.system, action="noop") is None


def test_log_action_safe_writes_on_success(session: Session):
    entry = log_action_safe(session, actor=ActorType.system, action="ok")
    assert entry is not None
    assert entry.action == "ok"


# log_action is still fail-closed for business-critical rows.
def test_log_action_still_raises_on_failure(monkeypatch, session: Session):
    monkeypatch.setattr(session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(RuntimeError):
        log_action(session, actor=ActorType.system, action="critical")
