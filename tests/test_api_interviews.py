"""Interview timeline + internal-artifact import endpoints (INT-01)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from zengrowth.api.main import app
from zengrowth.db import get_session
from zengrowth.ingestion.dedup import dedup_hash
from zengrowth.materials import generator
from zengrowth.models import GeneratedMaterial, Interview, Job


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


# --- CRUD + backdating -------------------------------------------------------


def test_create_interview_backdated(session: Session, client: TestClient):
    job = _job(session)
    resp = client.post(
        f"/api/jobs/{job.id}/interviews",
        json={
            "round_type": "recruiter_screen",
            "title": "Initial screening call",
            "format": "phone",
            "status": "completed",
            "scheduled_at": "2026-05-16T10:00:00Z",
            "occurred_at": "2026-05-16T10:00:00Z",
            "participants": [{"name": "Sam Recruiter", "role": "Talent partner"}],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["round_type"] == "recruiter_screen"
    assert data["occurred_at"].startswith("2026-05-16")
    assert data["participants"][0]["name"] == "Sam Recruiter"
    assert data["has_transcript"] is False


def test_create_interview_with_transcript(session: Session, client: TestClient):
    job = _job(session)
    resp = client.post(
        f"/api/jobs/{job.id}/interviews",
        json={
            "round_type": "recruiter_screen",
            "status": "completed",
            "transcript": "Interviewer: Tell me about your AI CoE experience.",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["has_transcript"] is True
    assert data["can_debrief"] is True
    assert data["transcript_updated_at"] is not None
    detail = client.get(f"/api/jobs/{job.id}/interviews/{data['id']}").json()
    assert "AI CoE" in detail["transcript"]


def test_timeline_sorts_by_event_date_not_entry_order(session: Session, client: TestClient):
    job = _job(session)
    # Entered out of order — the timeline must sort by when the round happened.
    client.post(
        f"/api/jobs/{job.id}/interviews",
        json={"round_type": "technical", "occurred_at": "2026-06-16T14:00:00Z"},
    )
    client.post(
        f"/api/jobs/{job.id}/interviews",
        json={"round_type": "recruiter_screen", "occurred_at": "2026-05-16T10:00:00Z"},
    )
    client.post(
        f"/api/jobs/{job.id}/interviews",
        json={"round_type": "final_round", "scheduled_at": "2026-07-09T09:00:00Z"},
    )
    rows = client.get(f"/api/jobs/{job.id}/interviews").json()
    assert [row["round_type"] for row in rows] == ["recruiter_screen", "technical", "final_round"]


def test_patch_interview_updates_fields(session: Session, client: TestClient):
    job = _job(session)
    created = client.post(
        f"/api/jobs/{job.id}/interviews", json={"round_type": "team", "status": "scheduled"}
    ).json()
    resp = client.patch(
        f"/api/jobs/{job.id}/interviews/{created['id']}",
        json={"status": "completed", "occurred_at": "2026-07-02T15:00:00Z", "notes": "Went well."},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["notes"] == "Went well."
    assert data["occurred_at"].startswith("2026-07-02")


def test_delete_interview_detaches_materials(session: Session, client: TestClient):
    job = _job(session)
    created = client.post(f"/api/jobs/{job.id}/interviews", json={"round_type": "technical"}).json()
    material = GeneratedMaterial(
        job_id=job.id or 0,
        interview_id=created["id"],
        material_type="debrief",
        audience="internal",
        title="Technical debrief",
        status="imported",
    )
    session.add(material)
    session.commit()
    session.refresh(material)

    assert client.delete(f"/api/jobs/{job.id}/interviews/{created['id']}").status_code == 204
    session.refresh(material)
    assert material.interview_id is None  # artifact survives at job level
    assert session.get(Interview, created["id"]) is None


def test_interview_404s(session: Session, client: TestClient):
    job = _job(session)
    other = _job(session, company="Iwoca")
    created = client.post(f"/api/jobs/{job.id}/interviews", json={"round_type": "other"}).json()
    assert client.get("/api/jobs/999/interviews").status_code == 404
    assert client.get(f"/api/jobs/{job.id}/interviews/999").status_code == 404
    # An interview is not reachable through another job's path.
    assert client.get(f"/api/jobs/{other.id}/interviews/{created['id']}").status_code == 404


# --- outcome / lifecycle sync -------------------------------------------------


def test_create_interview_syncs_outcome_stage(session: Session, client: TestClient):
    job = _job(session)
    client.post(f"/api/jobs/{job.id}/interviews", json={"round_type": "recruiter_screen"})
    session.refresh(job)
    assert job.outcome_stage == "recruiter_screen"
    assert job.lifecycle_state == "interviewing"

    client.post(f"/api/jobs/{job.id}/interviews", json={"round_type": "final_round"})
    session.refresh(job)
    assert job.outcome_stage == "final_round"


def test_sync_never_downgrades_stage(session: Session, client: TestClient):
    job = _job(session)
    client.post(f"/api/jobs/{job.id}/interviews", json={"round_type": "final_round"})
    client.post(f"/api/jobs/{job.id}/interviews", json={"round_type": "recruiter_screen"})
    session.refresh(job)
    assert job.outcome_stage == "final_round"


def test_sync_outcome_opt_out(session: Session, client: TestClient):
    job = _job(session)
    client.post(
        f"/api/jobs/{job.id}/interviews",
        json={"round_type": "recruiter_screen", "sync_outcome": False},
    )
    session.refresh(job)
    assert job.outcome_stage is None
    assert job.lifecycle_state == "discovered"


def test_sync_skips_terminal_jobs(session: Session, client: TestClient):
    from zengrowth.models import LifecycleState, OutcomeResult

    job = _job(session)
    job.lifecycle_state = LifecycleState.rejected
    job.outcome_result = OutcomeResult.rejected
    job.outcome_stage = "recruiter_screen"
    session.add(job)
    session.commit()
    session.refresh(job)

    client.post(f"/api/jobs/{job.id}/interviews", json={"round_type": "final_round"})
    session.refresh(job)
    assert job.outcome_stage == "recruiter_screen"
    assert job.lifecycle_state == LifecycleState.rejected


def test_sync_does_not_backfill_applied_at(session: Session, client: TestClient):
    """Backdated journeys set applied_at explicitly; sync must not stamp 'now'."""
    job = _job(session)
    client.post(f"/api/jobs/{job.id}/interviews", json={"round_type": "technical"})
    session.refresh(job)
    assert job.applied_at is None


# --- transcript ----------------------------------------------------------------


def test_set_and_read_transcript(session: Session, client: TestClient):
    job = _job(session)
    created = client.post(
        f"/api/jobs/{job.id}/interviews", json={"round_type": "recruiter_screen"}
    ).json()
    resp = client.put(
        f"/api/jobs/{job.id}/interviews/{created['id']}/transcript",
        json={"transcript": "Interviewer: welcome...\nMe: thanks..."},
    )
    assert resp.status_code == 200
    assert resp.json()["has_transcript"] is True

    detail = client.get(f"/api/jobs/{job.id}/interviews/{created['id']}").json()
    assert detail["transcript"].startswith("Interviewer: welcome")
    # List view exposes only the flag, not the transcript body.
    listed = client.get(f"/api/jobs/{job.id}/interviews").json()[0]
    assert listed["has_transcript"] is True
    assert listed["can_debrief"] is True
    assert "transcript" not in listed


def test_can_debrief_with_notes_only(session: Session, client: TestClient):
    job = _job(session)
    created = client.post(
        f"/api/jobs/{job.id}/interviews",
        json={
            "round_type": "recruiter_screen",
            "notes": "Recruiter asked about team size and notice period.",
        },
    ).json()
    listed = client.get(f"/api/jobs/{job.id}/interviews").json()[0]
    assert listed["id"] == created["id"]
    assert listed["has_transcript"] is False
    assert listed["can_debrief"] is True


# --- internal artifact import ---------------------------------------------------


def _import_payload(**overrides) -> dict:
    payload = {
        "material_type": "company_briefing",
        "title": "Intact research pack",
        "content": "# Intact\n\nBusiness overview...",
        "effective_date": "2026-05-13T09:00:00Z",
    }
    payload.update(overrides)
    return payload


def test_import_material_backdated(session: Session, client: TestClient, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    resp = client.post(f"/api/jobs/{job.id}/materials/import", json=_import_payload())
    assert resp.status_code == 201
    data = resp.json()
    assert data["material_type"] == "company_briefing"
    assert data["audience"] == "internal"
    assert data["effective_date"].startswith("2026-05-13")
    assert data["status"] == "imported"
    assert Path(
        session.get(GeneratedMaterial, data["id"]).markdown_path
    ).read_text(encoding="utf-8").startswith("# Intact")


def test_import_material_attached_to_interview(
    session: Session, client: TestClient, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    interview = client.post(
        f"/api/jobs/{job.id}/interviews", json={"round_type": "technical"}
    ).json()
    resp = client.post(
        f"/api/jobs/{job.id}/materials/import",
        json=_import_payload(material_type="debrief", interview_id=interview["id"]),
    )
    assert resp.status_code == 201
    assert resp.json()["interview_id"] == interview["id"]


def test_import_material_detail_and_download(
    session: Session, client: TestClient, tmp_path: Path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    material_id = client.post(
        f"/api/jobs/{job.id}/materials/import", json=_import_payload()
    ).json()["id"]

    detail = client.get(f"/api/jobs/{job.id}/materials/{material_id}").json()
    assert detail["preview_mode"] == "markdown"
    assert detail["markdown_available"] is True
    assert detail["fallback_content"].startswith("# Intact")

    download = client.get(f"/api/jobs/{job.id}/materials/{material_id}/file/md")
    assert download.status_code == 200
    assert "Business overview" in download.text


def test_import_material_rejects_unknown_type(session: Session, client: TestClient):
    job = _job(session)
    resp = client.post(
        f"/api/jobs/{job.id}/materials/import", json=_import_payload(material_type="cv")
    )
    assert resp.status_code == 400


def test_import_material_rejects_foreign_interview(
    session: Session, client: TestClient, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    other = _job(session, company="Iwoca")
    foreign = client.post(f"/api/jobs/{other.id}/interviews", json={"round_type": "other"}).json()
    resp = client.post(
        f"/api/jobs/{job.id}/materials/import",
        json=_import_payload(material_type="debrief", interview_id=foreign["id"]),
    )
    assert resp.status_code == 404


def test_delete_job_removes_interviews(session: Session, client: TestClient):
    job = _job(session)
    created = client.post(f"/api/jobs/{job.id}/interviews", json={"round_type": "other"}).json()
    assert client.delete(f"/api/jobs/{job.id}").status_code == 204
    assert session.get(Interview, created["id"]) is None
