from collections.abc import Iterator
from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from zengrowth.api.main import app
from zengrowth.db import get_session
from zengrowth.ingestion.job_description_extractor import ExtractedJobFields
from zengrowth.models import GeneratedMaterial, Job, LifecycleState


def test_jobs_extract_endpoint_returns_structured_fields(monkeypatch):
    def fake_extract_job_fields(*, raw_text: str, application_url: str | None = None):
        assert raw_text == "Lead AI strategy."
        assert application_url == "https://example.com/job"
        return ExtractedJobFields(
            company="Acme",
            title="Director of AI",
            location="London",
            hybrid_policy="2 days/week London",
            compensation={"min_gbp": 130000, "max_gbp": 160000},
            seniority="Director",
            application_url=application_url,
            posting_date=date(2026, 5, 20),
            description=raw_text,
            missing_fields=[],
            confidence_notes="All core fields were explicit.",
        )

    monkeypatch.setattr("zengrowth.api.routers.jobs.extract_job_fields", fake_extract_job_fields)
    client = TestClient(app)

    response = client.post(
        "/api/jobs/extract",
        json={"raw_text": "Lead AI strategy.", "application_url": "https://example.com/job"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["company"] == "Acme"
    assert data["title"] == "Director of AI"
    assert data["compensation"] == {"min_gbp": 130000, "max_gbp": 160000}
    assert data["posting_date"] == "2026-05-20"
    assert data["description"] == "Lead AI strategy."


def test_extracted_payload_can_be_saved_as_job(session: Session):
    def override_get_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)
    try:
        payload = {
            "company": "Acme",
            "title": "Director of AI",
            "location": "London",
            "hybrid_policy": "2 days/week London",
            "compensation": {"min_gbp": 130000, "max_gbp": 160000},
            "seniority": "Director",
            "application_url": "https://example.com/job",
            "posting_date": "2026-05-20",
            "description": "Lead AI strategy.",
            "source": "manual",
        }

        response = client.post("/api/jobs", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert data["id"] is not None
        assert data["company"] == "Acme"
        assert data["description"] == "Lead AI strategy."
    finally:
        app.dependency_overrides.clear()


def test_patch_job_application_url(session: Session):
    def override_get_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)
    try:
        create = client.post(
            "/api/jobs",
            json={"company": "Acme", "title": "Director of AI", "source": "manual"},
        )
        assert create.status_code == 201
        job_id = create.json()["id"]

        response = client.patch(
            f"/api/jobs/{job_id}",
            json={"application_url": "https://example.com/apply"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["application_url"] == "https://example.com/apply"
    finally:
        app.dependency_overrides.clear()


def test_purge_archived_jobs(session: Session):
    def override_get_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)
    try:
        for i, state in enumerate([LifecycleState.archived, LifecycleState.prepared]):
            session.add(
                Job(
                    company=f"Co{i}",
                    title=f"Role{i}",
                    dedup_hash=f"purge-{i}",
                    lifecycle_state=state,
                    source="manual",
                )
            )
        session.commit()

        response = client.post("/api/jobs/purge", json={"lifecycle_state": "archived"})

        assert response.status_code == 200
        assert response.json() == {"deleted": 1, "lifecycle_state": "archived"}
        remaining = list(session.exec(select(Job)))
        assert len(remaining) == 1
        assert remaining[0].lifecycle_state == LifecycleState.prepared
    finally:
        app.dependency_overrides.clear()


def test_jobs_curated_filter_hides_unprocessed_and_low_fit_jobs(session: Session):
    def override_get_session() -> Iterator[Session]:
        yield session

    clean = Job(
        company="Acme",
        title="Director of AI",
        source="manual",
        dedup_hash="clean",
        job_summary={"role_overview": "Clean."},
        summary_updated_at=datetime(2026, 6, 1, tzinfo=UTC),
        fit_score=72,
        expected_value=900,
    )
    raw = Job(company="RawCo", title="AI Lead", source="manual", dedup_hash="raw")
    low = Job(
        company="LowCo",
        title="AI Manager",
        source="manual",
        dedup_hash="low",
        job_summary={"role_overview": "Low fit."},
        summary_updated_at=datetime(2026, 6, 1, tzinfo=UTC),
        fit_score=40,
        expected_value=100,
    )
    raw_high_ev = Job(
        company="RawHigh",
        title="AI Lead",
        source="manual",
        dedup_hash="raw-high",
        expected_value=9999,
    )
    archived = Job(
        company="ArchivedCo",
        title="Director of AI",
        source="manual",
        dedup_hash="archived",
        job_summary={"role_overview": "Archived."},
        summary_updated_at=datetime(2026, 6, 1, tzinfo=UTC),
        fit_score=88,
        expected_value=2000,
        lifecycle_state=LifecycleState.archived,
    )
    session.add(clean)
    session.add(raw)
    session.add(low)
    session.add(raw_high_ev)
    session.add(archived)
    session.commit()

    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)
    try:
        all_jobs = client.get("/api/jobs").json()
        curated = client.get("/api/jobs", params={"curated": True}).json()

        assert {job["company"] for job in all_jobs} == {
            "Acme",
            "RawCo",
            "LowCo",
            "RawHigh",
            "ArchivedCo",
        }
        assert [job["company"] for job in curated] == ["Acme", "LowCo"]

        limited = client.get("/api/jobs", params={"curated": True, "limit": 1}).json()
        assert [job["company"] for job in limited] == ["Acme"]
    finally:
        app.dependency_overrides.clear()


def test_ingestion_endpoint_runs_in_background(monkeypatch, session: Session):
    # The endpoint must return immediately (202) and run the ingest as a
    # background task — the synchronous version timed out at the ~100s edge proxy
    # limit on a real precheck batch even though the work completed server-side.
    def override_get_session() -> Iterator[Session]:
        yield session

    class FakeIngestionResult:
        added = 3
        skipped_duplicate = 1
        skipped_stale = 2
        prechecked = 4
        archived = 2
        failed_precheck = 1
        succeeded_boards = ["greenhouse:anthropic"]
        failed_boards = ["lever:missing"]
        skipped_locked = False

    calls: list[bool] = []

    def fake_run_all() -> FakeIngestionResult:
        calls.append(True)
        return FakeIngestionResult()

    app.dependency_overrides[get_session] = override_get_session
    monkeypatch.setattr("zengrowth.api.routers.ingestion.run_all", fake_run_all)
    client = TestClient(app)
    try:
        response = client.post("/api/ingestion/run")

        assert response.status_code == 202
        assert response.json() == {"status": "started"}
        # TestClient runs background tasks after the response is sent.
        assert calls == [True]
    finally:
        app.dependency_overrides.clear()


def test_jobs_summarize_endpoint(monkeypatch, session: Session):
    def override_get_session() -> Iterator[Session]:
        yield session

    def fake_summarize_job(session: Session, job):
        job.job_summary = {"role_overview": "Clean role summary."}
        session.add(job)
        session.commit()
        session.refresh(job)
        return job

    app.dependency_overrides[get_session] = override_get_session
    monkeypatch.setattr("zengrowth.api.routers.jobs.summarize_job", fake_summarize_job)
    client = TestClient(app)
    try:
        created = client.post("/api/jobs", json={"company": "Acme", "title": "AI Lead", "source": "manual"}).json()
        response = client.post(f"/api/jobs/{created['id']}/summarize")

        assert response.status_code == 200
        assert response.json()["job_summary"] == {"role_overview": "Clean role summary."}
    finally:
        app.dependency_overrides.clear()


def test_material_endpoints_create_and_list_records(monkeypatch, session: Session, tmp_path):
    def override_get_session() -> Iterator[Session]:
        yield session

    def fake_generate_cv(session: Session, job):
        material = GeneratedMaterial(
            job_id=job.id,
            material_type="cv",
            title="Tailored CV",
            tex_path=str(tmp_path / "cv.tex"),
            status="pdf_unavailable_no_latex_compiler",
            evidence_ids=["evi-profile-001"],
        )
        session.add(material)
        session.commit()
        session.refresh(material)
        return material

    app.dependency_overrides[get_session] = override_get_session
    monkeypatch.setattr("zengrowth.api.routers.jobs.generate_cv", fake_generate_cv)
    client = TestClient(app)
    try:
        created = client.post("/api/jobs", json={"company": "Acme", "title": "AI Lead", "source": "manual"}).json()
        response = client.post(f"/api/jobs/{created['id']}/materials/cv")
        assert response.status_code == 200
        assert response.json()["material_type"] == "cv"

        listed = client.get(f"/api/jobs/{created['id']}/materials")
        assert listed.status_code == 200
        assert len(listed.json()) == 1
        assert listed.json()[0]["title"] == "Tailored CV"
    finally:
        app.dependency_overrides.clear()


def test_answer_endpoint_passes_word_limit(monkeypatch, session: Session):
    captured = {}

    def override_get_session() -> Iterator[Session]:
        yield session

    def fake_generate_answer(session: Session, job, *, question: str, word_limit: int | None = None, instructions: str | None = None):
        captured["question"] = question
        captured["word_limit"] = word_limit
        captured["instructions"] = instructions
        material = GeneratedMaterial(
            job_id=job.id,
            material_type="answer",
            title="Answer",
            markdown_path="data/materials/1/answer.md",
            status="created_markdown",
        )
        session.add(material)
        session.commit()
        session.refresh(material)
        return material

    app.dependency_overrides[get_session] = override_get_session
    monkeypatch.setattr("zengrowth.api.routers.jobs.generate_answer", fake_generate_answer)
    client = TestClient(app)
    try:
        created = client.post("/api/jobs", json={"company": "Acme", "title": "AI Lead", "source": "manual"}).json()
        response = client.post(
            f"/api/jobs/{created['id']}/materials/answer",
            json={"question": "Why us?", "word_limit": 200, "instructions": "Concise"},
        )

        assert response.status_code == 200
        assert captured == {"question": "Why us?", "word_limit": 200, "instructions": "Concise"}
    finally:
        app.dependency_overrides.clear()


def test_material_endpoint_reports_missing_anthropic_key(monkeypatch, session: Session):
    def override_get_session() -> Iterator[Session]:
        yield session

    def fake_generate_cv(session: Session, job):
        raise RuntimeError("ANTHROPIC_API_KEY is required for materials.")

    app.dependency_overrides[get_session] = override_get_session
    monkeypatch.setattr("zengrowth.api.routers.jobs.generate_cv", fake_generate_cv)
    client = TestClient(app)
    try:
        created = client.post("/api/jobs", json={"company": "Acme", "title": "AI Lead", "source": "manual"}).json()
        response = client.post(f"/api/jobs/{created['id']}/materials/cv")
        assert response.status_code == 503
        assert "ANTHROPIC_API_KEY" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()
