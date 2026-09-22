"""Curated pipeline visibility — which jobs appear on the operator board.

Auto-ingested roles must meet ``pipeline_min_fit_score`` so ATS noise stays off
the board. Jobs the operator pasted manually always pass the fit gate once they
have a clean summary and score — the operator decides whether to apply.
"""

from __future__ import annotations

from ..config import Settings, get_settings
from ..models import Job, JobSource, LifecycleState


def is_curated_pipeline_job(job: Job, *, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if job.lifecycle_state == LifecycleState.archived:
        return False
    if job.summary_updated_at is None or job.job_summary is None:
        return False
    if job.fit_score is None or job.expected_value is None:
        return False
    if job.source == JobSource.manual:
        return True
    return job.fit_score >= settings.pipeline_min_fit_score
