"""Learning loop (INT-04): promote-to-review-queue, cross-job reuse, round analytics."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from zengrowth.api.main import app
from zengrowth.config import Settings, get_settings
from zengrowth.db import get_session
from zengrowth.ingestion.dedup import dedup_hash
from zengrowth.interviews.service import (
    load_cross_job_learnings,
    promote_learning,
)
from zengrowth.models import (
    ClaimVerificationState,
    Interview,
    Job,
)


@pytest.fixture(autouse=True)
def _knowledge_root(tmp_path: Path, monkeypatch):
    """Point the knowledge store at a temp dir so learning files stay isolated."""
    get_settings.cache_clear() if hasattr(get_settings, "cache_clear") else None
    monkeypatch.setattr(
        "zengrowth.knowledge.service.get_settings",
        lambda: Settings(knowledge_root=str(tmp_path / "knowledge")),
    )
    yield


def _job(session: Session, company: str = "Intact") -> Job:
    job = Job(
        company=company,
        title="Director of AI",
        source="manual",
        dedup_hash=dedup_hash(company, "Director of AI", None),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _interview(session: Session, job: Job) -> Interview:
    interview = Interview(job_id=job.id or 0)
    session.add(interview)
    session.commit()
    session.refresh(interview)
    return interview


def test_promote_learning_creates_draft_claim(session: Session):
    job = _job(session)
    interview = _interview(session, job)
    claim, created = promote_learning(
        session,
        job,
        claim_text="Prepare a crisper answer on GenAI governance ROI.",
        interview=interview,
    )
    assert created is True
    # Never auto-verified: interview content reaches the evidence bank only
    # through the Approve facts queue.
    assert claim.verification_state == ClaimVerificationState.draft
    assert claim.category == "interview_learning"
    assert "interview_learning" in (claim.tags or [])
    # The backing learnings file records the promotion.
    from zengrowth.models import SourceDocument

    document = session.get(SourceDocument, claim.source_document_id)
    assert document is not None
    assert "GenAI governance ROI" in Path(document.original_path).read_text(encoding="utf-8")


def test_promote_learning_idempotent(session: Session):
    job = _job(session)
    first, created_first = promote_learning(session, job, claim_text="Same learning.")
    second, created_second = promote_learning(session, job, claim_text="Same learning.")
    assert created_first is True
    assert created_second is False
    assert first.id == second.id


def test_promote_learning_rejects_empty(session: Session):
    job = _job(session)
    with pytest.raises(ValueError, match="empty"):
        promote_learning(session, job, claim_text="   ")


def test_cross_job_learnings_only_verified_and_other_jobs(session: Session):
    intact = _job(session, "Intact")
    iwoca = _job(session, "Iwoca")
    draft_claim, _ = promote_learning(session, iwoca, claim_text="Draft learning stays out.")
    verified_claim, _ = promote_learning(session, iwoca, claim_text="Lead with platform ROI story.")
    verified_claim.verification_state = ClaimVerificationState.verified
    session.add(verified_claim)
    own_claim, _ = promote_learning(session, intact, claim_text="Intact-specific learning.")
    own_claim.verification_state = ClaimVerificationState.verified
    session.add(own_claim)
    session.commit()

    learnings = load_cross_job_learnings(session, exclude_job_id=intact.id)
    assert "Lead with platform ROI story." in learnings
    assert "Draft learning stays out." not in learnings
    assert "Intact-specific learning." not in learnings


# --- API ------------------------------------------------------------------------


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    def override_get_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        app.dependency_overrides.clear()


def test_promote_learning_endpoint(session: Session, client: TestClient):
    job = _job(session)
    interview = _interview(session, job)
    resp = client.post(
        f"/api/jobs/{job.id}/interviews/{interview.id}/promote-learning",
        json={"claim_text": "Bring a sharper 90-day plan."},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["verification_state"] == "draft"
    assert data["category"] == "interview_learning"
    # It shows up in the Approve facts queue.
    queue = client.get("/api/knowledge/claims", params={"state": "draft"}).json()
    assert any(c["id"] == data["id"] for c in queue)


def test_funnel_reports_round_analytics(session: Session, client: TestClient):
    job = _job(session)
    client.post(f"/api/jobs/{job.id}/outcome", json={"outcome_stage": "applied"})
    client.post(
        f"/api/jobs/{job.id}/interviews",
        json={"round_type": "recruiter_screen", "occurred_at": "2026-05-16T10:00:00Z"},
    )
    client.post(
        f"/api/jobs/{job.id}/interviews",
        json={"round_type": "technical", "occurred_at": "2026-06-15T10:00:00Z"},
    )
    funnel = client.get("/api/jobs/outcomes/funnel").json()
    assert funnel["rounds_recorded"] == 2
    assert funnel["avg_days_between_rounds"] == 30.0
