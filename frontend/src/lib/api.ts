import axios from 'axios'
import { authBridge } from './authBridge'
import { invalidateKnowledgeClaimsCache } from './knowledgeClaimsCache'
import type {
  ApiKeyProvider,
  AuditEntry,
  DeparturePackPayload,
  ClaimVerificationState,
  DiscoveryHit,
  DiscoverySearchRecord,
  EvidenceClaim,
  GeneratedMaterial,
  GeneratedMaterialDetail,
  IngestionConfig,
  IngestionHealth,
  IngestionStarted,
  Interview,
  InterviewDetail,
  InterviewPayload,
  Job,
  JobExtractResponse,
  KnowledgeGraph,
  Coverage,
  FacetBackfillResult,
  KnowledgeIngestResult,
  LifecycleState,
  MaterialImportPayload,
  MaterialRevisePayload,
  Offer,
  OfferExtractResult,
  OfferPayload,
  OfferResponseType,
  PackType,
  OutcomeFunnel,
  OutcomeUpdate,
  PasteIngestRequest,
  PublicPipeline,
  PublicScoreHistogram,
  PublicSummary,
  PublicVelocity,
  ObservabilitySummary,
  LlmCall,
  CostBucket,
  LatencyRow,
  PipelineRun,
  PipelineRunDetail,
  DataSource,
  DataSourceDetail,
  PerformanceScorecard,
  StorageMetrics,
  SettingsStatus,
  SourceDocument,
  SourceDocumentDetail,
  SourceDocumentType,
  VersionDiff,
} from './types'

// Same-origin in production (served behind nginx); the dev server proxies /api.
export const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
  timeout: 30_000,
})

export function apiErrorMessage(error: unknown, fallback: string): string {
  if (!axios.isAxiosError(error)) return fallback
  const detail = error.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (error.code === 'ECONNABORTED' || error.message?.toLowerCase().includes('timeout')) {
    return 'Generation timed out — try again.'
  }
  if (!error.response) {
    return 'Could not reach the server — check your connection and try again.'
  }
  return fallback
}

// LLM-backed API calls can take a while; mirror the production nginx allowance.
const LONG_TIMEOUT = 300_000

// On a 401/403 for a protected path, flip the auth store so the UI can redirect
// to login. Auth-endpoint failures are expected (e.g. wrong password) and skipped.
api.interceptors.response.use(
  (res) => res,
  (error) => {
    const status = error?.response?.status
    const url: string = error?.config?.url ?? ''
    if ((status === 401 || status === 403) && !url.includes('/auth/')) {
      authBridge.setUnauthed()
    }
    return Promise.reject(error)
  },
)

// --- auth -------------------------------------------------------------------

export async function login(password: string): Promise<void> {
  await api.post('/auth/login', { password })
  authBridge.setAuthed()
}

export async function logout(): Promise<void> {
  // Always drop the client-side auth state: even if the network call fails,
  // the UI is about to land on /login and must not think it's still authed.
  try {
    await api.post('/auth/logout')
  } finally {
    authBridge.setUnauthed()
  }
}

export async function checkSession(): Promise<boolean> {
  try {
    await api.get('/auth/session')
    authBridge.setAuthed()
    return true
  } catch {
    authBridge.setUnauthed()
    return false
  }
}

// --- jobs -------------------------------------------------------------------

export async function listJobs(options?: {
  state?: LifecycleState
  curated?: boolean
}): Promise<Job[]> {
  const params = {
    ...(options?.state ? { state: options.state } : {}),
    ...(options?.curated ? { curated: true } : {}),
  }
  const { data } = await api.get<Job[]>('/jobs', {
    params: Object.keys(params).length ? params : undefined,
  })
  return data
}

export async function getJob(id: number): Promise<Job> {
  const { data } = await api.get<Job>(`/jobs/${id}`)
  return data
}

export async function updateJobApplicationUrl(id: number, applicationUrl: string | null): Promise<Job> {
  const { data } = await api.patch<Job>(`/jobs/${id}`, {
    application_url: applicationUrl || null,
  })
  return data
}

export async function createJob(payload: Partial<Job>): Promise<Job> {
  const { data } = await api.post<Job>('/jobs', payload)
  return data
}

export async function extractJob(
  rawText: string,
  applicationUrl?: string,
): Promise<JobExtractResponse> {
  const { data } = await api.post<JobExtractResponse>('/jobs/extract', {
    raw_text: rawText,
    application_url: applicationUrl || null,
  })
  return data
}

export async function scoreJob(id: number): Promise<Job> {
  const { data } = await api.post<Job>(`/jobs/${id}/score`, null, { timeout: LONG_TIMEOUT })
  return data
}

export async function summarizeJob(id: number): Promise<Job> {
  const { data } = await api.post<Job>(`/jobs/${id}/summarize`, null, { timeout: LONG_TIMEOUT })
  return data
}

export async function changeState(id: number, state: LifecycleState, note?: string): Promise<Job> {
  const { data } = await api.post<Job>(`/jobs/${id}/state`, { state, note: note || null })
  return data
}

export async function recordOutcome(id: number, payload: OutcomeUpdate): Promise<Job> {
  const { data } = await api.post<Job>(`/jobs/${id}/outcome`, payload)
  return data
}

export async function getOutcomeFunnel(): Promise<OutcomeFunnel> {
  const { data } = await api.get<OutcomeFunnel>('/jobs/outcomes/funnel')
  return data
}

export async function listMaterials(id: number): Promise<GeneratedMaterial[]> {
  const { data } = await api.get<GeneratedMaterial[]>(`/jobs/${id}/materials`)
  return data
}

export async function generateMaterial(
  id: number,
  kind: 'cv' | 'cover-letter',
): Promise<GeneratedMaterial> {
  const { data } = await api.post<GeneratedMaterial>(`/jobs/${id}/materials/${kind}`, null, {
    timeout: LONG_TIMEOUT,
  })
  return data
}

export async function generateAnswer(
  id: number,
  question: string,
  wordLimit?: number,
  instructions?: string,
): Promise<GeneratedMaterial> {
  const { data } = await api.post<GeneratedMaterial>(
    `/jobs/${id}/materials/answer`,
    { question, word_limit: wordLimit ?? null, instructions: instructions || null },
    { timeout: LONG_TIMEOUT },
  )
  return data
}

export async function getMaterial(jobId: number, materialId: number): Promise<GeneratedMaterialDetail> {
  const { data } = await api.get<GeneratedMaterialDetail>(`/jobs/${jobId}/materials/${materialId}`)
  return data
}

export function getMaterialFileUrl(
  jobId: number,
  materialId: number,
  kind: 'pdf' | 'tex' | 'md',
  disposition: 'inline' | 'attachment' = 'attachment',
): string {
  return `/api/jobs/${jobId}/materials/${materialId}/file/${kind}?disposition=${disposition}`
}

export async function downloadMaterial(
  jobId: number,
  materialId: number,
  kind: 'pdf' | 'tex' | 'md',
  filename?: string,
): Promise<void> {
  const response = await api.get(
    `/jobs/${jobId}/materials/${materialId}/file/${kind}?disposition=attachment`,
    { responseType: 'blob' },
  )
  const cd = response.headers['content-disposition'] as string | undefined
  const fromHeader = cd?.match(/filename="([^"]+)"/)?.[1]
  const url = URL.createObjectURL(response.data)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename ?? fromHeader ?? `${kind}-${materialId}.${kind === 'md' ? 'md' : kind}`
  anchor.click()
  URL.revokeObjectURL(url)
}

export async function reviseMaterial(
  jobId: number,
  materialId: number,
  payload: MaterialRevisePayload,
): Promise<GeneratedMaterialDetail> {
  const { data } = await api.patch<GeneratedMaterialDetail>(
    `/jobs/${jobId}/materials/${materialId}`,
    payload,
    { timeout: LONG_TIMEOUT },
  )
  return data
}

export async function markMaterialFinal(
  jobId: number,
  materialId: number,
): Promise<GeneratedMaterialDetail> {
  const { data } = await api.post<GeneratedMaterialDetail>(
    `/jobs/${jobId}/materials/${materialId}/mark-final`,
    null,
  )
  return data
}

export async function unmarkMaterialFinal(
  jobId: number,
  materialId: number,
): Promise<GeneratedMaterialDetail> {
  const { data } = await api.post<GeneratedMaterialDetail>(
    `/jobs/${jobId}/materials/${materialId}/unmark-final`,
    null,
  )
  return data
}

export async function requestMaterialRevision(
  jobId: number,
  materialId: number,
  instruction: string,
): Promise<GeneratedMaterialDetail> {
  const { data } = await api.post<GeneratedMaterialDetail>(
    `/jobs/${jobId}/materials/${materialId}/revise-request`,
    { instruction },
    { timeout: LONG_TIMEOUT },
  )
  return data
}

export async function fitMaterialToPages(
  jobId: number,
  materialId: number,
): Promise<GeneratedMaterialDetail> {
  const { data } = await api.post<GeneratedMaterialDetail>(
    `/jobs/${jobId}/materials/${materialId}/fit-pages`,
    null,
    { timeout: LONG_TIMEOUT },
  )
  return data
}

// --- interviews (INT-01) ------------------------------------------------------

export async function listInterviews(jobId: number): Promise<Interview[]> {
  const { data } = await api.get<Interview[]>(`/jobs/${jobId}/interviews`)
  return data
}

export async function getInterview(jobId: number, interviewId: number): Promise<InterviewDetail> {
  const { data } = await api.get<InterviewDetail>(`/jobs/${jobId}/interviews/${interviewId}`)
  return data
}

export async function createInterview(jobId: number, payload: InterviewPayload): Promise<Interview> {
  const { data } = await api.post<Interview>(`/jobs/${jobId}/interviews`, payload)
  return data
}

export async function updateInterview(
  jobId: number,
  interviewId: number,
  payload: InterviewPayload,
): Promise<Interview> {
  const { data } = await api.patch<Interview>(`/jobs/${jobId}/interviews/${interviewId}`, payload)
  return data
}

export async function deleteInterview(jobId: number, interviewId: number): Promise<void> {
  await api.delete(`/jobs/${jobId}/interviews/${interviewId}`)
}

export async function setInterviewTranscript(
  jobId: number,
  interviewId: number,
  transcript: string,
): Promise<InterviewDetail> {
  const { data } = await api.put<InterviewDetail>(
    `/jobs/${jobId}/interviews/${interviewId}/transcript`,
    { transcript },
  )
  return data
}

export async function importMaterial(
  jobId: number,
  payload: MaterialImportPayload,
): Promise<GeneratedMaterial> {
  const { data } = await api.post<GeneratedMaterial>(`/jobs/${jobId}/materials/import`, payload)
  return data
}

export async function generatePack(
  jobId: number,
  packType: PackType,
  interviewId?: number | null,
  opts?: { enhance?: boolean; sourceMaterialId?: number },
): Promise<GeneratedMaterial> {
  const { data } = await api.post<GeneratedMaterial>(
    `/jobs/${jobId}/materials/pack`,
    {
      pack_type: packType,
      interview_id: interviewId ?? null,
      enhance: opts?.enhance ?? false,
      source_material_id: opts?.sourceMaterialId ?? null,
    },
    { timeout: LONG_TIMEOUT },
  )
  return data
}

export async function generateDebrief(
  jobId: number,
  interviewId: number,
): Promise<GeneratedMaterial> {
  const { data } = await api.post<GeneratedMaterial>(
    `/jobs/${jobId}/interviews/${interviewId}/debrief`,
    null,
    { timeout: LONG_TIMEOUT },
  )
  return data
}

export async function generateSimPrompt(
  jobId: number,
  interviewId?: number | null,
): Promise<GeneratedMaterial> {
  const { data } = await api.post<GeneratedMaterial>(`/jobs/${jobId}/materials/sim-prompt`, {
    interview_id: interviewId ?? null,
  })
  return data
}

export async function promoteLearning(
  jobId: number,
  interviewId: number,
  claimText: string,
): Promise<EvidenceClaim> {
  const { data } = await api.post<EvidenceClaim>(
    `/jobs/${jobId}/interviews/${interviewId}/promote-learning`,
    { claim_text: claimText },
  )
  invalidateKnowledgeClaimsCache()
  return data
}

export async function generateEmailDraft(
  jobId: number,
  payload: { instructions?: string; inbound_email?: string; interview_id?: number | null },
): Promise<GeneratedMaterial> {
  const { data } = await api.post<GeneratedMaterial>(
    `/jobs/${jobId}/materials/email-draft`,
    payload,
    { timeout: LONG_TIMEOUT },
  )
  return data
}

// --- offers (OFF-01) ---------------------------------------------------------

export async function listOffers(jobId: number): Promise<Offer[]> {
  const { data } = await api.get<Offer[]>(`/jobs/${jobId}/offers`)
  return data
}

export async function createOffer(jobId: number, payload: OfferPayload): Promise<Offer> {
  const { data } = await api.post<Offer>(`/jobs/${jobId}/offers`, payload)
  return data
}

export async function updateOffer(
  jobId: number,
  offerId: number,
  payload: OfferPayload,
): Promise<Offer> {
  const { data } = await api.patch<Offer>(`/jobs/${jobId}/offers/${offerId}`, payload)
  return data
}

export async function deleteOffer(jobId: number, offerId: number): Promise<void> {
  await api.delete(`/jobs/${jobId}/offers/${offerId}`)
}

export async function evaluateOffer(jobId: number, offerId: number): Promise<GeneratedMaterial> {
  const { data } = await api.post<GeneratedMaterial>(
    `/jobs/${jobId}/offers/${offerId}/evaluate`,
    null,
    { timeout: LONG_TIMEOUT },
  )
  return data
}

export async function extractOffer(jobId: number, rawText: string): Promise<OfferExtractResult> {
  const { data } = await api.post<OfferExtractResult>(
    `/jobs/${jobId}/offers/extract`,
    { raw_text: rawText },
    { timeout: LONG_TIMEOUT },
  )
  return data
}

export async function extractOfferFile(jobId: number, file: File): Promise<OfferExtractResult> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post<OfferExtractResult>(
    `/jobs/${jobId}/offers/extract-file`,
    form,
    { timeout: LONG_TIMEOUT },
  )
  return data
}

export async function generateOnboardingPack(jobId: number): Promise<GeneratedMaterial> {
  const { data } = await api.post<GeneratedMaterial>(
    `/jobs/${jobId}/materials/onboarding-pack`,
    null,
    { timeout: LONG_TIMEOUT },
  )
  return data
}

export async function generateDeparturePack(
  jobId: number,
  payload: DeparturePackPayload,
): Promise<GeneratedMaterial> {
  const { data } = await api.post<GeneratedMaterial>(
    `/jobs/${jobId}/materials/departure-pack`,
    payload,
    { timeout: LONG_TIMEOUT },
  )
  return data
}

export async function draftOfferResponse(
  jobId: number,
  offerId: number,
  payload: { response_type: OfferResponseType; instructions?: string },
): Promise<GeneratedMaterial> {
  const { data } = await api.post<GeneratedMaterial>(
    `/jobs/${jobId}/offers/${offerId}/response-draft`,
    payload,
    { timeout: LONG_TIMEOUT },
  )
  return data
}

// --- ingestion / discovery / audit -----------------------------------------

export async function getIngestionConfig(): Promise<IngestionConfig> {
  const { data } = await api.get<IngestionConfig>('/ingestion/config')
  return data
}

export async function getIngestionHealth(): Promise<IngestionHealth> {
  const { data } = await api.get<IngestionHealth>('/ingestion/health')
  return data
}

export async function runIngestion(): Promise<IngestionStarted> {
  // Ingestion runs in the background server-side (pull + bounded precheck can
  // exceed the edge proxy's request timeout), so this returns a fast 202 ack.
  const { data } = await api.post<IngestionStarted>('/ingestion/run')
  return data
}

export async function discoverySearch(query: string, maxResults = 10): Promise<DiscoveryHit[]> {
  const { data } = await api.post<DiscoveryHit[]>('/discovery/search', {
    query,
    max_results: maxResults,
  })
  return data
}

export async function listDiscoverySearches(limit = 20): Promise<DiscoverySearchRecord[]> {
  const { data } = await api.get<DiscoverySearchRecord[]>('/discovery/searches', {
    params: { limit },
  })
  return data
}

export async function listAudit(limit = 100): Promise<AuditEntry[]> {
  const { data } = await api.get<AuditEntry[]>('/audit', { params: { limit } })
  return data
}

// --- knowledge --------------------------------------------------------------

export async function listKnowledgeSources(): Promise<SourceDocument[]> {
  const { data } = await api.get<SourceDocument[]>('/knowledge/sources')
  return data
}

export async function getKnowledgeSource(id: number): Promise<SourceDocumentDetail> {
  const { data } = await api.get<SourceDocumentDetail>(`/knowledge/sources/${id}`)
  return data
}

export async function listKnowledgeClaims(
  state?: ClaimVerificationState,
): Promise<EvidenceClaim[]> {
  const { data } = await api.get<EvidenceClaim[]>('/knowledge/claims', {
    params: state ? { state } : undefined,
  })
  return data
}

export async function getKnowledgeCoverage(): Promise<Coverage> {
  const { data } = await api.get<Coverage>('/knowledge/coverage')
  return data
}

export async function backfillKnowledgeFacets(force = false): Promise<FacetBackfillResult> {
  const { data } = await api.post<FacetBackfillResult>('/knowledge/coverage/backfill', null, {
    params: force ? { force: true } : undefined,
    timeout: LONG_TIMEOUT,
  })
  return data
}

export async function uploadKnowledgeSource(
  file: File,
  sourceType: SourceDocumentType,
): Promise<KnowledgeIngestResult> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post<KnowledgeIngestResult>('/knowledge/upload', form, {
    params: { source_type: sourceType },
    timeout: LONG_TIMEOUT,
  })
  return data
}

export async function importKnowledgeInbox(): Promise<KnowledgeIngestResult[]> {
  const { data } = await api.post<{ results: KnowledgeIngestResult[] }>(
    '/knowledge/import-inbox',
    null,
    { timeout: LONG_TIMEOUT },
  )
  return data.results
}

export async function verifyKnowledgeClaim(id: string): Promise<EvidenceClaim> {
  const { data } = await api.post<EvidenceClaim>(`/knowledge/claims/${id}/verify`)
  invalidateKnowledgeClaimsCache()
  return data
}

export async function rejectKnowledgeClaim(id: string): Promise<EvidenceClaim> {
  const { data } = await api.post<EvidenceClaim>(`/knowledge/claims/${id}/reject`)
  invalidateKnowledgeClaimsCache()
  return data
}

export async function reopenKnowledgeClaim(id: string): Promise<EvidenceClaim> {
  const { data } = await api.post<EvidenceClaim>(`/knowledge/claims/${id}/reopen`)
  invalidateKnowledgeClaimsCache()
  return data
}

export async function updateKnowledgeClaim(
  id: string,
  payload: Partial<Pick<EvidenceClaim, 'claim_text' | 'category' | 'confidence' | 'source_span' | 'tags'>>,
): Promise<EvidenceClaim> {
  const { data } = await api.patch<EvidenceClaim>(`/knowledge/claims/${id}`, payload)
  invalidateKnowledgeClaimsCache()
  return data
}

export async function getKnowledgeGraph(options?: {
  includeClaims?: boolean
  includeEntities?: boolean
  includeLineage?: boolean
}): Promise<KnowledgeGraph> {
  const { data } = await api.get<KnowledgeGraph>('/knowledge/graph', {
    params: {
      include_claims: options?.includeClaims ?? false,
      include_entities: options?.includeEntities ?? false,
      include_lineage: options?.includeLineage ?? false,
    },
  })
  return data
}

export function knowledgeSourceFileUrl(id: number, kind: 'original' | 'processed' = 'original'): string {
  return `/api/knowledge/sources/${id}/file?kind=${kind}`
}

export async function pasteKnowledgeSource(payload: PasteIngestRequest): Promise<KnowledgeIngestResult> {
  const { data } = await api.post<KnowledgeIngestResult>('/knowledge/paste', payload, {
    timeout: LONG_TIMEOUT,
  })
  return data
}

export async function promoteKnowledgeTemplate(id: number): Promise<SourceDocument> {
  const { data } = await api.post<SourceDocument>(`/knowledge/sources/${id}/promote-template`)
  return data
}

export async function activateKnowledgeVersion(id: number): Promise<SourceDocument> {
  const { data } = await api.post<SourceDocument>(`/knowledge/sources/${id}/activate`)
  return data
}

export async function getKnowledgeVersionDiff(targetId: number, againstId: number): Promise<VersionDiff> {
  const { data } = await api.get<VersionDiff>(`/knowledge/sources/${targetId}/diff`, {
    params: { against: againstId },
  })
  return data
}

export async function summarizeKnowledgeVersionDiff(targetId: number, againstId: number): Promise<string> {
  const { data } = await api.post<{ summary: string }>(
    `/knowledge/sources/${targetId}/diff-summary`,
    { against: againstId },
    { timeout: LONG_TIMEOUT },
  )
  return data.summary
}

// --- observability ----------------------------------------------------------

export async function getObservabilitySummary(): Promise<ObservabilitySummary> {
  const { data } = await api.get<ObservabilitySummary>('/observability/summary')
  return data
}

export async function listLlmCalls(options?: {
  limit?: number
  offset?: number
  operation_name?: string
}): Promise<LlmCall[]> {
  const { data } = await api.get<LlmCall[]>('/observability/calls', { params: options })
  return data
}

export async function getObservabilityCosts(days = 30): Promise<CostBucket[]> {
  const { data } = await api.get<CostBucket[]>('/observability/costs', { params: { days } })
  return data
}

export async function getObservabilityLatency(days = 30): Promise<LatencyRow[]> {
  const { data } = await api.get<LatencyRow[]>('/observability/latency', { params: { days } })
  return data
}

export async function listPipelineRuns(limit = 50): Promise<PipelineRun[]> {
  const { data } = await api.get<PipelineRun[]>('/observability/runs', { params: { limit } })
  return data
}

export async function getPipelineRun(traceId: string): Promise<PipelineRunDetail> {
  const { data } = await api.get<PipelineRunDetail>(`/observability/runs/${traceId}`)
  return data
}

export async function listDataSources(): Promise<DataSource[]> {
  const { data } = await api.get<DataSource[]>('/observability/datasources')
  return data
}

export async function getDataSource(id: number): Promise<DataSourceDetail> {
  const { data } = await api.get<DataSourceDetail>(`/observability/datasources/${id}`)
  return data
}

export async function getObservabilityPerformance(days = 30): Promise<PerformanceScorecard[]> {
  const { data } = await api.get<PerformanceScorecard[]>('/observability/performance', { params: { days } })
  return data
}

export async function getObservabilityStorage(): Promise<StorageMetrics> {
  const { data } = await api.get<StorageMetrics>('/observability/storage')
  return data
}

// --- public surface (anonymous) --------------------------------------------

export async function publicSummary(): Promise<PublicSummary> {
  const { data } = await api.get<PublicSummary>('/public/summary')
  return data
}

export async function publicPipeline(): Promise<PublicPipeline> {
  const { data } = await api.get<PublicPipeline>('/public/pipeline')
  return data
}

export async function publicScores(): Promise<PublicScoreHistogram> {
  const { data } = await api.get<PublicScoreHistogram>('/public/scores')
  return data
}

export async function publicVelocity(): Promise<PublicVelocity> {
  const { data } = await api.get<PublicVelocity>('/public/velocity')
  return data
}

// --- Settings / first-run (PS-P1) ------------------------------------------

export async function getSettingsStatus(): Promise<SettingsStatus> {
  const { data } = await api.get<SettingsStatus>('/settings/status')
  return data
}

export async function saveApiKey(
  provider: ApiKeyProvider,
  key: string,
): Promise<SettingsStatus> {
  // Validating an Anthropic key makes a (tiny) live call, so allow extra time.
  const { data } = await api.put<SettingsStatus>(
    '/settings/keys',
    { provider, key },
    { timeout: LONG_TIMEOUT },
  )
  return data
}

export async function deleteApiKey(provider: ApiKeyProvider): Promise<SettingsStatus> {
  const { data } = await api.delete<SettingsStatus>(`/settings/keys/${provider}`)
  return data
}
