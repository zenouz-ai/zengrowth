"""Server-sent events over the AuditLog table (operator-gated).

The audit log is already the canonical record of every meaningful action, so it
doubles as the event source — no separate events table is needed. The stream
polls by the monotonic ``AuditLog.id`` (EA-06: keying on the timestamp dropped
sibling rows written in the same microsecond on reconnect), resumes from the
client's ``Last-Event-ID`` (or ``?since``) on reconnect, and emits keepalive
comments while idle.

Each poll uses a fresh short-lived Session: the request-scoped ``get_session``
generator must never be held open across a long-lived stream.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from ...config import get_settings
from ...db import get_engine
from ...models import AuditLog

router = APIRouter(tags=["events"])

_POLL_INTERVAL_SECONDS = 1.5
_BATCH_LIMIT = 100

SessionFactory = Callable[[], "contextmanager[Iterator[Session]]"]


@contextmanager
def _default_session_factory() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def fetch_events_since(session: Session, cursor: int | None) -> list[AuditLog]:
    stmt = select(AuditLog)
    if cursor is not None:
        stmt = stmt.where(AuditLog.id > cursor)
    stmt = stmt.order_by(AuditLog.id).limit(_BATCH_LIMIT)  # type: ignore[union-attr]
    return list(session.exec(stmt))


def format_sse_event(entry: AuditLog) -> str:
    payload = {
        "id": entry.id,
        "timestamp": entry.timestamp.isoformat(),
        "actor": entry.actor.value,
        "action": entry.action,
        "entity_type": entry.entity_type,
        "entity_id": entry.entity_id,
        "detail": entry.detail,
    }
    data = json.dumps(payload, default=str)
    # EA-06: the SSE id is the monotonic PK, not the timestamp — two rows written
    # in the same microsecond must each advance the cursor on reconnect.
    return f"id: {entry.id}\nevent: audit\ndata: {data}\n\n"


def _parse_cursor(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def audit_event_stream(
    since: int | None = None,
    *,
    session_factory: SessionFactory = _default_session_factory,
    poll_interval: float = _POLL_INTERVAL_SECONDS,
    max_polls: int | None = None,
) -> AsyncIterator[str]:
    """Yield SSE frames for new AuditLog rows, keepalives while idle.

    ``max_polls`` bounds the loop for tests; production leaves it ``None`` so the
    stream runs until the client disconnects.
    """
    cursor = since
    polls = 0
    while True:
        with session_factory() as session:
            events = fetch_events_since(session, cursor)
        if events:
            for entry in events:
                cursor = entry.id
                yield format_sse_event(entry)
        else:
            yield ": keepalive\n\n"
        polls += 1
        if max_polls is not None and polls >= max_polls:
            return
        await asyncio.sleep(poll_interval)


@router.get("/events/stream")
def events_stream(request: Request) -> StreamingResponse:
    if not get_settings().feature_sse:
        raise HTTPException(status_code=503, detail="event stream is disabled")
    since = _parse_cursor(
        request.headers.get("last-event-id") or request.query_params.get("since")
    )
    return StreamingResponse(
        audit_event_stream(since),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
