"""SQLModel definitions for the four Phase 1 entities.

Additional schemas from VISION §9 (Company, CVVersion, CoverLetter,
Interview, InterviewFeedback, EmailThread, LearningPack, AgentDecision,
BudgetRecord, Config) are documented in docs/SPEC.md and implemented in later
phases. GeneratedMaterial is the first concrete Phase 2 material-tracking
table.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Column, DateTime
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


class LifecycleState(StrEnum):
    discovered = "discovered"
    shortlisted = "shortlisted"
    prepared = "prepared"
    awaiting_approval = "awaiting_approval"
    approved = "approved"
    applied = "applied"
    interviewing = "interviewing"
    offer = "offer"
    rejected = "rejected"
    archived = "archived"


class JobSource(StrEnum):
    greenhouse = "greenhouse"
    lever = "lever"
    tavily = "tavily"
    manual = "manual"


class ApplicationState(StrEnum):
    draft = "draft"
    ready_for_review = "ready_for_review"
    submitted = "submitted"
    withdrawn = "withdrawn"


class OutcomeStage(StrEnum):
    """Furthest stage an application reached. Ordered for funnel analysis."""

    applied = "applied"
    acknowledged = "acknowledged"
    recruiter_screen = "recruiter_screen"
    interview = "interview"
    final_round = "final_round"
    offer = "offer"


class OutcomeResult(StrEnum):
    """Terminal result of an application (ground truth for calibration, TA-09)."""

    pending = "pending"
    no_response = "no_response"
    rejected = "rejected"
    withdrawn = "withdrawn"
    offer = "offer"
    accepted = "accepted"
    declined = "declined"


class ActorType(StrEnum):
    agent = "agent"
    human = "human"
    system = "system"


class InterviewRoundType(StrEnum):
    """Kind of interview round; maps onto ``OutcomeStage`` for funnel sync."""

    recruiter_screen = "recruiter_screen"
    hiring_manager = "hiring_manager"
    leadership_panel = "leadership_panel"
    technical = "technical"
    team = "team"
    final_round = "final_round"
    other = "other"


class InterviewFormat(StrEnum):
    phone = "phone"
    video = "video"
    onsite = "onsite"
    other = "other"


class InterviewStatus(StrEnum):
    scheduled = "scheduled"
    completed = "completed"
    cancelled = "cancelled"


class OfferStatus(StrEnum):
    """Where an offer stands in the operator's decision loop (OFF-01)."""

    received = "received"
    evaluating = "evaluating"
    negotiating = "negotiating"
    accepted = "accepted"
    declined = "declined"
    withdrawn = "withdrawn"


class MaterialAudience(StrEnum):
    """Who a generated material is for.

    ``employer`` documents (CV, cover letter, answers) are submitted claims about
    the operator and run the full truth-path grounding gates. ``internal``
    documents (prep packs, debriefs, email drafts) are operator-facing study
    aids: company/person facts carry web citations instead of evidence-bank
    grounding, and they are never exported as application materials.
    """

    employer = "employer"
    internal = "internal"


class SourceDocumentStatus(StrEnum):
    imported = "imported"
    duplicate = "duplicate"
    parsed = "parsed"
    extracted = "extracted"
    failed = "failed"


class SourceDocumentType(StrEnum):
    cv = "cv"
    project = "project"
    note = "note"
    document = "document"
    seed = "seed"


class ClaimVerificationState(StrEnum):
    draft = "draft"
    verified = "verified"
    rejected = "rejected"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Job(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    company: str = Field(index=True)
    title: str = Field(index=True)
    location: str | None = None
    hybrid_policy: str | None = None
    compensation: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    seniority: str | None = None
    application_url: str | None = None
    posting_date: date | None = Field(default=None, index=True)
    description: str | None = None
    job_summary: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    summary_updated_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    source: JobSource = Field(index=True)
    dedup_hash: str = Field(unique=True, index=True)
    lifecycle_state: LifecycleState = Field(default=LifecycleState.discovered, index=True)
    fit_score: float | None = Field(default=None, index=True)
    expected_value: float | None = Field(default=None, index=True)
    score_rationale: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    # Outcome tracking (TA-01): ground truth for the future scoring calibration loop.
    applied_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    first_response_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    outcome_stage: OutcomeStage | None = Field(default=None, index=True)
    outcome_result: OutcomeResult | None = Field(default=None, index=True)
    rejection_stage: OutcomeStage | None = Field(default=None)
    outcome_notes: str | None = None
    outcome_updated_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class Application(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", index=True)
    state: ApplicationState = Field(default=ApplicationState.draft, index=True)
    materials_path: str | None = None
    submitted_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    notes: str | None = None
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class Interview(SQLModel, table=True):
    """One interview round in a job's post-application timeline (INT-01).

    ``scheduled_at`` / ``occurred_at`` are operator-settable so a historical
    journey can be recorded after the fact (backdating applies to these domain
    dates only — audit rows keep their true timestamps). ``transcript`` holds
    pasted meeting notes/transcript text; it is deliberately NOT routed through
    knowledge extraction so interviewer statements never leak into the
    employer-facing evidence bank unreviewed.
    """

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", index=True)
    round_type: InterviewRoundType = Field(default=InterviewRoundType.other, index=True)
    title: str | None = None
    format: InterviewFormat = Field(default=InterviewFormat.video)
    status: InterviewStatus = Field(default=InterviewStatus.scheduled, index=True)
    scheduled_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    occurred_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # [{"name": "...", "role": "..."}] — feeds the interviewer research pack.
    participants: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON))
    notes: str | None = None
    transcript: str | None = None
    transcript_updated_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class JobOffer(SQLModel, table=True):
    """A received job offer and its terms (OFF-01).

    ``received_at`` / ``deadline_at`` are operator-settable so a historical
    journey can be recorded after the fact (domain dates backdate; audit rows
    never do). ``offer_text`` holds the pasted offer letter/email verbatim —
    it feeds the evaluation prompt but is never routed through knowledge
    extraction, so employer statements stay out of the evidence bank.
    Multiple rows per job capture revised offers during a negotiation.
    """

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", index=True)
    status: OfferStatus = Field(default=OfferStatus.received, index=True)
    base_salary: float | None = None
    currency: str = Field(default="GBP")
    bonus: str | None = None
    equity: str | None = None
    pension: str | None = None
    holiday_days: int | None = None
    benefits: str | None = None
    other_terms: str | None = None
    start_date: date | None = None
    received_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    deadline_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    offer_text: str | None = None
    notes: str | None = None
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class GeneratedMaterial(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", index=True)
    # Interview-scoped artifacts (prep packs, debriefs) link to their round;
    # job-level materials (CV, letter, company briefing) leave this null.
    interview_id: int | None = Field(default=None, foreign_key="interview.id", index=True)
    material_type: str = Field(index=True)
    audience: MaterialAudience = Field(default=MaterialAudience.employer, index=True)
    # Operator-settable display date for backdated/imported artifacts; falls
    # back to created_at when unset.
    effective_date: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    title: str
    question: str | None = None
    word_limit: int | None = None
    tex_path: str | None = None
    pdf_path: str | None = None
    markdown_path: str | None = None
    evidence_ids: list[str] | None = Field(default=None, sa_column=Column(JSON))
    draft_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    version: int = Field(default=1, index=True)
    is_final: bool = Field(default=False, index=True)
    supersedes_id: int | None = Field(default=None, foreign_key="generatedmaterial.id")
    page_count: int | None = None
    page_fill: float | None = None
    status: str = Field(default="created", index=True)
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


class SourceDocument(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    filename: str = Field(index=True)
    original_path: str
    processed_path: str | None = None
    content_hash: str = Field(unique=True, index=True)
    mime_type: str | None = None
    source_type: SourceDocumentType = Field(default=SourceDocumentType.document, index=True)
    status: SourceDocumentStatus = Field(default=SourceDocumentStatus.imported, index=True)
    error: str | None = None
    # Human-facing label; defaults to filename when unset.
    title: str | None = None
    # Short description shown on graph nodes (derived at ingest, no LLM by default).
    summary: str | None = None
    # Version lineage: documents sharing a lineage_id are revisions of one another.
    lineage_id: str | None = Field(default=None, index=True)
    version: int = Field(default=1, index=True)
    supersedes_id: int | None = Field(default=None, foreign_key="sourcedocument.id")
    is_current: bool = Field(default=True, index=True)
    # When set (e.g. "cv_style"), the is_current row with this role is the
    # active template/style consumed by material generation.
    template_role: str | None = Field(default=None, index=True)
    meta: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class SourceChunk(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    source_document_id: int = Field(foreign_key="sourcedocument.id", index=True)
    chunk_index: int = Field(index=True)
    text: str
    section_path: str | None = None
    page_start: int | None = None
    line_start: int | None = None
    token_estimate: int = 0
    embedding: list[float] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


class EvidenceClaim(SQLModel, table=True):
    id: str = Field(primary_key=True)
    source_document_id: int = Field(foreign_key="sourcedocument.id", index=True)
    source_chunk_id: int | None = Field(default=None, foreign_key="sourcechunk.id", index=True)
    claim_text: str
    category: str = Field(index=True)
    confidence: float = Field(default=0.0, index=True)
    verification_state: ClaimVerificationState = Field(
        default=ClaimVerificationState.draft,
        index=True,
    )
    source_span: str | None = None
    tags: list[str] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class KnowledgeEntity(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    normalized_name: str = Field(index=True)
    entity_type: str = Field(index=True)
    source_document_id: int | None = Field(default=None, foreign_key="sourcedocument.id", index=True)
    source_claim_id: str | None = Field(default=None, foreign_key="evidenceclaim.id", index=True)
    meta: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


class KnowledgeRelationship(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    source_entity_id: int | None = Field(default=None, foreign_key="knowledgeentity.id", index=True)
    target_entity_id: int | None = Field(default=None, foreign_key="knowledgeentity.id", index=True)
    source_claim_id: str | None = Field(default=None, foreign_key="evidenceclaim.id", index=True)
    relationship_type: str = Field(index=True)
    confidence: float = Field(default=0.0)
    meta: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


class ClaimFacet(SQLModel, table=True):
    """KG-02: controlled-vocabulary facet assigned to an evidence claim.

    Derived metadata over already-extracted claims (the truth path is
    untouched); rows are replaced wholesale on re-assignment, so uniqueness of
    ``(claim_id, facet, value)`` is enforced by the assignment code.
    """

    id: int | None = Field(default=None, primary_key=True)
    claim_id: str = Field(foreign_key="evidenceclaim.id", index=True)
    facet: str = Field(index=True)
    value: str = Field(index=True)
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


class JobFacet(SQLModel, table=True):
    """KG-02: demand facet extracted from a scored job's JD summary."""

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", index=True)
    facet: str = Field(index=True)
    value: str = Field(index=True)
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


class ClaimDocumentLink(SQLModel, table=True):
    """Many-to-many: which source documents cite a canonical evidence claim."""

    id: int | None = Field(default=None, primary_key=True)
    claim_id: str = Field(foreign_key="evidenceclaim.id", index=True)
    source_document_id: int = Field(foreign_key="sourcedocument.id", index=True)
    source_chunk_id: int | None = Field(default=None, foreign_key="sourcechunk.id", index=True)
    source_span: str | None = None
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


class EntityDocumentLink(SQLModel, table=True):
    """Many-to-many: which source documents mention a canonical entity."""

    id: int | None = Field(default=None, primary_key=True)
    entity_id: int = Field(foreign_key="knowledgeentity.id", index=True)
    source_document_id: int = Field(foreign_key="sourcedocument.id", index=True)
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


class AuditLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    actor: ActorType = Field(index=True)
    action: str = Field(index=True)
    entity_type: str | None = Field(default=None, index=True)
    entity_id: str | None = Field(default=None, index=True)
    detail: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class LlmOperation(StrEnum):
    chat = "chat"
    embedding = "embedding"


class LlmCallStatus(StrEnum):
    ok = "ok"
    error = "error"


class LlmCall(SQLModel, table=True):
    """Per-LLM-call telemetry (OpenTelemetry gen_ai.* aligned)."""

    id: int | None = Field(default=None, primary_key=True)
    trace_id: str | None = Field(default=None, index=True)
    span_id: str | None = Field(default=None, index=True)
    parent_span_id: str | None = Field(default=None, index=True)
    timestamp: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    operation: LlmOperation = Field(index=True)
    provider: str = Field(index=True)
    request_model: str = Field(index=True)
    response_model: str | None = Field(default=None, index=True)
    operation_name: str = Field(index=True)
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    cache_read_tokens: int = Field(default=0)
    cache_creation_tokens: int = Field(default=0)
    latency_ms: int = Field(default=0, index=True)
    cost_usd: float = Field(default=0.0, index=True)
    status: LlmCallStatus = Field(default=LlmCallStatus.ok, index=True)
    error_type: str | None = Field(default=None, index=True)
    finish_reason: str | None = None
    entity_type: str | None = Field(default=None, index=True)
    entity_id: str | None = Field(default=None, index=True)
    detail: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class PipelineRunStatus(StrEnum):
    running = "running"
    completed = "completed"
    failed = "failed"


class PipelineRun(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    trace_id: str = Field(unique=True, index=True)
    pipeline_type: str = Field(index=True)
    started_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    finished_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    status: PipelineRunStatus = Field(default=PipelineRunStatus.running, index=True)
    total_cost_usd: float = Field(default=0.0)
    total_tokens: int = Field(default=0)
    step_count: int = Field(default=0)
    entity_type: str | None = Field(default=None, index=True)
    entity_id: str | None = Field(default=None, index=True)
    detail: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class PipelineStep(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    trace_id: str = Field(index=True)
    span_id: str = Field(index=True)
    parent_span_id: str | None = Field(default=None, index=True)
    step_name: str = Field(index=True)
    step_type: str = Field(index=True)  # llm | tool | db | decision
    decision: str | None = Field(default=None, index=True)
    started_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    duration_ms: int = Field(default=0)
    status: str = Field(default="ok", index=True)
    detail: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class DiscoverySearch(SQLModel, table=True):
    """Persisted Tavily discovery search for operator history."""

    id: int | None = Field(default=None, primary_key=True)
    query: str = Field(index=True)
    scoped_query: str | None = None
    result_count: int = Field(default=0)
    results: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


class DataSourceKind(StrEnum):
    ats = "ats"
    search = "search"
    llm = "llm"
    embedding = "embedding"
    graph = "graph"
    file = "file"


class DataSourceHealth(StrEnum):
    healthy = "healthy"
    degraded = "degraded"
    unavailable = "unavailable"
    unknown = "unknown"


class DataSource(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    kind: DataSourceKind = Field(index=True)
    config: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    enabled: bool = Field(default=True, index=True)
    health_status: DataSourceHealth = Field(default=DataSourceHealth.unknown, index=True)
    last_used_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    record_count: int = Field(default=0)
    pii_flag: bool = Field(default=False, index=True)
    retention_days: int | None = None
    notes: str | None = None
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class PerformanceSnapshot(SQLModel, table=True):
    """Daily rollup of per-operation performance scorecards."""

    id: int | None = Field(default=None, primary_key=True)
    snapshot_date: date = Field(index=True)
    operation_name: str = Field(index=True)
    call_count: int = Field(default=0)
    success_rate: float = Field(default=0.0)
    latency_p50_ms: float = Field(default=0.0)
    latency_p95_ms: float = Field(default=0.0)
    avg_cost_usd: float = Field(default=0.0)
    quality_score: float | None = Field(default=None)
    detail: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class SchedulerLock(SQLModel, table=True):
    """Cross-process advisory lock + last-run bookkeeping for scheduled jobs (EA-04).

    One row per named job. ``acquire_lock`` flips ``locked`` true via an atomic
    conditional UPDATE so concurrent cron fires, manual triggers, or multiple API
    replicas can't run the same ingest at once (no double-spend). ``expires_at``
    is a safety valve: a crashed holder's lock self-heals after the TTL.
    """

    name: str = Field(primary_key=True)
    locked: bool = Field(default=False)
    holder: str | None = Field(default=None)
    acquired_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    expires_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class AppSecret(SQLModel, table=True):
    """Operator-managed secrets (e.g. the LLM API key) set from the dashboard.

    Stored encrypted-at-rest (encrypt-then-MAC, keyed by a local ``data/.keyring``
    file — see ``secrets_store``) so the key survives restarts without an env var.
    Environment variables still take precedence; this is the in-app fallback that
    lets a first-time user reach value without editing ``.env`` (PS-P1).
    """

    name: str = Field(primary_key=True)
    ciphertext: str
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
