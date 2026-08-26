"""Voice-interviewer simulation prompt (INT-05) — deterministic, no LLM."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from zengrowth.api.main import app
from zengrowth.db import get_session
from zengrowth.ingestion.dedup import dedup_hash
from zengrowth.interviews.sim_prompt import build_sim_prompt, generate_sim_prompt
from zengrowth.materials import generator
from zengrowth.models import Interview, InterviewRoundType, Job


def _job(session: Session) -> Job:
    job = Job(
        company="Intact",
        title="Director of AI",
        source="manual",
        dedup_hash=dedup_hash("Intact", "Director of AI", None),
        job_summary={"role_overview": "Lead AI strategy for a global insurer."},
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def test_build_sim_prompt_round_specific():
    job = Job(company="Intact", title="Director of AI", source="manual", dedup_hash="x")
    interview = Interview(
        job_id=1,
        round_type=InterviewRoundType.technical,
        participants=[{"name": "Alex CTO", "role": "CTO"}],
    )
    prompt = build_sim_prompt(
        job, interview=interview, evidence_topics=["Led a 12-person AI team."]
    )
    assert "technical deep-dive" in prompt
    assert "Alex CTO (CTO)" in prompt
    assert "Led a 12-person AI team." in prompt
    assert "score the" in prompt  # coaching rubric present
    assert "ChatGPT Voice" in prompt  # model-agnostic usage note


def test_build_sim_prompt_without_round_or_evidence():
    job = Job(company="Intact", title="Director of AI", source="manual", dedup_hash="x")
    prompt = build_sim_prompt(job)
    assert "general interview" in prompt
    assert "invent one realistic interviewer" in prompt


def test_generate_sim_prompt_records_material(session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    monkeypatch.setattr(generator, "SOURCE_OF_TRUTH", tmp_path / "missing.md")
    job = _job(session)
    interview = Interview(job_id=job.id or 0, round_type=InterviewRoundType.final_round)
    session.add(interview)
    session.commit()
    session.refresh(interview)

    material = generate_sim_prompt(session, job, interview=interview)
    assert material.material_type == "interviewer_sim_prompt"
    assert material.audience == "internal"
    assert material.interview_id == interview.id
    document = Path(material.markdown_path).read_text(encoding="utf-8")
    assert "final executive round" in document


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


def test_sim_prompt_endpoint(session: Session, client: TestClient, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    monkeypatch.setattr(generator, "SOURCE_OF_TRUTH", tmp_path / "missing.md")
    job = _job(session)
    resp = client.post(f"/api/jobs/{job.id}/materials/sim-prompt", json={})
    assert resp.status_code == 201
    assert resp.json()["material_type"] == "interviewer_sim_prompt"
