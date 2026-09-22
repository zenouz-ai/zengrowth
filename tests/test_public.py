"""Phase 4: the public observability surface is anonymous, aggregate-only, and
redacted. These tests assert no identifying data leaks and that k-anonymity and
the feature flag behave."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from zengrowth.api.main import create_app
from zengrowth.audit import log_action
from zengrowth.config import Settings, get_settings
from zengrowth.db import get_session
from zengrowth.models import ActorType, AuditLog, Job, JobSource, LifecycleState


def _seed_jobs(session: Session, n: int, *, state: LifecycleState, fit: float | None) -> None:
    for i in range(n):
        session.add(
            Job(
                company=f"SecretCorp{i}",
                title=f"Director of Things {i}",
                application_url=f"https://secret.example/{i}",
                source=JobSource.manual,
                dedup_hash=f"hash-{state.value}-{fit}-{i}",
                lifecycle_state=state,
                fit_score=fit,
            )
        )
    session.commit()


def _seed_state_changes(session: Session, n: int, *, timestamp: datetime) -> None:
    for i in range(n):
        session.add(
            AuditLog(
                timestamp=timestamp,
                actor=ActorType.human,
                action="change_state",
                entity_type="job",
                entity_id=str(i),
                detail={"from": "discovered", "to": "applied"},
            )
        )
    session.commit()


def _week_label(value: datetime) -> str:
    iso = value.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


@pytest.fixture()
def public_client(session: Session):
    def override_get_session() -> Iterator[Session]:
        yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    try:
        yield TestClient(app), session
    finally:
        app.dependency_overrides.clear()


def test_public_routes_are_anonymous_and_leak_no_identifiers(public_client):
    client, session = public_client
    _seed_jobs(session, 6, state=LifecycleState.applied, fit=85.0)

    for path in ("/api/public/summary", "/api/public/pipeline", "/api/public/scores"):
        resp = client.get(path)  # no auth cookie at all
        assert resp.status_code == 200, path
        body = resp.text
        assert "SecretCorp" not in body
        assert "Director of Things" not in body
        assert "secret.example" not in body

    summary = client.get("/api/public/summary").json()
    assert summary["total_jobs"] == 6
    assert summary["applied"] == 6
    assert summary["suppressed"] == 0


def test_pipeline_lists_every_state_in_enum_order(public_client):
    client, _ = public_client
    states = [b["state"] for b in client.get("/api/public/pipeline").json()["states"]]
    assert states == [s.value for s in LifecycleState]


def test_summary_suppresses_small_counts_and_reveals_counts_at_threshold(public_client):
    client, session = public_client
    _seed_jobs(session, 3, state=LifecycleState.interviewing, fit=70.0)
    _seed_jobs(session, 5, state=LifecycleState.applied, fit=80.0)

    body = client.get("/api/public/summary").json()
    assert body["total_jobs"] == 8
    assert body["applied"] == 5
    assert body["interviewing"] == 0
    assert body["offers"] == 0
    assert body["suppressed"] == 3


def test_summary_keeps_zero_counts_zero(public_client):
    client, _ = public_client

    body = client.get("/api/public/summary").json()
    assert body == {
        "total_jobs": 0,
        "applied": 0,
        "interviewing": 0,
        "offers": 0,
        "suppressed": 0,
    }


def test_pipeline_suppresses_small_state_counts_with_complement(public_client):
    # SEC-05: a lone small state (discovered=3) would be recoverable as
    # total - sum(revealed), so the smallest revealed cell (applied=5) is hidden
    # too. Both go to zero; suppressed counts all hidden records.
    client, session = public_client
    _seed_jobs(session, 3, state=LifecycleState.discovered, fit=90.0)
    _seed_jobs(session, 5, state=LifecycleState.applied, fit=50.0)

    body = client.get("/api/public/pipeline").json()
    states = {row["state"]: row["count"] for row in body["states"]}
    assert states["discovered"] == 0
    assert states["applied"] == 0  # complementary suppression
    assert states["offer"] == 0
    assert body["suppressed"] == 8


def test_pipeline_reveals_when_two_or_more_cells_are_large(public_client):
    # No small cell to hide -> nothing suppressed, real counts shown.
    client, session = public_client
    _seed_jobs(session, 6, state=LifecycleState.discovered, fit=90.0)
    _seed_jobs(session, 7, state=LifecycleState.applied, fit=50.0)

    body = client.get("/api/public/pipeline").json()
    states = {row["state"]: row["count"] for row in body["states"]}
    assert states["discovered"] == 6
    assert states["applied"] == 7
    assert body["suppressed"] == 0


def test_pipeline_no_single_state_recoverable_by_differencing(public_client):
    # The defense property: total (from summary) minus the revealed pipeline
    # states must never uniquely identify a hidden state's count.
    client, session = public_client
    _seed_jobs(session, 3, state=LifecycleState.interviewing, fit=70.0)
    _seed_jobs(session, 8, state=LifecycleState.applied, fit=60.0)

    total = client.get("/api/public/summary").json()["total_jobs"]
    states = {row["state"]: row["count"] for row in client.get("/api/public/pipeline").json()["states"]}
    revealed_sum = sum(states.values())
    # At least two cells hidden, so the margin leaves >= 2 unknowns (not solvable).
    hidden_states = [s for s, c in states.items() if c == 0]
    assert total - revealed_sum >= 5  # the hidden mass, not a single cell
    assert len([s for s in hidden_states if s in ("interviewing", "applied")]) == 2


def test_scores_suppress_small_buckets(public_client):
    client, session = public_client
    # 3 jobs in the 80-100 bucket -> below k=5 -> suppressed to 0.
    _seed_jobs(session, 3, state=LifecycleState.discovered, fit=90.0)
    # 5 jobs in the 40-60 bucket -> at threshold -> revealed.
    _seed_jobs(session, 5, state=LifecycleState.discovered, fit=50.0)

    body = client.get("/api/public/scores").json()
    buckets = {b["label"]: b["count"] for b in body["buckets"]}
    assert buckets["80-100"] == 0
    # SEC-05: lone small bucket triggers complementary suppression of 40-60 too.
    assert buckets["40-60"] == 0
    assert body["suppressed"] == 8


def test_velocity_counts_state_changes_only(public_client):
    client, session = public_client
    job = Job(company="X", title="Y", source=JobSource.manual, dedup_hash="vh")
    session.add(job)
    session.commit()
    log_action(
        session,
        actor=ActorType.human,
        action="change_state",
        entity_type="job",
        entity_id=job.id,
        detail={"from": "discovered", "to": "applied"},
    )
    log_action(session, actor=ActorType.human, action="create_job", entity_type="job",
               entity_id=job.id)

    body = client.get("/api/public/velocity").json()
    points = body["points"]
    assert len(points) == 12
    assert sum(p["transitions"] for p in points) == 0  # one transition is suppressed
    assert body["suppressed"] == 1


def test_velocity_suppresses_small_weeks_and_reveals_counts_at_threshold(public_client):
    client, session = public_client
    now = datetime.now(UTC)
    last_week = now - timedelta(weeks=1)
    _seed_state_changes(session, 3, timestamp=last_week)
    _seed_state_changes(session, 5, timestamp=now)

    body = client.get("/api/public/velocity").json()
    points = {point["week"]: point["transitions"] for point in body["points"]}
    assert points[_week_label(last_week)] == 0
    # SEC-05: lone small week triggers complementary suppression of the busy week.
    assert points[_week_label(now)] == 0
    assert body["suppressed"] == 8


def test_public_surface_returns_503_when_disabled(monkeypatch, session: Session):
    def override_get_session() -> Iterator[Session]:
        yield session

    monkeypatch.setattr(
        "zengrowth.api.routers.public.get_settings",
        lambda: Settings(_env_file=None, feature_public_observability=False),
    )
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(app)
        assert client.get("/api/public/summary").status_code == 503
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
