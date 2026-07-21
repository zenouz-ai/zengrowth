"""Read-only response models for the public observability surface.

Hard rule: nothing here may carry company, title, url, compensation, materials,
or any free-text user data. Only integers, bucket labels, and generic lifecycle
state names (which are non-identifying) cross the public boundary.
"""

from __future__ import annotations

from pydantic import BaseModel


class PublicSummaryOut(BaseModel):
    total_jobs: int
    applied: int
    interviewing: int
    offers: int
    suppressed: int


class PublicStateCountOut(BaseModel):
    state: str
    count: int


class PublicPipelineOut(BaseModel):
    states: list[PublicStateCountOut]
    suppressed: int


class PublicScoreBucketOut(BaseModel):
    label: str
    count: int


class PublicScoreHistogramOut(BaseModel):
    buckets: list[PublicScoreBucketOut]
    suppressed: int  # jobs folded out of small buckets for k-anonymity


class PublicVelocityPointOut(BaseModel):
    week: str  # ISO year-week, e.g. "2026-W24"
    transitions: int


class PublicVelocityOut(BaseModel):
    points: list[PublicVelocityPointOut]
    suppressed: int
