"""Schemas for the knowledge ingestion and review surface."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from ..models import ClaimVerificationState, SourceDocumentStatus, SourceDocumentType


class SourceChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chunk_index: int
    text: str
    section_path: str | None
    page_start: int | None
    line_start: int | None
    token_estimate: int


class EvidenceClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_document_id: int
    source_chunk_id: int | None
    claim_text: str
    category: str
    confidence: float
    verification_state: ClaimVerificationState
    source_span: str | None
    tags: list[str] | None
    created_at: datetime
    updated_at: datetime


class KnowledgeEntityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    normalized_name: str
    entity_type: str


class SourceDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    title: str | None
    summary: str | None
    original_path: str
    processed_path: str | None
    content_hash: str
    mime_type: str | None
    source_type: SourceDocumentType
    status: SourceDocumentStatus
    error: str | None
    lineage_id: str | None
    version: int
    supersedes_id: int | None
    is_current: bool
    template_role: str | None
    meta: dict | None
    created_at: datetime
    updated_at: datetime


class SourceDocumentDetailOut(SourceDocumentOut):
    chunks: list[SourceChunkOut]
    claims: list[EvidenceClaimOut]
    entities: list[KnowledgeEntityOut]
    versions: list[SourceDocumentOut] = []


class IngestResultOut(BaseModel):
    source_document: SourceDocumentOut
    created: bool
    chunks: int
    claims: int
    verified_claims: int


class InboxImportOut(BaseModel):
    results: list[IngestResultOut]


class ClaimUpdate(BaseModel):
    claim_text: str | None = None
    category: str | None = None
    confidence: float | None = None
    source_span: str | None = None
    tags: list[str] | None = None


class PasteIngestRequest(BaseModel):
    text: str
    filename: str = "pasted"
    format: str = "txt"
    source_type: SourceDocumentType = SourceDocumentType.document
    title: str | None = None
    lineage_id: str | None = None
    supersedes_id: int | None = None
    promote_template: bool = False


class GraphNodeOut(BaseModel):
    id: str
    kind: str  # source | claim | entity
    label: str
    detail: str | None = None
    group: str | None = None
    ref_id: str | None = None
    meta: dict = {}


class GraphEdgeOut(BaseModel):
    id: str
    source: str
    target: str
    kind: str  # supersedes | has_claim | mentions | related_to


class KnowledgeGraphOut(BaseModel):
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]


class VersionDiffLine(BaseModel):
    op: str  # context | add | remove | gap
    text: str


class VersionDiffOut(BaseModel):
    base_id: int
    base_version: int
    target_id: int
    target_version: int
    added: int
    removed: int
    lines: list[VersionDiffLine]


class DiffSummaryRequest(BaseModel):
    against: int


class DiffSummaryOut(BaseModel):
    summary: str


class CoverageMonthlyOut(BaseModel):
    month: str  # YYYY-MM
    claims: int


class CoverageValueOut(BaseModel):
    value: str
    verified_claims: int
    draft_claims: int
    claim_ids: list[str]
    demand_jobs: int
    job_ids: list[int]
    gap: bool
    monthly: list[CoverageMonthlyOut]


class CoverageFacetOut(BaseModel):
    facet: str
    values: list[CoverageValueOut]
    vocabulary_size: int


class CoverageJobOut(BaseModel):
    id: int
    company: str
    title: str


class CoverageTotalsOut(BaseModel):
    claims: int
    faceted_claims: int
    unfaceted_claims: int
    scored_jobs: int
    faceted_jobs: int
    unfaceted_jobs: int


class CoverageOut(BaseModel):
    facets: list[CoverageFacetOut]
    jobs: list[CoverageJobOut]
    totals: CoverageTotalsOut


class FacetBackfillOut(BaseModel):
    documents_faceted: int
    documents_skipped: int
    jobs_faceted: int
    jobs_skipped: int
    facet_rows: int
    rejected: list[str]
