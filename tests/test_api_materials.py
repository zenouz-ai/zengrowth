"""API tests for material preview, download, revise, and retention."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from zengrowth.api.main import app
from zengrowth.db import get_session
from zengrowth.ingestion.dedup import dedup_hash
from zengrowth.materials import generator
from zengrowth.materials.retention import purge_old_material_versions
from zengrowth.models import GeneratedMaterial, Job


@pytest.fixture
def client_with_session(session: Session):
    def override_get_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def _job(session: Session) -> Job:
    job = Job(
        company="Acme",
        title="AI Lead",
        source="manual",
        dedup_hash=dedup_hash("Acme", "AI Lead", None),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _cv_material(session: Session, job: Job, tmp_path: Path, *, version: int = 1, is_final: bool = False) -> GeneratedMaterial:
    out_dir = tmp_path / str(job.id) / f"v{version}"
    out_dir.mkdir(parents=True)
    tex_path = out_dir / "cv.tex"
    tex_path.write_text(r"\documentclass{article}\begin{document}CV\end{document}", encoding="utf-8")
    pdf_path = out_dir / "cv.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    material = GeneratedMaterial(
        job_id=job.id or 0,
        material_type="cv",
        title=f"Tailored CV v{version}",
        tex_path=str(tex_path),
        pdf_path=str(pdf_path),
        status="created_pdf",
        evidence_ids=["evi-profile-001"],
        draft_json={
            "title": f"Tailored CV v{version}",
            "summary": "Strong match.",
            "bullets": ["Led AI delivery."],
            "body": None,
            "evidence_ids": ["evi-profile-001"],
        },
        version=version,
        is_final=is_final,
    )
    session.add(material)
    session.commit()
    session.refresh(material)
    return material


def test_get_material_detail_includes_draft(session: Session, tmp_path, monkeypatch, client_with_session: TestClient):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    material = _cv_material(session, job, tmp_path / "materials")

    response = client_with_session.get(f"/api/jobs/{job.id}/materials/{material.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["preview_mode"] == "structured"
    assert data["draft_json"]["summary"] == "Strong match."
    assert data["pdf_available"] is True
    assert data["version"] == 1


def test_download_material_pdf(session: Session, tmp_path, monkeypatch, client_with_session: TestClient):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    material = _cv_material(session, job, tmp_path / "materials")

    response = client_with_session.get(f"/api/jobs/{job.id}/materials/{material.id}/file/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.content.startswith(b"%PDF")
    assert 'filename="Jordan_Avery_CV_Acme_v1.pdf"' in response.headers.get("content-disposition", "")


def _fake_compile(path: Path):
    pdf = path.with_suffix(".pdf")
    pdf.write_bytes(b"%PDF-1.4\n")
    return pdf, "pdf_created"


def test_revise_cv_creates_new_version(session: Session, tmp_path, monkeypatch, client_with_session: TestClient):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    cv_source = tmp_path / "docs/career/processed/cv_source.tex"
    cv_source.parent.mkdir(parents=True)
    cv_source.write_text(r"\section*{Professional Summary}{CV body}", encoding="utf-8")
    monkeypatch.setattr(generator, "CV_SOURCE", cv_source)
    monkeypatch.setattr("zengrowth.materials.revise.compile_pdf", _fake_compile)
    job = _job(session)
    material = _cv_material(session, job, tmp_path / "materials")

    response = client_with_session.patch(
        f"/api/jobs/{job.id}/materials/{material.id}",
        json={"mode": "structured", "draft": {"summary": "Updated summary.", "bullets": ["New bullet."]}},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["version"] == 2
    assert data["draft_json"]["summary"] == "Updated summary."
    assert data["supersedes_id"] == material.id
    assert data["pdf_available"] is True


def test_cover_letter_revise_and_download(session: Session, tmp_path, monkeypatch, client_with_session: TestClient):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "materials"
    monkeypatch.setattr(generator, "MATERIALS_ROOT", root)
    monkeypatch.setattr("zengrowth.materials.revise.compile_pdf", _fake_compile)
    job = _job(session)
    out_dir = root / str(job.id) / "letter"
    out_dir.mkdir(parents=True)
    tex_path = out_dir / "cover_letter.tex"
    tex_path.write_text(r"\documentclass{article}\begin{document}Letter\end{document}", encoding="utf-8")
    material = GeneratedMaterial(
        job_id=job.id or 0,
        material_type="cover_letter",
        title="Cover letter",
        tex_path=str(tex_path),
        pdf_path=str(out_dir / "cover_letter.pdf"),
        status="created_pdf",
        evidence_ids=["evi-profile-001"],
        draft_json={
            "title": "Cover letter",
            "summary": None,
            "bullets": [],
            "body": "Dear team,\n\nI am interested.",
            "evidence_ids": ["evi-profile-001"],
        },
        version=1,
    )
    session.add(material)
    session.commit()
    session.refresh(material)
    (out_dir / "cover_letter.pdf").write_bytes(b"%PDF-1.4\n")

    revised = client_with_session.patch(
        f"/api/jobs/{job.id}/materials/{material.id}",
        json={"mode": "structured", "draft": {"body": "Dear MUFG,\n\nUpdated hook."}},
    )
    assert revised.status_code == 200
    assert revised.json()["version"] == 2

    download = client_with_session.get(f"/api/jobs/{job.id}/materials/{revised.json()['id']}/file/pdf")
    assert download.status_code == 200


def test_mark_final_clears_sibling_final_flag(session: Session, tmp_path, monkeypatch, client_with_session: TestClient):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    first = _cv_material(session, job, tmp_path / "materials", version=1, is_final=True)
    second = _cv_material(session, job, tmp_path / "materials", version=2)

    response = client_with_session.post(f"/api/jobs/{job.id}/materials/{second.id}/mark-final")

    assert response.status_code == 200
    assert response.json()["is_final"] is True
    session.refresh(first)
    assert first.is_final is False


class _FakeInstructionClient:
    def __init__(self, output: str) -> None:
        self.output = output
        self.last_user: str | None = None

    def complete_text(self, system: str, user: str, model: str, max_tokens: int = 8000, **kwargs) -> str:
        self.last_user = user
        return self.output


def test_revise_request_creates_new_version(session: Session, tmp_path, monkeypatch, client_with_session: TestClient):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    monkeypatch.setattr("zengrowth.materials.revise.compile_pdf", _fake_compile)
    fake = _FakeInstructionClient(
        r"\documentclass{article}\begin{document}Revised CV with shorter summary\end{document}"
    )
    monkeypatch.setattr("zengrowth.materials.revise._build_client", lambda settings, session=None, entity_id=None: fake)
    job = _job(session)
    material = _cv_material(session, job, tmp_path / "materials")

    response = client_with_session.post(
        f"/api/jobs/{job.id}/materials/{material.id}/revise-request",
        json={"instruction": "Make the summary shorter."},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["version"] == 2
    assert data["supersedes_id"] == material.id
    assert data["pdf_available"] is True
    assert "Make the summary shorter." in (fake.last_user or "")


def test_revise_request_rejects_non_latex_output(session: Session, tmp_path, monkeypatch, client_with_session: TestClient):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    monkeypatch.setattr("zengrowth.materials.revise.compile_pdf", _fake_compile)
    monkeypatch.setattr(
        "zengrowth.materials.revise._build_client",
        lambda settings, session=None, entity_id=None: _FakeInstructionClient("Sorry, I cannot help with that."),
    )
    job = _job(session)
    material = _cv_material(session, job, tmp_path / "materials")

    response = client_with_session.post(
        f"/api/jobs/{job.id}/materials/{material.id}/revise-request",
        json={"instruction": "Do something odd."},
    )

    assert response.status_code == 502


def test_revise_request_requires_instruction(session: Session, tmp_path, monkeypatch, client_with_session: TestClient):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    material = _cv_material(session, job, tmp_path / "materials")

    response = client_with_session.post(
        f"/api/jobs/{job.id}/materials/{material.id}/revise-request",
        json={"instruction": "   "},
    )

    assert response.status_code == 400


def test_fit_pages_shortens_long_cv(session: Session, tmp_path, monkeypatch, client_with_session: TestClient):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")

    state = {"pages": 3}

    def fake_compile(path):
        path.with_suffix(".pdf").write_bytes(b"%PDF-1.4\n")
        return path.with_suffix(".pdf"), "pdf_created"

    monkeypatch.setattr("zengrowth.materials.revise.compile_pdf", fake_compile)
    monkeypatch.setattr("zengrowth.materials.generator.compile_pdf", fake_compile)
    monkeypatch.setattr("zengrowth.materials.generator.measure_pdf_extent", lambda pdf: (state["pages"], 0.9))

    class FitClient:
        def complete_text(self, system, user, model, max_tokens=8000, **kwargs):
            state["pages"] = 2
            return r"\documentclass{article}\begin{document}SHORT\end{document}"

    monkeypatch.setattr("zengrowth.materials.revise._build_client", lambda settings, session=None, entity_id=None: FitClient())
    job = _job(session)
    material = _cv_material(session, job, tmp_path / "materials")
    material.page_count = 3
    session.add(material)
    session.commit()

    response = client_with_session.post(f"/api/jobs/{job.id}/materials/{material.id}/fit-pages")

    assert response.status_code == 200
    data = response.json()
    assert data["version"] == 2
    assert data["page_count"] == 2
    assert data["page_fit"] == "ok"


def test_fit_pages_rejects_already_fitting_cv(session: Session, tmp_path, monkeypatch, client_with_session: TestClient):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    material = _cv_material(session, job, tmp_path / "materials")
    material.page_count = 2
    material.page_fill = 0.9
    session.add(material)
    session.commit()

    response = client_with_session.post(f"/api/jobs/{job.id}/materials/{material.id}/fit-pages")

    assert response.status_code == 400


def test_unmark_final_returns_material_to_review(session: Session, tmp_path, monkeypatch, client_with_session: TestClient):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    material = _cv_material(session, job, tmp_path / "materials", is_final=True)

    response = client_with_session.post(f"/api/jobs/{job.id}/materials/{material.id}/unmark-final")

    assert response.status_code == 200
    assert response.json()["is_final"] is False
    session.refresh(material)
    assert material.is_final is False


def test_material_detail_exposes_page_fit_and_tex_content(session: Session, tmp_path, monkeypatch, client_with_session: TestClient):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    material = _cv_material(session, job, tmp_path / "materials")
    material.page_count = 2
    material.page_fill = 0.92
    session.add(material)
    session.commit()

    data = client_with_session.get(f"/api/jobs/{job.id}/materials/{material.id}").json()

    assert data["page_count"] == 2
    assert data["page_fit"] == "ok"
    assert data["tex_content"] is not None


def test_retention_keeps_final_and_purges_old_versions(session: Session, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    old = _cv_material(session, job, tmp_path / "materials", version=1)
    final = _cv_material(session, job, tmp_path / "materials", version=2, is_final=True)
    old.created_at = datetime.now(UTC) - timedelta(days=45)
    final.created_at = datetime.now(UTC) - timedelta(days=45)
    session.add(old)
    session.add(final)
    session.commit()

    purged = purge_old_material_versions(session, retention_days=30, now=datetime.now(UTC))

    assert old.id in purged
    assert session.get(GeneratedMaterial, final.id) is not None
    assert session.get(GeneratedMaterial, old.id) is None


def test_legacy_material_latex_fallback(session: Session, tmp_path, monkeypatch, client_with_session: TestClient):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "materials"
    monkeypatch.setattr(generator, "MATERIALS_ROOT", root)
    job = _job(session)
    out_dir = root / str(job.id) / "legacy"
    out_dir.mkdir(parents=True)
    tex_path = out_dir / "cv.tex"
    tex_path.write_text("legacy tex content", encoding="utf-8")
    material = GeneratedMaterial(
        job_id=job.id or 0,
        material_type="cv",
        title="Legacy CV",
        tex_path=str(tex_path),
        status="pdf_unavailable_no_latex_compiler",
        evidence_ids=["evi-profile-001"],
        version=1,
    )
    session.add(material)
    session.commit()
    session.refresh(material)

    response = client_with_session.get(f"/api/jobs/{job.id}/materials/{material.id}")

    assert response.status_code == 200
    assert response.json()["preview_mode"] == "latex_fallback"
    assert "legacy tex content" in response.json()["fallback_content"]
