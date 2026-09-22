"""Outcome tracking + funnel endpoints (TA-01)."""

from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlmodel import Session

from zengrowth.api.main import app
from zengrowth.db import get_session
from zengrowth.models import Job


def _client(session: Session) -> TestClient:
    def override_get_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)


def _job(session: Session, dedup_hash: str) -> Job:
    job = Job(company="Acme", title="Director of AI", source="manual", dedup_hash=dedup_hash)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def test_record_outcome_updates_fields_and_syncs_lifecycle(session: Session):
    job = _job(session, "o1")
    client = _client(session)
    try:
        resp = client.post(f"/api/jobs/{job.id}/outcome", json={"outcome_stage": "interview"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["outcome_stage"] == "interview"
        assert data["applied_at"] is not None  # backfilled from recording a stage
        assert data["outcome_updated_at"] is not None
        assert data["lifecycle_state"] == "interviewing"
    finally:
        app.dependency_overrides.clear()


def test_record_outcome_rejection_sets_rejected_state(session: Session):
    job = _job(session, "o2")
    client = _client(session)
    try:
        resp = client.post(
            f"/api/jobs/{job.id}/outcome",
            json={"outcome_result": "rejected", "rejection_stage": "recruiter_screen", "notes": "No fit."},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["outcome_result"] == "rejected"
        assert data["rejection_stage"] == "recruiter_screen"
        assert data["outcome_notes"] == "No fit."
        assert data["lifecycle_state"] == "rejected"
    finally:
        app.dependency_overrides.clear()


def test_record_outcome_can_skip_lifecycle_sync(session: Session):
    job = _job(session, "o3")
    client = _client(session)
    try:
        resp = client.post(
            f"/api/jobs/{job.id}/outcome",
            json={"outcome_stage": "interview", "sync_lifecycle": False},
        )
        assert resp.status_code == 200
        assert resp.json()["lifecycle_state"] == "discovered"
    finally:
        app.dependency_overrides.clear()


def test_record_outcome_unknown_job_404(session: Session):
    client = _client(session)
    try:
        assert client.post("/api/jobs/999/outcome", json={"outcome_stage": "applied"}).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_outcome_funnel_aggregates(session: Session):
    applied = _job(session, "f1")
    interviewed = _job(session, "f2")
    offered = _job(session, "f3")
    _job(session, "f4")  # never applied -> excluded from the funnel
    client = _client(session)
    try:
        client.post(f"/api/jobs/{applied.id}/outcome", json={"outcome_stage": "applied"})
        client.post(f"/api/jobs/{interviewed.id}/outcome", json={"outcome_stage": "interview"})
        client.post(
            f"/api/jobs/{offered.id}/outcome",
            json={"outcome_stage": "offer", "outcome_result": "offer"},
        )
        funnel = client.get("/api/jobs/outcomes/funnel").json()
        assert funnel["total_applied"] == 3
        assert funnel["responded"] == 2  # interview + offer reached past "applied"
        assert funnel["interviewed"] == 2
        assert funnel["offers"] == 1
        assert funnel["response_rate"] == round(2 / 3, 3)
    finally:
        app.dependency_overrides.clear()
