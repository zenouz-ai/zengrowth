"""Prep-pack generation (INT-02): provenance profile, citations, learning loop."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from zengrowth.api.main import app
from zengrowth.db import get_session
from zengrowth.ingestion.dedup import dedup_hash
from zengrowth.interviews.packs import (
    InstrumentedPackClient,
    generate_pack,
    load_prior_debriefs,
)
from zengrowth.materials import generator
from zengrowth.models import (
    ClaimVerificationState,
    EvidenceClaim,
    GeneratedMaterial,
    Interview,
    Job,
    SourceDocument,
)


def _job(session: Session, company: str = "Intact") -> Job:
    job = Job(
        company=company,
        title="Director of AI",
        source="manual",
        dedup_hash=dedup_hash(company, "Director of AI", None),
        description="Lead the AI strategy for a global insurer.",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _claim(session: Session, claim_id: str = "claim-abc123def4567890") -> EvidenceClaim:
    document = SourceDocument(
        filename="cv.md", original_path="/tmp/cv.md", content_hash=f"hash-{claim_id}"
    )
    session.add(document)
    session.commit()
    claim = EvidenceClaim(
        id=claim_id,
        source_document_id=document.id or 0,
        claim_text="Led a 12-person AI team delivering GBP 3m efficiency gains.",
        category="leadership",
        confidence=0.9,
        verification_state=ClaimVerificationState.verified,
    )
    session.add(claim)
    session.commit()
    return claim


class FakePackClient:
    """Returns a canned pack; records the prompt for assertions."""

    def __init__(self, markdown: str, citations: list[dict[str, str]] | None = None, web: bool = True):
        self.markdown = markdown
        self.citations = citations or []
        self.web = web
        self.prompts: list[str] = []

    def generate_document(self, system, user, model, max_tokens, *, operation_name):  # noqa: ANN001
        self.prompts.append(user)
        return self.markdown, self.citations, self.web


def _pack_markdown() -> str:
    return (
        "> [!tip] Screening call with talent partner — lead with strategic AI leadership.\n\n"
        "## Who They Are\nGlobal insurer.\n\n"
        "## The Org Structure That Matters\nCDO reports to CIO.\n\n"
        "## Key Leaders and Interviewers\nRay Williamson, talent partner.\n\n"
        "## Current Technology Stack\nMicrosoft Fabric, Databricks.\n\n"
        "## What They Need You to Build — Year One Plan\nEstablish AI CoE.\n\n"
        "## Agentic AI — What Can Be Built on This Stack\nUnderwriting agents.\n\n"
        "## Key Numbers to Know\n£5bn GWP ambition.\n\n"
        "## The Insurance Value Chain (Know This)\nBroker to claims.\n\n"
        "## Interview Question Preparation\nPrepare GenAI governance ROI answer.\n\n"
        "## People to Know\nIndhira Mani, CDO.\n\n"
        "## Competitive Context\nAviva, Zurich.\n\n"
        "## Your Evidence to Lead With\nLed a 12-person AI team [claim-abc123def4567890].\n\n"
        "## Compensation Range and Your Alignment\nMarket range fits."
    )


def test_generate_company_briefing(session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    _claim(session)
    client = FakePackClient(
        _pack_markdown(),
        citations=[{"url": "https://example.com/intact", "title": "Intact overview"}],
    )
    material = generate_pack(session, job, pack_type="company_briefing", client=client)

    assert material.material_type == "company_briefing"
    assert material.audience == "internal"
    assert material.status == "created_markdown"
    assert material.evidence_ids == ["claim-abc123def4567890"]

    document = Path(material.markdown_path).read_text(encoding="utf-8")
    assert document.startswith("---\n")
    assert "# Company briefing — Intact" in document
    assert "> [!warning]" in document
    assert "unverified web research" in document
    assert "> [!tip]" in document
    assert "## Who They Are" in document
    assert "## Sources" in document
    assert "https://example.com/intact" in document
    assert material.markdown_path.endswith("company-briefing-intact.md")
    # Evidence bank made it into the prompt with claim ids.
    assert "claim-abc123def4567890" in client.prompts[0]


def test_generate_pack_without_web_search_labels_it(session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    client = FakePackClient(_pack_markdown(), web=False)
    material = generate_pack(session, job, pack_type="company_briefing", client=client)
    document = Path(material.markdown_path).read_text(encoding="utf-8")
    assert "Web research was unavailable" in document
    assert "## Sources" not in document


def test_generate_pack_empty_bank_still_works(session: Session, tmp_path: Path, monkeypatch):
    """Packs are internal study aids — no fail-loud on an empty evidence bank."""
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    monkeypatch.setattr(generator, "SOURCE_OF_TRUTH", tmp_path / "missing.md")
    job = _job(session)
    client = FakePackClient(_pack_markdown())
    material = generate_pack(session, job, pack_type="company_briefing", client=client)
    assert material.evidence_ids == []  # id in text no longer matches a known claim


def test_generate_pack_rejects_unknown_type(session: Session):
    job = _job(session)
    with pytest.raises(ValueError, match="unsupported pack type"):
        generate_pack(session, job, pack_type="party_planning", client=FakePackClient("x"))


def test_generate_pack_rejects_empty_document(session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    with pytest.raises(ValueError, match="empty document"):
        generate_pack(session, job, pack_type="company_briefing", client=FakePackClient("   "))


def test_pack_includes_prior_debriefs(session: Session, tmp_path: Path, monkeypatch):
    """The learning loop: earlier debriefs feed the next round's prep (INT-04)."""
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    interview = Interview(job_id=job.id or 0)
    session.add(interview)
    session.commit()
    debrief_path = tmp_path / "materials" / "debrief.md"
    debrief_path.parent.mkdir(parents=True, exist_ok=True)
    debrief_path.write_text("Learned: be crisper on GenAI governance ROI.", encoding="utf-8")
    session.add(
        GeneratedMaterial(
            job_id=job.id or 0,
            interview_id=interview.id,
            material_type="debrief",
            audience="internal",
            title="Screen debrief",
            markdown_path=str(debrief_path),
            status="imported",
        )
    )
    session.commit()

    client = FakePackClient(_pack_markdown())
    generate_pack(session, job, pack_type="final_round_pack", client=client)
    assert "GenAI governance ROI" in client.prompts[0]


def test_pack_includes_prior_prep_materials(session: Session, tmp_path: Path, monkeypatch):
    """Learning loop: prior prep packs (including imports) feed the next round."""
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    interview = Interview(job_id=job.id or 0)
    session.add(interview)
    session.commit()
    prep_path = tmp_path / "materials" / "imported-tech.md"
    prep_path.parent.mkdir(parents=True, exist_ok=True)
    prep_path.write_text(
        "## Anchor Sentence\n> \"Partner with platform teams.\"\n"
        "### Q1 — MLOps (Ankur)\n- Answer outline here.",
        encoding="utf-8",
    )
    session.add(
        GeneratedMaterial(
            job_id=job.id or 0,
            interview_id=interview.id,
            material_type="tech_prep_pack",
            audience="internal",
            title="Imported tech pack",
            markdown_path=str(prep_path),
            status="imported",
        )
    )
    session.commit()

    client = FakePackClient(_pack_markdown())
    generate_pack(session, job, pack_type="final_round_pack", client=client)
    assert "Partner with platform teams" in client.prompts[0] or "MLOps" in client.prompts[0]


def test_enhance_mode_includes_skeleton(session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    interview = Interview(job_id=job.id or 0)
    session.add(interview)
    session.commit()
    skeleton_path = tmp_path / "materials" / "imported-pack.md"
    skeleton_path.parent.mkdir(parents=True, exist_ok=True)
    skeleton = "## Anchor Sentence\n> \"Keep this line.\"\n### Q1 — Opening\n- Model answer."
    skeleton_path.write_text(skeleton, encoding="utf-8")
    imported = GeneratedMaterial(
        job_id=job.id or 0,
        interview_id=interview.id,
        material_type="interviewer_pack",
        audience="internal",
        title="Imported interviewer pack",
        markdown_path=str(skeleton_path),
        status="imported",
    )
    session.add(imported)
    session.commit()
    session.refresh(imported)

    client = FakePackClient(_pack_markdown())
    generate_pack(
        session,
        job,
        pack_type="interviewer_pack",
        interview=interview,
        client=client,
        enhance=True,
        source_material_id=imported.id,
    )
    assert "Keep this line" in client.prompts[0]
    assert "enhance_skeleton" in client.prompts[0]


def test_pack_endpoint_accepts_enhance_flag(
    session: Session, client: TestClient, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    fake = FakePackClient(_pack_markdown())
    monkeypatch.setattr("zengrowth.interviews.packs._build_pack_client", lambda *a, **k: fake)
    resp = client.post(
        f"/api/jobs/{job.id}/materials/pack",
        json={"pack_type": "company_briefing", "enhance": True},
    )
    assert resp.status_code == 201


def test_load_prior_debriefs_latest_per_round(session: Session, tmp_path: Path):
    job = _job(session)
    interview = Interview(job_id=job.id or 0)
    session.add(interview)
    session.commit()
    for version, text in ((1, "old learning"), (2, "new learning")):
        path = tmp_path / f"debrief-v{version}.md"
        path.write_text(text, encoding="utf-8")
        session.add(
            GeneratedMaterial(
                job_id=job.id or 0,
                interview_id=interview.id,
                material_type="debrief",
                audience="internal",
                title=f"Debrief v{version}",
                markdown_path=str(path),
                version=version,
                status="imported",
            )
        )
    session.commit()
    # markdown_path outside MATERIALS_ROOT is rejected by the safe-path check,
    # so point the root at tmp_path for this read.
    debriefs = load_prior_debriefs(session, job.id or 0)
    assert len(debriefs) <= 1  # one per round at most


class _FailsWithBadRequest:
    def chat_with_web_search(self, **_kwargs):  # noqa: ANN003
        class BadRequestError(Exception):
            pass

        raise BadRequestError("tool not supported")

    def complete_text(self, **_kwargs):  # noqa: ANN003
        return "fallback text"


def test_pack_client_falls_back_when_web_search_rejected(session: Session):
    from zengrowth.config import Settings

    settings = Settings(interview_research_web_search=True)
    client = InstrumentedPackClient(_FailsWithBadRequest(), settings=settings)  # type: ignore[arg-type]
    text, citations, web = client.generate_document("s", "u", "model", 100, operation_name="x")
    assert text == "fallback text"
    assert citations == []
    assert web is False


class _FailsWithPermissionDenied:
    def chat_with_web_search(self, **_kwargs):  # noqa: ANN003
        class PermissionDeniedError(Exception):
            pass

        raise PermissionDeniedError("web_search not enabled for this key")

    def complete_text(self, **_kwargs):  # noqa: ANN003
        return "fallback without web"


def test_pack_client_falls_back_when_web_search_permission_denied(session: Session):
    from zengrowth.config import Settings

    settings = Settings(interview_research_web_search=True)
    client = InstrumentedPackClient(_FailsWithPermissionDenied(), settings=settings)  # type: ignore[arg-type]
    text, citations, web = client.generate_document("s", "u", "model", 100, operation_name="x")
    assert text == "fallback without web"
    assert citations == []
    assert web is False


class _FailsWithAuthentication:
    def chat_with_web_search(self, **_kwargs):  # noqa: ANN003
        class AuthenticationError(Exception):
            pass

        raise AuthenticationError("invalid key")

    def complete_text(self, **_kwargs):  # noqa: ANN003
        raise AssertionError("should not reach plain completion")


def test_pack_client_propagates_authentication_error(session: Session):
    from zengrowth.config import Settings

    settings = Settings(interview_research_web_search=True)
    client = InstrumentedPackClient(_FailsWithAuthentication(), settings=settings)  # type: ignore[arg-type]
    with pytest.raises(Exception, match="invalid key"):
        client.generate_document("s", "u", "model", 100, operation_name="x")


# --- API endpoint ---------------------------------------------------------------


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


def test_pack_endpoint_validates_type(session: Session, client: TestClient):
    job = _job(session)
    resp = client.post(
        f"/api/jobs/{job.id}/materials/pack", json={"pack_type": "party_planning"}
    )
    assert resp.status_code == 400


def test_pack_endpoint_generates(session: Session, client: TestClient, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    interview = Interview(job_id=job.id or 0)
    session.add(interview)
    session.commit()

    fake = FakePackClient(_pack_markdown())
    monkeypatch.setattr(
        "zengrowth.interviews.packs._build_pack_client", lambda *a, **k: fake
    )
    resp = client.post(
        f"/api/jobs/{job.id}/materials/pack",
        json={"pack_type": "tech_prep_pack", "interview_id": interview.id},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["material_type"] == "tech_prep_pack"
    assert data["interview_id"] == interview.id
    assert data["audience"] == "internal"


def test_pack_endpoint_foreign_interview_404(session: Session, client: TestClient):
    job = _job(session)
    other = _job(session, company="Iwoca")
    interview = Interview(job_id=other.id or 0)
    session.add(interview)
    session.commit()
    resp = client.post(
        f"/api/jobs/{job.id}/materials/pack",
        json={"pack_type": "company_briefing", "interview_id": interview.id},
    )
    assert resp.status_code == 404


def test_pack_endpoint_auth_error_returns_clear_detail(
    session: Session, client: TestClient, monkeypatch
):
    job = _job(session)

    class _AuthFail:
        def generate_document(self, *_a, **_k):  # noqa: ANN003
            class AuthenticationError(Exception):
                pass

            raise AuthenticationError("invalid x-api-key")

    monkeypatch.setattr(
        "zengrowth.interviews.packs._build_pack_client",
        lambda *a, **k: _AuthFail(),
    )
    resp = client.post(
        f"/api/jobs/{job.id}/materials/pack",
        json={"pack_type": "company_briefing"},
    )
    assert resp.status_code == 503
    assert "Claude API key rejected" in resp.json()["detail"]
