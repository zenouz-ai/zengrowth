from datetime import date
from typing import Any

import pytest

from zengrowth.config import Settings
from zengrowth.ingestion.dedup import dedup_hash
from zengrowth.ingestion.job_summarizer import summarize_job
from zengrowth.models import Job, JobSource


class FakeSummaryClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response

    def summarize(self, system: str, user: str, model: str) -> dict[str, Any]:
        return self.response


def _job() -> Job:
    return Job(
        company="SS&C Technologies",
        title="Senior Director, AI Strategy & Delivery",
        location="London",
        posting_date=date(2026, 5, 26),
        description="SS&C Careers\nSign In\nSenior Director role leading AI strategy.",
        source=JobSource.manual,
        dedup_hash=dedup_hash("SS&C Technologies", "Senior Director, AI Strategy & Delivery", date(2026, 5, 26)),
    )


def test_summarize_job_persists_clean_summary(session):
    job = _job()
    session.add(job)
    session.commit()
    session.refresh(job)
    client = FakeSummaryClient(
        {
            "role_overview": "Senior AI strategy role in financial services technology.",
            "responsibilities": ["Lead AI strategy", "Deliver enterprise AI programmes"],
            "requirements": ["AI leadership", "Stakeholder management"],
            "company_domain": "Financial services and healthcare technology",
            "location_hybrid": "London or Basildon; hybrid unspecified",
            "compensation": None,
            "application_notes": ["Requisition R43900"],
            "noise_removed": ["SS&C Careers", "Sign In"],
        }
    )

    summarized = summarize_job(
        session,
        job,
        client=client,
        settings=Settings(anthropic_api_key="test", scoring_model="claude-test"),
    )

    assert summarized.job_summary is not None
    assert summarized.job_summary["role_overview"].startswith("Senior AI strategy")
    assert "SS&C Careers" in summarized.job_summary["noise_removed"]
    assert summarized.summary_updated_at is not None


def test_summarize_job_rejects_invalid_shape(session):
    job = _job()
    session.add(job)
    session.commit()

    with pytest.raises(ValueError, match="job summary response invalid"):
        summarize_job(
            session,
            job,
            client=FakeSummaryClient({"responsibilities": {"bad": "shape"}}),
            settings=Settings(anthropic_api_key="test"),
        )


def test_summarize_job_coerces_string_list_fields(session):
    job = _job()
    session.add(job)
    session.commit()

    summarized = summarize_job(
        session,
        job,
        client=FakeSummaryClient(
            {
                "role_overview": "Senior AI role.",
                "responsibilities": "Lead AI delivery.",
                "requirements": "AI leadership.",
                "application_notes": "Applications are ongoing.",
                "noise_removed": "Cookie banner.",
            }
        ),
        settings=Settings(anthropic_api_key="test"),
    )

    assert summarized.job_summary["responsibilities"] == ["Lead AI delivery."]
    assert summarized.job_summary["application_notes"] == ["Applications are ongoing."]
