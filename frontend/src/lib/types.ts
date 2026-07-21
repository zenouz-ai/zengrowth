// Mirrors the backend Pydantic response models (src/zengrowth/api/schemas.py).

export const LIFECYCLE_STATES = [
  'discovered',
  'shortlisted',
  'prepared',
  'awaiting_approval',
  'approved',
  'applied',
  'interviewing',
  'offer',
  'rejected',
  'archived',
] as const

export type LifecycleState = (typeof LIFECYCLE_STATES)[number]

export const OUTCOME_STAGES = [
  'applied',
  'acknowledged',
  'recruiter_screen',
  'interview',
  'final_round',
  'offer',
] as const

export type OutcomeStage = (typeof OUTCOME_STAGES)[number]

export const OUTCOME_RESULTS = [
  'pending',
  'no_response',
  'rejected',
  'withdrawn',
  'offer',
  'accepted',
  'declined',
] as const

export type OutcomeResult = (typeof OUTCOME_RESULTS)[number]

export interface OutcomeUpdate {
  applied_at?: string | null
  first_response_at?: string | null
  outcome_stage?: OutcomeStage | null
  outcome_result?: OutcomeResult | null
  rejection_stage?: OutcomeStage | null
  notes?: string | null
  sync_lifecycle?: boolean
}

// --- interviews (INT-01) -----------------------------------------------------

export const INTERVIEW_ROUND_TYPES = [
  'recruiter_screen',
  'hiring_manager',
  'leadership_panel',
  'technical',
  'team',
  'final_round',
  'other',
] as const

export type InterviewRoundType = (typeof INTERVIEW_ROUND_TYPES)[number]

export const INTERVIEW_FORMATS = ['phone', 'video', 'onsite', 'other'] as const

export type InterviewFormat = (typeof INTERVIEW_FORMATS)[number]

export const INTERVIEW_STATUSES = ['scheduled', 'completed', 'cancelled'] as const

export type InterviewStatus = (typeof INTERVIEW_STATUSES)[number]

export type MaterialAudience = 'employer' | 'internal'

export interface InterviewParticipant {
  name: string
  role?: string | null
}

export interface Interview {
  id: number
  job_id: number
  round_type: InterviewRoundType
  title: string | null
  format: InterviewFormat
  status: InterviewStatus
  scheduled_at: string | null
  occurred_at: string | null
  participants: InterviewParticipant[] | null
  notes: string | null
  has_transcript: boolean
  can_debrief: boolean
  transcript_updated_at: string | null
  created_at: string
  updated_at: string
}

export interface InterviewDetail extends Interview {
  transcript: string | null
}

export interface InterviewPayload {
  round_type?: InterviewRoundType
  title?: string | null
  format?: InterviewFormat
  status?: InterviewStatus
  scheduled_at?: string | null
  occurred_at?: string | null
  participants?: InterviewParticipant[] | null
  notes?: string | null
  transcript?: string | null
  sync_outcome?: boolean
}

// Offer-stage documents render on the Offer panel, not the interview timeline
// (OFF-01/OFF-03). Single source of truth for that routing.
export const OFFER_MATERIAL_TYPES = [
  'offer_evaluation',
  'offer_response',
  'onboarding_pack',
  'departure_pack',
] as const

export type OfferMaterialType = (typeof OFFER_MATERIAL_TYPES)[number]

export const INTERNAL_MATERIAL_TYPES = [
  'company_briefing',
  'interviewer_pack',
  'tech_prep_pack',
  'final_round_pack',
  'debrief',
  'email_draft',
  'interviewer_sim_prompt',
  ...OFFER_MATERIAL_TYPES,
] as const

export type InternalMaterialType = (typeof INTERNAL_MATERIAL_TYPES)[number]

export const PACK_TYPES = [
  'company_briefing',
  'interviewer_pack',
  'tech_prep_pack',
  'final_round_pack',
] as const

export type PackType = (typeof PACK_TYPES)[number]

export interface MaterialImportPayload {
  material_type: InternalMaterialType
  title: string
  content: string
  interview_id?: number | null
  effective_date?: string | null
}

// --- offers (OFF-01) ----------------------------------------------------------

export const OFFER_STATUSES = [
  'received',
  'evaluating',
  'negotiating',
  'accepted',
  'declined',
  'withdrawn',
] as const

export type OfferStatus = (typeof OFFER_STATUSES)[number]

export const OFFER_RESPONSE_TYPES = ['accept', 'counter', 'clarify'] as const

export type OfferResponseType = (typeof OFFER_RESPONSE_TYPES)[number]

export interface Offer {
  id: number
  job_id: number
  status: OfferStatus
  base_salary: number | null
  currency: string
  bonus: string | null
  equity: string | null
  pension: string | null
  holiday_days: number | null
  benefits: string | null
  other_terms: string | null
  start_date: string | null
  received_at: string | null
  deadline_at: string | null
  offer_text: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

export interface OfferPayload {
  status?: OfferStatus
  base_salary?: number | null
  currency?: string
  bonus?: string | null
  equity?: string | null
  pension?: string | null
  holiday_days?: number | null
  benefits?: string | null
  other_terms?: string | null
  start_date?: string | null
  received_at?: string | null
  deadline_at?: string | null
  offer_text?: string | null
  notes?: string | null
  sync_outcome?: boolean
}

export interface OfferExtractResult {
  base_salary: number | null
  currency: string | null
  bonus: string | null
  equity: string | null
  pension: string | null
  holiday_days: number | null
  benefits: string | null
  other_terms: string | null
  start_date: string | null
  received_at: string | null
  deadline_at: string | null
  offer_text: string | null
  missing_fields: string[]
  confidence_notes: string | null
}

export interface DeparturePackPayload {
  current_company?: string | null
  current_role?: string | null
  manager_name?: string | null
  notice_period?: string | null
  last_day_target?: string | null
  responsibilities?: string | null
  achievements?: string | null
  notes?: string | null
}

export interface OutcomeFunnel {
  total_applied: number
  responded: number
  interviewed: number
  offers: number
  rejected: number
  response_rate: number | null
  interview_rate: number | null
  offer_rate: number | null
  rounds_recorded: number
  avg_days_between_rounds: number | null
}

export interface Job {
  id: number
  company: string
  title: string
  location: string | null
  hybrid_policy: string | null
  compensation: Record<string, unknown> | null
  seniority: string | null
  application_url: string | null
  posting_date: string | null
  description: string | null
  job_summary: Record<string, unknown> | null
  summary_updated_at: string | null
  source: string
  lifecycle_state: LifecycleState
  fit_score: number | null
  expected_value: number | null
  score_rationale: Record<string, unknown> | null
  applied_at: string | null
  first_response_at: string | null
  outcome_stage: OutcomeStage | null
  outcome_result: OutcomeResult | null
  rejection_stage: OutcomeStage | null
  outcome_notes: string | null
  outcome_updated_at: string | null
  created_at: string
  updated_at: string
}

export interface JobExtractResponse {
  company: string | null
  title: string | null
  location: string | null
  hybrid_policy: string | null
  compensation: Record<string, unknown> | null
  seniority: string | null
  application_url: string | null
  posting_date: string | null
  description: string | null
  missing_fields: string[]
  confidence_notes: string | null
}

export interface CvTailoringSectionReport {
  status: 'applied' | 'template_fallback' | 'partial' | 'missing' | 'evidence_compose'
  reason?: string | null
  detail?: string[]
  requested?: number
  applied?: number
  lines_applied?: number
  roles_total?: number
  roles_applied?: number
  bullets_applied?: number
  bullets_total?: number
  sentences_kept?: number
  sentences_dropped?: number
  source?: string
}

export interface AlignmentGap {
  term: string
  kind: 'entity' | 'requirement'
  status: 'missing' | 'weak'
  closest_claim_id?: string | null
  closest_claim_text?: string | null
  suggestion?: string
}

export interface ExperienceAlignmentNote {
  role_index: number
  alignment: 'approximate' | 'reordered'
  note: string
  closest_claim_id?: string | null
}

export interface CvChangeLine {
  section: 'summary' | 'capability' | 'experience'
  index: number
  role_index?: number
  before: string
  after: string
}

export interface CvChangeSummary {
  lines_total: number
  lines_changed: number
  lines_unchanged: number
  change_rate: number
  summary_changed: boolean
  capabilities_changed: number
  capabilities_total: number
  bullets_changed: number
  bullets_total: number
  changes: CvChangeLine[]
}

export interface CvTailoringReport {
  grounding_profile?: 'strict' | 'aligned' | 'priority'
  summary: CvTailoringSectionReport
  capabilities: CvTailoringSectionReport
  experience: CvTailoringSectionReport
  alignment_gaps?: AlignmentGap[]
  experience_alignment?: ExperienceAlignmentNote[]
  change_summary?: CvChangeSummary
}

export interface GeneratedMaterial {
  id: number
  job_id: number
  interview_id: number | null
  material_type: string
  audience: MaterialAudience
  effective_date: string | null
  title: string
  question: string | null
  word_limit: number | null
  tex_path: string | null
  pdf_path: string | null
  markdown_path: string | null
  evidence_ids: string[] | null
  version: number
  is_final: boolean
  supersedes_id: number | null
  page_count: number | null
  page_fill: number | null
  page_fit: 'ok' | 'short' | 'long' | 'unknown'
  status: string
  created_at: string
  tailoring?: CvTailoringReport | null
}

export interface MaterialQualityReport {
  jd_match: {
    score: number | null
    matched: string[]
    missing: string[]
    term_count: number
  }
  impact: {
    quantified_lines: number
    content_lines: number
  }
  tells: string[]
}

export interface MaterialDraft {
  title: string
  summary?: string | null
  bullets?: string[]
  body?: string | null
  capabilities?: string[]
  experience?: Record<string, string[]>
  evidence_ids?: string[]
  tailoring?: CvTailoringReport
  quality_report?: MaterialQualityReport
}

export interface GeneratedMaterialDetail extends GeneratedMaterial {
  draft_json: MaterialDraft | null
  preview_mode: 'structured' | 'latex_fallback' | 'markdown' | 'unavailable'
  pdf_available: boolean
  tex_available: boolean
  markdown_available: boolean
  fallback_content?: string | null
  tex_content?: string | null
}

export interface MaterialRevisePayload {
  mode: 'structured' | 'latex'
  draft?: Partial<MaterialDraft>
  tex?: string
  markdown_body?: string
}

export interface IngestionSummary {
  added: number
  skipped_duplicate: number
  skipped_stale: number
  prechecked: number
  archived: number
  failed_precheck: number
  succeeded_boards: string[]
  failed_boards: string[]
}

export interface IngestionStarted {
  status: string
}

export interface IngestionConfig {
  ats_boards: string[]
  max_posting_age_days: number
  ingestion_hour: number
  tavily_configured: boolean
}

export interface IngestionHealth {
  last_completed_at: string | null
  age_seconds: number | null
  stale: boolean
  never_run: boolean
  degraded: boolean
  added: number | null
  zero_row_boards: string[]
  failed_boards: string[]
}

export interface DiscoveryHit {
  title: string
  url: string
  snippet: string | null
  score: number | null
}

export interface DiscoverySearchRecord {
  id: number
  query: string
  scoped_query: string | null
  result_count: number
  results: DiscoveryHit[]
  created_at: string
}

export interface AuditEntry {
  id: number
  timestamp: string
  actor: string
  action: string
  entity_type: string | null
  entity_id: string | null
  detail: Record<string, unknown> | null
}

export type SourceDocumentType = 'cv' | 'project' | 'note' | 'document' | 'seed'
export type SourceDocumentStatus = 'imported' | 'duplicate' | 'parsed' | 'extracted' | 'failed'
export type ClaimVerificationState = 'draft' | 'verified' | 'rejected'

export interface SourceChunk {
  id: number
  chunk_index: number
  text: string
  section_path: string | null
  page_start: number | null
  line_start: number | null
  token_estimate: number
}

export interface EvidenceClaim {
  id: string
  source_document_id: number
  source_chunk_id: number | null
  claim_text: string
  category: string
  confidence: number
  verification_state: ClaimVerificationState
  source_span: string | null
  tags: string[] | null
  created_at: string
  updated_at: string
}

export interface KnowledgeEntity {
  id: number
  name: string
  normalized_name: string
  entity_type: string
}

export interface SourceDocument {
  id: number
  filename: string
  title: string | null
  summary: string | null
  original_path: string
  processed_path: string | null
  content_hash: string
  mime_type: string | null
  source_type: SourceDocumentType
  status: SourceDocumentStatus
  error: string | null
  lineage_id: string | null
  version: number
  supersedes_id: number | null
  is_current: boolean
  template_role: string | null
  meta: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface SourceDocumentDetail extends SourceDocument {
  chunks: SourceChunk[]
  claims: EvidenceClaim[]
  entities: KnowledgeEntity[]
  versions: SourceDocument[]
}

export type PasteFormat = 'md' | 'txt' | 'tex'

export interface PasteIngestRequest {
  text: string
  filename?: string
  format?: PasteFormat
  source_type?: SourceDocumentType
  title?: string | null
  lineage_id?: string | null
  supersedes_id?: number | null
  promote_template?: boolean
}

export type GraphNodeKind = 'source' | 'claim' | 'entity'
export type GraphEdgeKind = 'supersedes' | 'has_claim' | 'mentions' | 'related_to'

export interface GraphNode {
  id: string
  kind: GraphNodeKind
  label: string
  detail: string | null
  group: string | null
  ref_id: string | null
  meta: Record<string, unknown>
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  kind: GraphEdgeKind
}

export interface KnowledgeGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

// --- KG-02 evidence coverage ------------------------------------------------

export interface CoverageMonthly {
  month: string // YYYY-MM
  claims: number
}

export interface CoverageValue {
  value: string
  verified_claims: number
  draft_claims: number
  claim_ids: string[]
  demand_jobs: number
  job_ids: number[]
  gap: boolean
  monthly: CoverageMonthly[]
}

export interface CoverageFacet {
  facet: string
  values: CoverageValue[]
  vocabulary_size: number
}

export interface CoverageJob {
  id: number
  company: string
  title: string
}

export interface CoverageTotals {
  claims: number
  faceted_claims: number
  unfaceted_claims: number
  scored_jobs: number
  faceted_jobs: number
  unfaceted_jobs: number
}

export interface Coverage {
  facets: CoverageFacet[]
  jobs: CoverageJob[]
  totals: CoverageTotals
}

export interface FacetBackfillResult {
  documents_faceted: number
  documents_skipped: number
  jobs_faceted: number
  jobs_skipped: number
  facet_rows: number
  rejected: string[]
}

export type VersionDiffOp = 'context' | 'add' | 'remove' | 'gap'

export interface VersionDiffLine {
  op: VersionDiffOp
  text: string
}

export interface VersionDiff {
  base_id: number
  base_version: number
  target_id: number
  target_version: number
  added: number
  removed: number
  lines: VersionDiffLine[]
}

export interface KnowledgeIngestResult {
  source_document: SourceDocument
  created: boolean
  chunks: number
  claims: number
  verified_claims: number
}

export interface PublicSummary {
  total_jobs: number
  applied: number
  interviewing: number
  offers: number
  suppressed: number
}

export interface PublicPipeline {
  states: { state: string; count: number }[]
  suppressed: number
}

export interface PublicScoreHistogram {
  buckets: { label: string; count: number }[]
  suppressed: number
}

export interface PublicVelocity {
  points: { week: string; transitions: number }[]
  suppressed: number
}

export interface ObservabilityWindow {
  call_count: number
  total_cost_usd: number
  total_tokens: number
  avg_latency_ms: number
  error_rate: number
}

export interface ObservabilitySummary {
  today: ObservabilityWindow
  '7d': ObservabilityWindow
  '30d': ObservabilityWindow
}

export interface LlmCall {
  id: number
  trace_id: string | null
  timestamp: string
  operation: string
  provider: string
  request_model: string
  operation_name: string
  input_tokens: number
  output_tokens: number
  latency_ms: number
  cost_usd: number
  status: string
  entity_type: string | null
  entity_id: string | null
  detail: Record<string, unknown> | null
}

export interface CostBucket {
  key: string
  cost_usd: number
  tokens: number
  calls: number
}

export interface LatencyRow {
  operation_name: string
  count: number
  p50_ms: number
  p95_ms: number
  p99_ms: number
  avg_ms: number
}

export interface PipelineRun {
  id: number
  trace_id: string
  pipeline_type: string
  started_at: string
  finished_at: string | null
  status: string
  total_cost_usd: number
  total_tokens: number
  step_count: number
  entity_type: string | null
  entity_id: string | null
  detail: Record<string, unknown> | null
}

export interface PipelineStep {
  id: number
  trace_id: string
  span_id: string
  step_name: string
  step_type: string
  decision: string | null
  started_at: string
  duration_ms: number
  status: string
  detail: Record<string, unknown> | null
}

export interface PipelineRunDetail {
  run: PipelineRun
  steps: PipelineStep[]
}

export interface DataSource {
  id: number
  name: string
  kind: string
  config: Record<string, unknown> | null
  enabled: boolean
  health_status: string
  last_used_at: string | null
  record_count: number
  pii_flag: boolean
  retention_days: number | null
  notes: string | null
}

export interface DataSourceDetail {
  source: DataSource
  lineage: Record<string, unknown>
  recent_calls: LlmCall[]
}

export interface PerformanceScorecard {
  operation_name: string
  call_count: number
  success_rate: number
  latency_p50_ms: number
  latency_p95_ms: number
  avg_cost_usd: number
  total_cost_usd: number
}

export interface StorageMetrics {
  table_counts: Record<string, number>
  sqlite_bytes: number
  materials_bytes: number
  knowledge_bytes: number
  telemetry_retention_days: number
  materials_retention_days: number
}

export type ApiKeyProvider = 'anthropic' | 'tavily' | 'openai'

export interface SettingsStatus {
  anthropic_configured: boolean
  anthropic_source: 'env' | 'stored' | null
  tavily_configured: boolean
  openai_configured: boolean
  has_documents: boolean
  has_verified_facts: boolean
  has_cv_template: boolean
  setup_complete: boolean
}
