"""SEC-01/SEC-09: ingestion readiness, staleness detection, and the heartbeat.

A silently-stopped nightly ingest is the highest-blast-radius failure (an empty
board reads as "no new roles"). These tests pin the signals that make it loud:
staleness derived from the scheduler lock, zero-row/failed boards surfaced from
the last run, the readiness probe's 503, and the dead-man's-switch ping.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from zengrowth.api.main import create_app
from zengrowth.config import Settings
from zengrowth.db import get_session
from zengrowth.ingestion import runner as runner_mod
from zengrowth.ingestion.health import ingestion_health, send_ingest_heartbeat
from zengrowth.ingestion.runner import INGEST_LOCK_NAME, IngestionResult, _run_all_body
from zengrowth.models import PipelineRun, PipelineRunStatus, SchedulerLock


def _set_last_completed(session: Session, when: datetime | None) -> None:
    row = session.get(SchedulerLock, INGEST_LOCK_NAME) or SchedulerLock(name=INGEST_LOCK_NAME)
    row.last_completed_at = when
    session.add(row)
    session.commit()


def _add_ingestion_run(session: Session, **result: object) -> None:
    session.add(
        PipelineRun(
            trace_id=f"trace-{datetime.now(UTC).timestamp()}",
            pipeline_type="ingestion",
            started_at=datetime.now(UTC),
            status=PipelineRunStatus.completed,
            detail={"result": result},
        )
    )
    session.commit()


# --- ingestion_health -------------------------------------------------------


def test_health_reports_never_run_with_no_lock(session: Session) -> None:
    health = ingestion_health(session, Settings(_env_file=None))
    assert health.never_run is True
    assert health.stale is False
    assert health.degraded is False


def test_health_flags_stale_when_last_run_is_old(session: Session) -> None:
    _set_last_completed(session, datetime.now(UTC) - timedelta(hours=48))
    health = ingestion_health(session, Settings(_env_file=None, ingestion_stale_after_hours=26))
    assert health.never_run is False
    assert health.stale is True
    assert health.degraded is True
    assert health.age_seconds is not None and health.age_seconds > 26 * 3600


def test_health_fresh_run_is_not_stale(session: Session) -> None:
    _set_last_completed(session, datetime.now(UTC) - timedelta(hours=2))
    health = ingestion_health(session, Settings(_env_file=None, ingestion_stale_after_hours=26))
    assert health.stale is False
    assert health.degraded is False


def test_health_surfaces_zero_row_and_failed_boards(session: Session) -> None:
    _set_last_completed(session, datetime.now(UTC) - timedelta(hours=1))
    _add_ingestion_run(
        session, added=0, zero_row_boards=["greenhouse:acme"], failed_boards=["lever:x"]
    )
    health = ingestion_health(session, Settings(_env_file=None))
    assert health.zero_row_boards == ["greenhouse:acme"]
    assert health.failed_boards == ["lever:x"]
    # Fresh, but a board went silent -> the operator should still look.
    assert health.degraded is True


def test_health_uses_most_recent_ingestion_run(session: Session) -> None:
    _set_last_completed(session, datetime.now(UTC) - timedelta(hours=1))
    _add_ingestion_run(session, added=3, zero_row_boards=["old:board"])
    _add_ingestion_run(session, added=7, zero_row_boards=[])
    health = ingestion_health(session, Settings(_env_file=None))
    assert health.added == 7
    assert health.zero_row_boards == []


# --- runner: zero-row tracking + run annotation -----------------------------


def test_runner_flags_board_that_parses_zero_rows(session: Session, monkeypatch) -> None:
    monkeypatch.setattr(runner_mod, "fetch_greenhouse", lambda slug, client=None: [])
    settings = Settings(
        _env_file=None, ats_boards=["greenhouse:acme"], ingestion_precheck_on_run=False
    )
    result = IngestionResult()
    _run_all_body(session, settings, result)
    assert result.zero_row_boards == ["greenhouse:acme"]
    assert result.succeeded_boards == ["greenhouse:acme"]
    # The outcome is stamped onto the run row for readiness to read back.
    health = ingestion_health(session, settings)
    assert health.zero_row_boards == ["greenhouse:acme"]


# --- heartbeat --------------------------------------------------------------


def test_heartbeat_is_noop_without_url(monkeypatch) -> None:
    called = False

    def _fail(*a, **k):  # pragma: no cover - must never be reached
        nonlocal called
        called = True

    monkeypatch.setattr("zengrowth.ingestion.health.httpx.get", _fail)
    send_ingest_heartbeat(Settings(_env_file=None), IngestionResult())
    assert called is False


def test_heartbeat_pings_when_configured(monkeypatch) -> None:
    pinged: list[str] = []
    monkeypatch.setattr(
        "zengrowth.ingestion.health.httpx.get",
        lambda url, timeout=None: pinged.append(url),
    )
    send_ingest_heartbeat(
        Settings(_env_file=None, ingest_heartbeat_url="https://hc.example/ping"),
        IngestionResult(),
    )
    assert pinged == ["https://hc.example/ping"]


def test_heartbeat_swallows_network_errors(monkeypatch) -> None:
    def _boom(url, timeout=None):
        raise RuntimeError("network down")

    monkeypatch.setattr("zengrowth.ingestion.health.httpx.get", _boom)
    # Must not raise — a failed beat is the monitor's problem, not ingestion's.
    send_ingest_heartbeat(
        Settings(_env_file=None, ingest_heartbeat_url="https://hc.example/ping"),
        IngestionResult(),
    )


# --- endpoints --------------------------------------------------------------


@pytest.fixture()
def health_client(session: Session):
    def override_get_session() -> Iterator[Session]:
        yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    try:
        yield TestClient(app), session
    finally:
        app.dependency_overrides.clear()


def test_health_ready_ok_when_fresh(health_client) -> None:
    client, session = health_client
    _set_last_completed(session, datetime.now(UTC) - timedelta(hours=1))
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db_writable"] is True
    assert body["ingest_stale"] is False


def test_health_ready_503_when_stale(health_client) -> None:
    client, session = health_client
    _set_last_completed(session, datetime.now(UTC) - timedelta(hours=72))
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["ingest_stale"] is True


def test_health_ready_never_run_is_ok(health_client) -> None:
    client, _ = health_client
    resp = client.get("/health/ready")
    # A fresh install hasn't run yet — that's not a failure, just "never run".
    assert resp.status_code == 200
    assert resp.json()["ingest_never_run"] is True


def test_ingestion_health_endpoint_returns_board_detail(health_client) -> None:
    client, session = health_client
    _set_last_completed(session, datetime.now(UTC) - timedelta(hours=1))
    _add_ingestion_run(session, added=2, zero_row_boards=["greenhouse:acme"], failed_boards=[])
    body = client.get("/api/ingestion/health").json()
    assert body["zero_row_boards"] == ["greenhouse:acme"]
    assert body["degraded"] is True
    assert body["added"] == 2
