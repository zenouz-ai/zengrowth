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
    import_internal_material,
    list_closeout_learning_candidates,
    load_cross_job_learnings,
    promote_closeout_learnings,
    promote_learning,
)
from zengrowth.materials import generator
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


_CLOSEOUT_MD = """## Process Summary
Three rounds then a no.

## Gaps Versus The Bar
- Credit-risk modelling depth was thinner than the bar for this seat.

## Skills And Knowledge To Deepen
- Practiced calibrated credit-risk modelling with gradient boosting on imbalanced labels.

## Evidence To Add To Library
- Write a Library note on the underwriting feature pipeline and monitoring.

## Posture For The Next Similar Role
- Lead with a 90-day credit-risk discovery plan instead of a generic platform story.
"""


def test_promote_closeout_learnings_creates_drafts(
    session: Session, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session, "Acme")
    import_internal_material(
        session,
        job,
        material_type="rejection_reflection",
        title="Rejection reflection",
        content=_CLOSEOUT_MD,
    )
    claims, promoted, skipped = promote_closeout_learnings(
        session,
        job,
        claim_texts=[
            "Practiced calibrated credit-risk modelling with gradient boosting on imbalanced labels.",
            "Lead with a 90-day credit-risk discovery plan instead of a generic platform story.",
        ],
    )
    assert skipped == 0
    assert promoted == 2
    assert all(c.verification_state == ClaimVerificationState.draft for c in claims)
    assert {c.category for c in claims} == {"interview_learning", "process_skill"}
    skill = next(c for c in claims if c.category == "process_skill")
    assert "gradient boosting" in skill.claim_text
    assert not any("thinner than the bar" in c.claim_text.lower() for c in claims)
    assert not any("library note" in c.claim_text.lower() for c in claims)

    _, promoted_again, skipped_again = promote_closeout_learnings(
        session,
        job,
        claim_texts=[
            "Practiced calibrated credit-risk modelling with gradient boosting on imbalanced labels.",
        ],
    )
    assert promoted_again == 0
    assert skipped_again == 1


def test_list_closeout_candidates_merges_docs_and_skips_gaps(
    session: Session, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session, "Acme")
    import_internal_material(
        session,
        job,
        material_type="rejection_reflection",
        title="Custom essay",
        content=(
            "## Part 3: The Three Gaps, Rebuilt Properly\n"
            "- Credit-risk modelling depth was thinner than the bar for this seat.\n\n"
            "## Part 5: The Durable Playbook For Next Senior Interview\n"
            "- End Head-of answers with I decided X because Y, then the consequence I owned.\n"
        ),
    )
    import_internal_material(
        session,
        job,
        material_type="journey_summary",
        title="Journey summary",
        content=(
            "## What Needs To Improve\n"
            "- Tighten the recovery script for timed modelling exercises under pressure.\n\n"
            "## Reusable Learnings\n"
            "- Process: Confirm the live-coding environment the day before the round.\n"
        ),
    )
    import_internal_material(
        session,
        job,
        material_type="rejection_reflection",
        title="Generated reflection",
        content=_CLOSEOUT_MD,
    )
    texts = [text for _cat, text, _src in list_closeout_learning_candidates(session, job)]
    joined = " ".join(texts).lower()
    assert "gradient boosting" in joined
    assert "i decided x because y" in joined
    assert "live-coding environment" in joined
    assert "thinner than the bar" not in joined
    assert "recovery script" not in joined


def test_promote_closeout_learnings_endpoint(
    session: Session, client: TestClient, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session, "Acme")
    import_internal_material(
        session,
        job,
        material_type="rejection_reflection",
        title="Rejection reflection",
        content=_CLOSEOUT_MD,
    )
    preview = client.get(f"/api/jobs/{job.id}/closeout-learnings")
    assert preview.status_code == 200
    candidates = preview.json()["candidates"]
    texts = [c["claim_text"] for c in candidates]
    assert any("gradient boosting" in t for t in texts)
    assert not any("thinner than the bar" in t.lower() for t in texts)
    skill = next(c for c in candidates if "gradient boosting" in c["claim_text"])
    resp = client.post(
        f"/api/jobs/{job.id}/promote-closeout-learnings",
        json={"claim_texts": [skill["claim_text"]]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["promoted"] == 1
    assert data["skipped_existing"] == 0
    queue = client.get("/api/knowledge/claims", params={"state": "draft"}).json()
    assert any("gradient boosting" in c["claim_text"] for c in queue)


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
