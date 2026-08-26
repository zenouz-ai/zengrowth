from datetime import date
from typing import Any

from sqlmodel import select

from zengrowth.config import Settings
from zengrowth.ingestion import precheck
from zengrowth.ingestion.dedup import dedup_hash
from zengrowth.ingestion.precheck import (
    looks_plausibly_relevant,
    precheck_job,
    relevance_signal,
)
from zengrowth.models import AuditLog, Job, JobSource, LifecycleState


class FakeSummaryClient:
    def summarize(self, system: str, user: str, model: str) -> dict[str, Any]:
        return {
            "role_overview": "Senior AI leadership role.",
            "responsibilities": ["Lead AI strategy."],
            "requirements": ["AI leadership."],
        }


class FakeScorer:
    def __init__(self, fit_score: int = 74) -> None:
        self.fit_score = fit_score

    def score(self, system: str, user: str, model: str) -> dict[str, Any]:
        return {
            "role_relevance": {"score": 80, "reason": "Relevant."},
            "ai_technical_alignment": {"score": 70, "reason": "AI role."},
            "leadership_alignment": {"score": 70, "reason": "Leadership."},
            "compensation_fit": {"score": 60, "reason": "Unknown."},
            "domain_fit": {"score": 70, "reason": "Good domain."},
            "strategic_career_value": {"score": 72, "reason": "Strategic."},
            "hybrid_location_fit": {"score": 80, "reason": "London."},
            "application_effort": {"score": 3, "reason": "Standard."},
            "success_probability": {"score": 0.4, "reason": "Credible."},
            "match_quality": {"score": self.fit_score, "reason": "Composite."},
            "summary": "Good fit.",
        }


def _job(title: str, description: str = "Build and run web services for the finance team.") -> Job:
    return Job(
        company="Acme",
        title=title,
        posting_date=date(2026, 6, 1),
        description=description,
        source=JobSource.manual,
        dedup_hash=dedup_hash("Acme", title, date(2026, 6, 1)),
    )


def test_cheap_precheck_rejects_obvious_non_target_role():
    assert not looks_plausibly_relevant(_job("Technical Support Specialist - AI"))
    assert not looks_plausibly_relevant(_job("Software Engineer, Full Stack"))
    assert not looks_plausibly_relevant(_job("Director, Business Systems"))
    assert not looks_plausibly_relevant(_job("Business Development Manager, Agentic Commerce"))
    assert not looks_plausibly_relevant(_job("Integrated Campaigns Manager, Startups and AI"))
    assert looks_plausibly_relevant(_job("Director of AI Strategy"))


def test_precheck_recovers_oddly_titled_senior_roles():
    # Senior AI roles with flat/unusual titles that the old conjunctive,
    # engineer-excluding title filter wrongly archived (TA-02).
    assert looks_plausibly_relevant(_job("Founding ML Engineer"))
    assert looks_plausibly_relevant(_job("Distinguished Engineer, Applied AI"))
    assert looks_plausibly_relevant(_job("Senior Software Engineer, ML Platform"))
    # Title carries seniority but not the AI signal; the description supplies it.
    assert looks_plausibly_relevant(
        _job("Member of Technical Staff", "We train and deploy large language models and ML systems.")
    )


def test_relevance_signal_reports_match_source():
    assert relevance_signal(_job("Director of AI Strategy")).reason == "title_match"
    desc = "We train and deploy large language models and ML systems."
    assert relevance_signal(_job("Member of Technical Staff", desc)).reason == "description_assisted"
    assert relevance_signal(_job("Sales Director, AI Products")).reason == "hard_excluded"
    assert relevance_signal(_job("Product Designer")).reason == "no_signal"


def test_short_tokens_do_not_match_substrings():
    # "ai"/"ml" must not fire inside words like "maintain" or "html".
    assert not looks_plausibly_relevant(
        _job("Lead Platform Engineer", "Maintain HTML services and remain available on call.")
    )


def test_precheck_archives_obvious_non_target_without_llm(session):
    job = _job("Technical Support Specialist - AI")
    session.add(job)
    session.commit()
    session.refresh(job)

    ready = precheck_job(
        session,
        job,
        settings=Settings(anthropic_api_key="test", scoring_model="claude-test"),
    )

    assert not ready
    assert job.lifecycle_state == LifecycleState.archived
    audit = session.exec(select(AuditLog).where(AuditLog.action == "precheck_archive_job")).first()
    assert audit is not None
    assert audit.detail["reason"] == "cheap_filter_not_target_role"


def test_precheck_summarizes_scores_and_keeps_relevant_job(session, monkeypatch):
    job = _job("Director of AI Strategy")
    session.add(job)
    session.commit()
    session.refresh(job)

    def fake_summarize_job(session, job, settings):
        from zengrowth.ingestion.job_summarizer import summarize_job

        return summarize_job(session, job, client=FakeSummaryClient(), settings=settings)

    def fake_score_job(session, job, settings):
        from zengrowth.scoring.scorer import score_job

        return score_job(session, job, client=FakeScorer(), settings=settings)

    monkeypatch.setattr(precheck, "summarize_job", fake_summarize_job)
    monkeypatch.setattr(precheck, "score_job", fake_score_job)

    ready = precheck_job(
        session,
        job,
        settings=Settings(anthropic_api_key="test", scoring_model="claude-test"),
    )

    assert ready
    # TP-08: passing precheck is a state transition, not just a predicate.
    assert job.lifecycle_state == LifecycleState.shortlisted
    assert job.summary_updated_at is not None
    assert job.fit_score == 74


def test_precheck_batch_does_not_reselect_passed_jobs(session, monkeypatch):
    """TP-08 regression: a job that passed stays out of the next nightly batch."""
    job = _job("Director of AI Strategy")
    job.source = JobSource.greenhouse
    session.add(job)
    session.commit()
    session.refresh(job)

    calls = {"summarize": 0, "score": 0}

    def fake_summarize_job(session, job, settings):
        from zengrowth.ingestion.job_summarizer import summarize_job

        calls["summarize"] += 1
        return summarize_job(session, job, client=FakeSummaryClient(), settings=settings)

    def fake_score_job(session, job, settings):
        from zengrowth.scoring.scorer import score_job

        calls["score"] += 1
        return score_job(session, job, client=FakeScorer(), settings=settings)

    monkeypatch.setattr(precheck, "summarize_job", fake_summarize_job)
    monkeypatch.setattr(precheck, "score_job", fake_score_job)
    settings = Settings(anthropic_api_key="test", scoring_model="claude-test")

    first = precheck.precheck_jobs(session, settings=settings)
    assert first.prechecked == 1
    assert calls == {"summarize": 1, "score": 1}
    session.refresh(job)
    assert job.lifecycle_state == LifecycleState.shortlisted

    second = precheck.precheck_jobs(session, settings=settings)
    assert second.prechecked == 0
    assert calls == {"summarize": 1, "score": 1}
