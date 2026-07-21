"""Debrief + email-draft generation (INT-03)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from zengrowth.api.main import app
from zengrowth.db import get_session
from zengrowth.ingestion.dedup import dedup_hash
from zengrowth.interviews.debrief import generate_debrief, generate_email_draft
from zengrowth.materials import generator
from zengrowth.models import Interview, InterviewStatus, Job


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


def _interview(session: Session, job: Job, **overrides) -> Interview:
    interview = Interview(job_id=job.id or 0, **overrides)
    session.add(interview)
    session.commit()
    session.refresh(interview)
    return interview


class FakeClient:
    def __init__(self, markdown: str = "## How it went\nSolid.", citations=None):  # noqa: ANN001
        self.markdown = markdown
        self.citations = citations or []
        self.prompts: list[str] = []
        self.allow_web_flags: list[bool] = []

    def generate_document(self, system, user, model, max_tokens, *, operation_name, allow_web=True):  # noqa: ANN001
        self.prompts.append(user)
        self.allow_web_flags.append(allow_web)
        return self.markdown, self.citations, allow_web


def test_debrief_requires_transcript_or_notes(session: Session):
    job = _job(session)
    interview = _interview(session, job)
    with pytest.raises(ValueError, match="transcript"):
        generate_debrief(session, job, interview, client=FakeClient())


def test_debrief_from_transcript(session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    interview = _interview(
        session,
        job,
        transcript="Interviewer: how would you scale GenAI? Me: ...",
        status=InterviewStatus.scheduled,
    )
    client = FakeClient()
    material = generate_debrief(session, job, interview, client=client)

    assert material.material_type == "debrief"
    assert material.audience == "internal"
    assert material.interview_id == interview.id
    document = Path(material.markdown_path).read_text(encoding="utf-8")
    assert document.startswith("---\n")
    assert "> [!warning]" in document
    assert "scale GenAI" in client.prompts[0]
    # Generating a debrief marks a scheduled round as completed.
    session.refresh(interview)
    assert interview.status == InterviewStatus.completed


def test_debrief_falls_back_to_notes(session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    interview = _interview(session, job, notes="Panel asked about MLOps governance.")
    client = FakeClient()
    generate_debrief(session, job, interview, client=client)
    assert "MLOps governance" in client.prompts[0]


def test_email_draft_requires_input(session: Session):
    job = _job(session)
    with pytest.raises(ValueError, match="nothing to draft"):
        generate_email_draft(session, job, client=FakeClient())


def test_email_draft_never_uses_web(session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    client = FakeClient(markdown="## Subject\nRe: Interview\n\n## Body\nThanks — Thursday works.")
    material = generate_email_draft(
        session,
        job,
        inbound_email="We'd like to invite you to an interview...",
        instructions="Reply accepting and propose Thursday",
        client=client,
    )
    assert client.allow_web_flags == [False]
    assert material.material_type == "email_draft"
    document = Path(material.markdown_path).read_text(encoding="utf-8")
    assert "nothing is sent by ZenGrowth" in document
    assert "Thursday works" in document


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


def test_debrief_endpoint_409_without_transcript(session: Session, client: TestClient):
    job = _job(session)
    interview = _interview(session, job)
    resp = client.post(f"/api/jobs/{job.id}/interviews/{interview.id}/debrief")
    assert resp.status_code == 409
    assert "transcript" in resp.json()["detail"]


def test_debrief_endpoint_generates(session: Session, client: TestClient, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    fake = FakeClient()
    monkeypatch.setattr("zengrowth.interviews.debrief._build_pack_client", lambda *a, **k: fake)
    job = _job(session)
    interview = _interview(session, job, transcript="Q&A about AI strategy")
    resp = client.post(f"/api/jobs/{job.id}/interviews/{interview.id}/debrief")
    assert resp.status_code == 201
    assert resp.json()["material_type"] == "debrief"


def test_email_draft_endpoint_validates_input(session: Session, client: TestClient):
    job = _job(session)
    resp = client.post(f"/api/jobs/{job.id}/materials/email-draft", json={})
    assert resp.status_code == 400


def test_email_draft_endpoint_generates(session: Session, client: TestClient, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    fake = FakeClient(markdown="## Subject\nFollow-up\n\n## Body\nThank you.")
    monkeypatch.setattr("zengrowth.interviews.debrief._build_pack_client", lambda *a, **k: fake)
    job = _job(session)
    resp = client.post(
        f"/api/jobs/{job.id}/materials/email-draft",
        json={"instructions": "Send a thank-you follow-up"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["material_type"] == "email_draft"
    assert data["audience"] == "internal"
