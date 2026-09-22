"""Tests for curated pipeline visibility."""

from __future__ import annotations

from datetime import UTC, datetime

from zengrowth.jobs.curation import is_curated_pipeline_job
from zengrowth.models import Job, JobSource, LifecycleState


def _job(**kwargs) -> Job:
    base = dict(
        company="Co",
        title="AI Lead",
        source=JobSource.greenhouse,
        dedup_hash="x",
        job_summary={"role_overview": "ok"},
        summary_updated_at=datetime(2026, 6, 1, tzinfo=UTC),
        fit_score=72.0,
        expected_value=500.0,
    )
    base.update(kwargs)
    return Job(**base)


def test_manual_job_passes_below_fit_threshold():
    job = _job(source=JobSource.manual, fit_score=40.0)
    assert is_curated_pipeline_job(job) is True


def test_auto_ingested_job_blocked_below_fit_threshold():
    job = _job(source=JobSource.greenhouse, fit_score=40.0)
    assert is_curated_pipeline_job(job) is False


def test_archived_never_curated():
    job = _job(source=JobSource.manual, lifecycle_state=LifecycleState.archived)
    assert is_curated_pipeline_job(job) is False
