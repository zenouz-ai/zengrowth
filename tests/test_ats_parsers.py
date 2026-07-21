from datetime import date

from zengrowth.ingestion.ats_greenhouse import parse_greenhouse_job
from zengrowth.ingestion.ats_lever import parse_lever_job
from zengrowth.models import JobSource


def test_parse_greenhouse_job_extracts_core_fields():
    payload = {
        "title": "Head of AI",
        "company_name": "Acme",
        "location": {"name": "London, UK"},
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
        "content": "<p>Lead the AI team. <strong>5+ years</strong>.</p>",
        "updated_at": "2025-05-01T12:00:00Z",
        "metadata": [{"name": "Remote", "value": "Hybrid"}],
    }
    job = parse_greenhouse_job("acme", payload)
    assert job.company == "Acme"
    assert job.title == "Head of AI"
    assert job.location == "London, UK"
    assert job.posting_date == date(2025, 5, 1)
    assert job.source == JobSource.greenhouse
    assert job.dedup_hash
    assert "5+ years" in (job.description or "")
    assert "<p>" not in (job.description or "")
    assert job.hybrid_policy == "Hybrid"


def test_parse_greenhouse_dedup_stable_when_updated_at_changes():
    # EA-01: an edited posting (new updated_at) keeps the same identity via id.
    base = {
        "id": 12345,
        "title": "Head of AI",
        "company_name": "Acme",
        "updated_at": "2025-05-01T12:00:00Z",
    }
    edited = {**base, "title": "Head of AI (Remote)", "updated_at": "2025-06-09T08:00:00Z"}
    assert parse_greenhouse_job("acme", base).dedup_hash == parse_greenhouse_job("acme", edited).dedup_hash


def test_parse_greenhouse_dedup_scoped_by_board_slug():
    # EA-01: Greenhouse posting ids are unique per board, not globally, so the
    # same numeric id on two different boards must not collide.
    payload = {"id": 12345, "title": "Head of AI", "updated_at": "2025-05-01T12:00:00Z"}
    a = parse_greenhouse_job("anthropic", payload)
    b = parse_greenhouse_job("stripe", payload)
    assert a.dedup_hash != b.dedup_hash


def test_parse_greenhouse_job_handles_missing_optional_fields():
    payload = {"title": "Eng", "content": None}
    job = parse_greenhouse_job("acme", payload)
    assert job.company == "acme"
    assert job.posting_date is None
    assert job.description is None


def test_parse_lever_job_extracts_core_fields():
    payload = {
        "text": "Director of Data Science",
        "categories": {"location": "Remote (UK)", "commitment": "Full-time"},
        "workplaceType": "hybrid",
        "createdAt": 1714560000000,  # 2024-05-01 UTC
        "hostedUrl": "https://jobs.lever.co/acme/abc",
        "descriptionPlain": "Lead the DS function.",
    }
    job = parse_lever_job("acme", payload)
    assert job.title == "Director of Data Science"
    assert job.location == "Remote (UK)"
    assert job.seniority == "Full-time"
    assert job.hybrid_policy == "hybrid"
    assert job.posting_date == date(2024, 5, 1)
    assert job.source == JobSource.lever
    assert job.description == "Lead the DS function."


def test_parse_lever_dedup_stable_when_updated_at_changes():
    # EA-01: same Lever posting id keeps a stable identity across edits.
    base = {"id": "abc-uuid", "text": "Director of DS", "createdAt": 1714560000000}
    edited = {**base, "text": "Director of DS (Hybrid)", "updatedAt": 1717238400000}
    assert parse_lever_job("acme", base).dedup_hash == parse_lever_job("acme", edited).dedup_hash


def test_parse_lever_handles_missing_timestamps():
    payload = {"text": "Eng", "categories": {}}
    job = parse_lever_job("acme", payload)
    assert job.posting_date is None
    assert job.location is None
