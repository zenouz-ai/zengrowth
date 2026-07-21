"""Pydantic request/response models for the FastAPI surface."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

from ..interviews.offer_extractor import ExtractedOfferFields
from ..models import (
    InterviewFormat,
    InterviewRoundType,
    InterviewStatus,
    JobSource,
    LifecycleState,
    MaterialAudience,
    OfferStatus,
    OutcomeResult,
    OutcomeStage,
)


def page_fit_status(material_type: str, page_count: int | None, page_fill: float | None) -> str:
    """Classify CV page fit (delegates to the shared materials classifier)."""
    from ..materials.latex import classify_cv_fit

    return classify_cv_fit(material_type, page_count, page_fill)


def material_tailoring_from_draft(
    draft_json: dict[str, Any] | None,
    *,
    material_type: str | None = None,
) -> dict[str, Any] | None:
    if not draft_json:
        return None
    tailoring = draft_json.get("tailoring")
    if not isinstance(tailoring, dict):
        return None
    if material_type != "cv":
        return tailoring
    baseline = draft_json.get("template_baseline")
    if not isinstance(baseline, dict):
        from ..materials.generator import _parse_cv_template, _read_cv_template

        baseline = _parse_cv_template(_read_cv_template())
    tailored = {
        "summary": draft_json.get("summary"),
        "capabilities": draft_json.get("capabilities"),
        "experience": draft_json.get("experience"),
    }
    from ..materials.cv_diff import summarize_cv_changes

    enriched = dict(tailoring)
    enriched["change_summary"] = summarize_cv_changes(baseline, tailored)
    return enriched


class JobCreate(BaseModel):
    company: str = Field(min_length=1)
    title: str = Field(min_length=1)
    location: str | None = None
    hybrid_policy: str | None = None
    compensation: dict[str, Any] | None = None
    seniority: str | None = None
    application_url: str | None = None
    posting_date: date | None = None
    description: str | None = None
    source: JobSource = JobSource.manual


class JobExtractRequest(BaseModel):
    raw_text: str = Field(min_length=1)
    application_url: str | None = None


class JobExtractResponse(BaseModel):
    company: str | None = None
    title: str | None = None
    location: str | None = None
    hybrid_policy: str | None = None
    compensation: dict[str, Any] | None = None
    seniority: str | None = None
    application_url: str | None = None
    posting_date: date | None = None
    description: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    confidence_notes: str | None = None


class JobPatch(BaseModel):
    application_url: str | None = None


class JobPurgeRequest(BaseModel):
    lifecycle_state: LifecycleState = LifecycleState.archived


class JobPurgeResponse(BaseModel):
    deleted: int
    lifecycle_state: LifecycleState


class JobOut(BaseModel):
    id: int
    company: str
    title: str
    location: str | None
    hybrid_policy: str | None
    compensation: dict[str, Any] | None
    seniority: str | None
    application_url: str | None
    posting_date: date | None
    description: str | None
    job_summary: dict[str, Any] | None
    summary_updated_at: datetime | None
    source: JobSource
    lifecycle_state: LifecycleState
    fit_score: float | None
    expected_value: float | None
    score_rationale: dict[str, Any] | None
    applied_at: datetime | None
    first_response_at: datetime | None
    outcome_stage: OutcomeStage | None
    outcome_result: OutcomeResult | None
    rejection_stage: OutcomeStage | None
    outcome_notes: str | None
    outcome_updated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class StateChange(BaseModel):
    state: LifecycleState
    note: str | None = None


class OutcomeUpdate(BaseModel):
    """Partial outcome update — only the fields supplied are applied (TA-01)."""

    applied_at: datetime | None = None
    first_response_at: datetime | None = None
    outcome_stage: OutcomeStage | None = None
    outcome_result: OutcomeResult | None = None
    rejection_stage: OutcomeStage | None = None
    notes: str | None = None
    # Keep the coarse lifecycle_state in sync with the detailed outcome fields.
    sync_lifecycle: bool = True


class OutcomeFunnel(BaseModel):
    """Aggregate application funnel — seeds the calibration loop (TA-09)."""

    total_applied: int
    responded: int
    interviewed: int
    offers: int
    rejected: int
    response_rate: float | None
    interview_rate: float | None
    offer_rate: float | None
    # Round-level analytics from the interview timeline (INT-04).
    rounds_recorded: int = 0
    avg_days_between_rounds: float | None = None


class MaterialAnswerRequest(BaseModel):
    question: str = Field(min_length=1)
    word_limit: int | None = Field(default=None, ge=1)
    instructions: str | None = None


class InterviewCreate(BaseModel):
    round_type: InterviewRoundType = InterviewRoundType.other
    title: str | None = None
    format: InterviewFormat = InterviewFormat.video
    status: InterviewStatus = InterviewStatus.scheduled
    scheduled_at: datetime | None = None
    occurred_at: datetime | None = None
    participants: list[dict[str, Any]] | None = None
    notes: str | None = None
    transcript: str | None = None
    # Bump the job's coarse outcome_stage/lifecycle to match this round.
    sync_outcome: bool = True


class InterviewPatch(BaseModel):
    """Partial update — only supplied fields are applied."""

    round_type: InterviewRoundType | None = None
    title: str | None = None
    format: InterviewFormat | None = None
    status: InterviewStatus | None = None
    scheduled_at: datetime | None = None
    occurred_at: datetime | None = None
    participants: list[dict[str, Any]] | None = None
    notes: str | None = None
    transcript: str | None = None
    sync_outcome: bool = True


class InterviewTranscriptIn(BaseModel):
    transcript: str = Field(min_length=1)


class InterviewOut(BaseModel):
    id: int
    job_id: int
    round_type: InterviewRoundType
    title: str | None
    format: InterviewFormat
    status: InterviewStatus
    scheduled_at: datetime | None
    occurred_at: datetime | None
    participants: list[dict[str, Any]] | None
    notes: str | None
    has_transcript: bool = False
    can_debrief: bool = False
    transcript_updated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class InterviewDetailOut(InterviewOut):
    transcript: str | None = None


class MaterialPackRequest(BaseModel):
    """Generate an internal prep pack (INT-02)."""

    pack_type: str = Field(min_length=1)
    interview_id: int | None = None
    enhance: bool = False
    source_material_id: int | None = None


class SimPromptRequest(BaseModel):
    """Compose a voice-interviewer simulation prompt (INT-05, no LLM call)."""

    interview_id: int | None = None


class PromoteLearningRequest(BaseModel):
    """Queue a debrief insight as a draft evidence claim (INT-04)."""

    claim_text: str = Field(min_length=1)


class EmailDraftRequest(BaseModel):
    """Draft a reply/follow-up email (INT-03). ZenGrowth never sends email."""

    instructions: str | None = None
    inbound_email: str | None = None
    interview_id: int | None = None


class OfferCreate(BaseModel):
    """Record a received offer (OFF-01). Dates are backdatable."""

    status: OfferStatus = OfferStatus.received
    base_salary: float | None = Field(default=None, ge=0)
    currency: str = "GBP"
    bonus: str | None = None
    equity: str | None = None
    pension: str | None = None
    holiday_days: int | None = Field(default=None, ge=0)
    benefits: str | None = None
    other_terms: str | None = None
    start_date: date | None = None
    received_at: datetime | None = None
    deadline_at: datetime | None = None
    offer_text: str | None = None
    notes: str | None = None
    # Move the job's outcome/lifecycle to the offer stage.
    sync_outcome: bool = True


class OfferPatch(BaseModel):
    """Partial update — only supplied fields are applied."""

    status: OfferStatus | None = None
    base_salary: float | None = Field(default=None, ge=0)
    currency: str | None = None
    bonus: str | None = None
    equity: str | None = None
    pension: str | None = None
    holiday_days: int | None = Field(default=None, ge=0)
    benefits: str | None = None
    other_terms: str | None = None
    start_date: date | None = None
    received_at: datetime | None = None
    deadline_at: datetime | None = None
    offer_text: str | None = None
    notes: str | None = None
    sync_outcome: bool = True


class OfferOut(BaseModel):
    id: int
    job_id: int
    status: OfferStatus
    base_salary: float | None
    currency: str
    bonus: str | None
    equity: str | None
    pension: str | None
    holiday_days: int | None
    benefits: str | None
    other_terms: str | None
    start_date: date | None
    received_at: datetime | None
    deadline_at: datetime | None
    offer_text: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class OfferExtractRequest(BaseModel):
    """Paste-to-fill for offers (OFF-04): extract terms from an offer email."""

    raw_text: str = Field(min_length=1)


class OfferExtractResponse(ExtractedOfferFields):
    """API mirror of the extractor output — subclassed so a field added to the
    extractor can never silently vanish at the API boundary."""


class DeparturePackRequest(BaseModel):
    """Context for the leave-well pack (OFF-05). Everything is optional —
    unknown terms are flagged as "check your contract" in the document."""

    current_company: str | None = None
    current_role: str | None = None
    manager_name: str | None = None
    notice_period: str | None = None
    last_day_target: date | None = None
    responsibilities: str | None = None
    achievements: str | None = None
    notes: str | None = None


class OfferResponseDraftRequest(BaseModel):
    """Draft an acceptance / counter-offer / clarification email (OFF-01).

    ZenGrowth never sends email — the draft is an internal material."""

    response_type: Literal["accept", "counter", "clarify"]
    instructions: str | None = None


class MaterialImportRequest(BaseModel):
    """File an existing document (e.g. a Claude-chat prep pack) as a backdated
    internal artifact (INT-01)."""

    material_type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    interview_id: int | None = None
    effective_date: datetime | None = None


class GeneratedMaterialOut(BaseModel):
    id: int
    job_id: int
    interview_id: int | None = None
    material_type: str
    audience: MaterialAudience = MaterialAudience.employer
    effective_date: datetime | None = None
    title: str
    question: str | None
    word_limit: int | None
    tex_path: str | None
    pdf_path: str | None
    markdown_path: str | None
    evidence_ids: list[str] | None
    version: int
    is_final: bool
    supersedes_id: int | None
    page_count: int | None = None
    page_fill: float | None = None
    status: str
    created_at: datetime
    tailoring: dict[str, Any] | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def page_fit(self) -> str:
        return page_fit_status(self.material_type, self.page_count, self.page_fill)


class GeneratedMaterialDetailOut(GeneratedMaterialOut):
    draft_json: dict[str, Any] | None
    preview_mode: str
    pdf_available: bool
    tex_available: bool
    markdown_available: bool
    fallback_content: str | None = None
    tex_content: str | None = None


class MaterialReviseIn(BaseModel):
    mode: str = "structured"
    draft: dict[str, Any] | None = None
    tex: str | None = None
    markdown_body: str | None = None


class IngestionSummary(BaseModel):
    added: int
    skipped_duplicate: int
    skipped_stale: int
    prechecked: int = 0
    archived: int = 0
    failed_precheck: int = 0
    succeeded_boards: list[str]
    failed_boards: list[str]
    skipped_locked: bool = False


class IngestionStartedOut(BaseModel):
    """Acknowledgement that a background ingest was scheduled (runs async)."""

    status: str = "started"


class IngestionConfigOut(BaseModel):
    ats_boards: list[str]
    max_posting_age_days: int
    ingestion_hour: int
    tavily_configured: bool


class IngestionHealthOut(BaseModel):
    """Operator-facing ingestion health for the dashboard staleness banner (SEC-01)."""

    last_completed_at: datetime | None = None
    age_seconds: float | None = None
    stale: bool = False
    never_run: bool = True
    degraded: bool = False
    added: int | None = None
    zero_row_boards: list[str] = Field(default_factory=list)
    failed_boards: list[str] = Field(default_factory=list)


class HealthReadyOut(BaseModel):
    """Minimal readiness probe for an external monitor (SEC-09).

    Intentionally omits board names/counts — those stay behind operator auth on
    ``/api/ingestion/health``; the public probe exposes only status booleans.
    """

    status: str
    db_writable: bool
    last_ingest_age_seconds: float | None = None
    ingest_stale: bool = False
    ingest_never_run: bool = True


class ScoreRequest(BaseModel):
    job_id: int


class DiscoveryQuery(BaseModel):
    query: str
    max_results: int = 10


class DiscoveryHit(BaseModel):
    title: str
    url: str
    snippet: str | None = None
    score: float | None = None


class DiscoverySearchOut(BaseModel):
    id: int
    query: str
    scoped_query: str | None = None
    result_count: int
    results: list[DiscoveryHit]
    created_at: datetime
