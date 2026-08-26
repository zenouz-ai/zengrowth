import { useState } from 'react'
import { useParams } from 'react-router'
import { AlertBanner } from '../components/AlertBanner'
import { AnswerPanel } from '../components/AnswerPanel'
import { EmptyState } from '../components/EmptyState'
import { InterviewTimeline } from '../components/InterviewTimeline'
import { MaterialVersionList } from '../components/MaterialPreviewPanel'
import { MetricCard } from '../components/MetricCard'
import { OfferPanel } from '../components/OfferPanel'
import { Panel } from '../components/Panel'
import { RationalePanel } from '../components/RationalePanel'
import { Skeleton } from '../components/Skeleton'
import { StatusPill } from '../components/StatusPill'
import { AuditTimeline } from '../components/AuditTimeline'
import { useAsyncData } from '../hooks/useAsyncData'
import { useSSE } from '../hooks/useSSE'
import {
  changeState,
  apiErrorMessage,
  downloadMaterial,
  generateJourneySummary,
  generateMaterial,
  generateRejectionReflection,
  getJob,
  getJourneySummaryEligibility,
  listAudit,
  listInterviews,
  listMaterials,
  listOffers,
  listCloseoutLearnings,
  promoteCloseoutLearnings,
  promoteJobLearning,
  recordOutcome,
  scoreJob,
  summarizeJob,
  updateJobApplicationUrl,
} from '../lib/api'
import {
  LIFECYCLE_STATES,
  OFFER_MATERIAL_TYPES,
  OUTCOME_RESULTS,
  OUTCOME_STAGES,
  type AuditEntry,
  type GeneratedMaterial,
  type Interview,
  type Job,
  type LifecycleState,
  type OutcomeResult,
  type OutcomeStage,
  type OutcomeUpdate,
} from '../lib/types'
import { ArtifactRow } from '../components/ArtifactRow'

export function JobDetail() {
  const { id } = useParams()
  const jobId = Number(id)
  const job = useAsyncData(() => getJob(jobId), [jobId])
  const materials = useAsyncData(() => listMaterials(jobId), [jobId])
  const interviews = useAsyncData(() => listInterviews(jobId), [jobId])
  const offers = useAsyncData(() => listOffers(jobId), [jobId])
  const audit = useAsyncData(() => listAudit(200), [jobId])
  const { events } = useSSE<AuditEntry>('/api/events/stream')
  const [busy, setBusy] = useState<string>()
  // Prepare = clean + score; Generate CV = default; cover letter is opt-in per job.
  const [flow, setFlow] = useState<string>()
  const [error, setError] = useState<string>()
  const [selectedMaterialId, setSelectedMaterialId] = useState<number | null>(null)

  async function run(label: string, fn: () => Promise<unknown>) {
    setBusy(label)
    setError(undefined)
    try {
      const result = await fn()
      job.refetch()
      materials.refetch()
      audit.refetch()
      return result
    } catch (err) {
      setError(apiErrorMessage(err, `${label} failed.`))
      return undefined
    } finally {
      setBusy(undefined)
    }
  }

  // Orchestrate a sequence of steps under one button, surfacing the live step
  // label. Each underlying call already streams to the audit feed.
  async function orchestrate(steps: { label: string; fn: () => Promise<unknown> }[]) {
    setError(undefined)
    try {
      for (const step of steps) {
        setFlow(step.label)
        await step.fn()
      }
      job.refetch()
      materials.refetch()
      audit.refetch()
    } catch (err) {
      setError(apiErrorMessage(err, 'Something went wrong. You can retry below.'))
    } finally {
      setFlow(undefined)
    }
  }

  if (job.loading && !job.data) return <Skeleton className="h-64" />
  if (!job.data) return <AlertBanner tone="error">Job not found.</AlertBanner>
  const j = job.data
  const allMaterials = materials.data ?? []
  const applicationAnswers = allMaterials.filter((m) => m.material_type === 'answer')
  // Internal artifacts (prep packs, debriefs) live on the interview timeline,
  // not in the employer-facing Materials panel; offer documents live on the
  // Offer panel (OFF-01).
  const offerMaterialTypes = new Set<string>(OFFER_MATERIAL_TYPES)
  const offerMaterials = allMaterials.filter((m) => offerMaterialTypes.has(m.material_type))
  const internalMaterials = allMaterials.filter(
    (m) => m.audience === 'internal' && !offerMaterialTypes.has(m.material_type),
  )
  const documentMaterials = allMaterials.filter(
    (m) => m.material_type !== 'answer' && m.audience !== 'internal',
  )
  const scored = j.fit_score != null
  const working = !!flow || !!busy

  const liveForJob = events.filter((e) => e.entity_type === 'job' && e.entity_id === String(jobId))
  const persistedForJob = (audit.data ?? []).filter(
    (e) => e.entity_type === 'job' && e.entity_id === String(jobId),
  )

  async function prepare() {
    await orchestrate([
      ...(!j.job_summary ? [{ label: 'Cleaning the description…', fn: () => summarizeJob(jobId) }] : []),
      { label: 'Scoring the match…', fn: () => scoreJob(jobId) },
    ])
  }

  const hasCoverLetter = documentMaterials.some((m) => m.material_type === 'cover_letter')

  async function generateCv() {
    await orchestrate([
      {
        label: 'Drafting your CV…',
        fn: async () => {
          const cv = await generateMaterial(jobId, 'cv')
          setSelectedMaterialId(cv.id)
        },
      },
    ])
  }

  async function generateCoverLetter() {
    await orchestrate([
      {
        label: 'Writing the cover letter…',
        fn: async () => {
          const letter = await generateMaterial(jobId, 'cover-letter')
          setSelectedMaterialId(letter.id)
        },
      },
    ])
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-2xl font-bold">{j.company}</h1>
          <p className="text-muted">{j.title}</p>
        </div>
        <StatusPill state={j.lifecycle_state} />
      </div>

      <ApplicationLinkPanel
        key={`${jobId}-${j.application_url ?? ''}`}
        applicationUrl={j.application_url}
        onSave={async (url) => {
          await updateJobApplicationUrl(jobId, url)
          job.refetch()
        }}
      />

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <MetricCard label="Fit score" value={j.fit_score?.toFixed(0) ?? '—'} />
        <MetricCard label="Priority score" value={j.expected_value?.toFixed(1) ?? '—'} />
        <MetricCard label="Source" value={j.source} />
      </div>

      {error && <AlertBanner tone="error">{error}</AlertBanner>}

      {/* One confident primary action (PS-P2). Nothing spends until clicked. */}
      <Panel title={scored ? 'Generate your application' : 'Prepare this job'}>
        {flow ? (
          <div className="flex items-center gap-3 text-sm text-cyan">
            <span className="h-2 w-2 animate-pulse rounded-full bg-cyan" />
            {flow}
          </div>
        ) : scored ? (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-muted">
              Draft a tailored CV grounded in your approved facts — employers, dates, and metrics
              stay unchanged. Add a cover letter only when the posting asks for one.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <button
                onClick={generateCv}
                disabled={working}
                className="rounded-lg border border-violet bg-violet/10 px-4 py-2 text-sm font-medium text-violet disabled:opacity-50"
              >
                Generate CV
              </button>
              <button
                onClick={generateCoverLetter}
                disabled={working}
                className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-muted hover:text-text disabled:opacity-50"
              >
                {hasCoverLetter ? 'Regenerate cover letter' : 'I need a cover letter'}
              </button>
              <MoreActions
                state={j.lifecycle_state}
                disabled={working}
                onScore={() => run('Score', () => scoreJob(jobId))}
                onSummarize={() => run('Summarize', () => summarizeJob(jobId))}
                onCv={() =>
                  run('CV', () => generateMaterial(jobId, 'cv')).then((m) => {
                    if (m && typeof m === 'object' && 'id' in m) setSelectedMaterialId(m.id as number)
                  })
                }
                onState={(s) => run('State change', () => changeState(jobId, s))}
              />
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-muted">
              ZenGrowth will clean the posting into a readable brief and score how it fits your
              experience — one step, so you can decide whether to apply.
            </p>
            <button
              onClick={prepare}
              disabled={working}
              className="self-start rounded-lg border border-cyan bg-cyan/10 px-4 py-2 text-sm font-medium text-cyan disabled:opacity-50"
            >
              Prepare application
            </button>
          </div>
        )}
      </Panel>

      <RationalePanel rationale={j.score_rationale} expectedValue={j.expected_value} />

      {/* Material-first: the generated documents are the hero of the page. */}
      <Panel title="Materials">
        {documentMaterials.length === 0 ? (
          <EmptyState
            message={
              scored
                ? 'No CV yet — use Generate CV above. Cover letters and answers are optional.'
                : 'Prepare the job first, then generate a tailored CV.'
            }
          />
        ) : (
          <MaterialVersionList
            jobId={jobId}
            materials={documentMaterials}
            selectedId={selectedMaterialId}
            onSelect={(id) => setSelectedMaterialId((current) => (current === id ? null : id))}
            onUpdated={(nextId) => {
              if (nextId) setSelectedMaterialId(nextId)
              materials.refetch()
            }}
            onDownloadPdf={(material) =>
              run('Download PDF', () => downloadMaterial(jobId, material.id, 'pdf'))
            }
            onDownloadTex={(material) =>
              run('Download TeX', () => downloadMaterial(jobId, material.id, 'tex'))
            }
            onDownloadMd={(material) =>
              run('Download Markdown', () => downloadMaterial(jobId, material.id, 'md'))
            }
          />
        )}
      </Panel>

      <AnswerPanel jobId={jobId} answers={applicationAnswers} onUpdated={() => materials.refetch()} />

      {/* Post-application journey: rounds, prep packs, transcripts (INT-01). */}
      <Panel title="Interview journey">
        <InterviewTimeline
          job={j}
          interviews={interviews.data ?? []}
          materials={internalMaterials}
          employerMaterialCount={documentMaterials.length}
          onChanged={() => {
            interviews.refetch()
            materials.refetch()
            job.refetch()
            audit.refetch()
          }}
        />
      </Panel>

      {/* End of the journey: record the offer, benchmark it, draft the response (OFF-01). */}
      <Panel title="Offer">
        <OfferPanel
          job={j}
          offers={offers.data ?? []}
          materials={offerMaterials}
          onChanged={() => {
            offers.refetch()
            materials.refetch()
            job.refetch()
            audit.refetch()
          }}
        />
      </Panel>

      {/* Supporting context, collapsed by default so the action + materials lead. */}
      <CollapsiblePanel title="Job summary">
        {j.job_summary ? (
          <JobSummary summary={j.job_summary} />
        ) : (
          <EmptyState message="No clean summary yet — Prepare application creates one." />
        )}
      </CollapsiblePanel>

      <CollapsiblePanel title="Outcome">
        <OutcomePanel
          job={j}
          materials={internalMaterials}
          interviews={interviews.data ?? []}
          onDone={() => {
            job.refetch()
            materials.refetch()
            audit.refetch()
          }}
        />
      </CollapsiblePanel>

      <CollapsiblePanel title="Audit timeline">
        <AuditTimeline persisted={persistedForJob} live={liveForJob} loading={audit.loading} />
      </CollapsiblePanel>
    </div>
  )
}

// A bare <details> wrapper so supporting context recedes until wanted (Apple
// deference). Title stays visible; body opens on click.
function CollapsiblePanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <details className="rounded-xl border border-border/70 bg-white/[0.02]">
      <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium hover:text-text">
        {title}
      </summary>
      <div className="border-t border-border/60 px-4 py-4">{children}</div>
    </details>
  )
}

// The full set of individual actions, tucked behind a disclosure so the primary
// flow stays uncluttered.
function MoreActions({
  state,
  disabled,
  onScore,
  onSummarize,
  onCv,
  onState,
}: {
  state: LifecycleState
  disabled: boolean
  onScore: () => void
  onSummarize: () => void
  onCv: () => void
  onState: (s: LifecycleState) => void
}) {
  const [open, setOpen] = useState(false)
  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="micro-label text-muted hover:text-text"
        type="button"
      >
        more actions
      </button>
    )
  }
  const btn = 'rounded-lg border border-border px-3 py-2 text-sm text-muted hover:text-text disabled:opacity-50'
  return (
    <div className="flex w-full flex-wrap items-center gap-2 border-t border-border/60 pt-3">
      <button onClick={onScore} disabled={disabled} className={btn}>
        Re-score
      </button>
      <button onClick={onSummarize} disabled={disabled} className={btn}>
        Clean summary
      </button>
      <button onClick={onCv} disabled={disabled} className={btn}>
        CV only
      </button>
      <select
        value={state}
        onChange={(e) => onState(e.target.value as LifecycleState)}
        disabled={disabled}
        className="rounded-lg border border-border bg-black/30 px-3 py-2 text-sm"
        aria-label="Change lifecycle state"
      >
        {LIFECYCLE_STATES.map((s) => (
          <option key={s} value={s}>
            {s.replace(/_/g, ' ')}
          </option>
        ))}
      </select>
    </div>
  )
}

function ApplicationLinkPanel({
  applicationUrl,
  onSave,
}: {
  applicationUrl: string | null
  onSave: (url: string) => Promise<void>
}) {
  const [draft, setDraft] = useState(applicationUrl ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()

  async function save() {
    const trimmed = draft.trim()
    if (!trimmed) {
      setError('Enter the job posting URL.')
      return
    }
    setBusy(true)
    setError(undefined)
    try {
      await onSave(trimmed)
    } catch {
      setError('Could not save the URL.')
    } finally {
      setBusy(false)
    }
  }

  if (applicationUrl) {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-cyan/40 bg-cyan/5 px-4 py-3">
        <a
          href={applicationUrl}
          target="_blank"
          rel="noreferrer"
          className="rounded-lg border border-cyan px-4 py-2 text-sm font-medium text-cyan hover:bg-cyan/10"
        >
          Open job posting
        </a>
        <span className="min-w-0 flex-1 truncate text-xs text-muted">{applicationUrl}</span>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-border/70 bg-white/[0.02] px-4 py-3">
      <p className="mb-2 text-sm text-muted">No posting link saved for this job.</p>
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="https://…"
          className="min-w-0 flex-1 rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
        />
        <button
          onClick={save}
          disabled={busy}
          className="rounded-lg border border-cyan px-4 py-2 text-sm text-cyan disabled:opacity-50"
        >
          {busy ? 'Saving…' : 'Save link'}
        </button>
      </div>
      {error && <p className="mt-2 text-xs text-warning">{error}</p>}
    </div>
  )
}

function OutcomePanel({
  job,
  materials,
  interviews,
  onDone,
}: {
  job: Job
  materials: GeneratedMaterial[]
  interviews: Interview[]
  onDone: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [notes, setNotes] = useState(job.outcome_notes ?? '')
  const [working, setWorking] = useState<string>()
  const eligibility = useAsyncData(() => getJourneySummaryEligibility(job.id), [
    job.id,
    job.outcome_result,
    interviews.length,
  ])

  async function update(payload: OutcomeUpdate) {
    setBusy(true)
    setError(undefined)
    try {
      await recordOutcome(job.id, payload)
      onDone()
    } catch {
      setError('Could not save the outcome update.')
    } finally {
      setBusy(false)
    }
  }

  async function saveNotes() {
    await update({ notes: notes.trim() || null })
  }

  async function runReflection() {
    setWorking('Writing rejection reflection…')
    setError(undefined)
    try {
      if (notes.trim() !== (job.outcome_notes ?? '')) {
        await recordOutcome(job.id, { notes: notes.trim() || null })
      }
      await generateRejectionReflection(job.id, notes.trim() || null)
      onDone()
    } catch (err) {
      setError(apiErrorMessage(err, 'Could not generate the rejection reflection.'))
    } finally {
      setWorking(undefined)
    }
  }

  async function runJourneySummary() {
    setWorking('Writing journey summary…')
    setError(undefined)
    try {
      await generateJourneySummary(job.id)
      onDone()
    } catch (err) {
      setError(apiErrorMessage(err, 'Could not generate the journey summary.'))
    } finally {
      setWorking(undefined)
    }
  }

  const selectClass =
    'rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan disabled:opacity-50'
  const reflections = materials.filter((m) => m.material_type === 'rejection_reflection')
  const summaries = materials.filter((m) => m.material_type === 'journey_summary')
  const showReflection =
    job.outcome_result === 'rejected' || job.outcome_result === 'withdrawn'
  const eligible = !!eligibility.data?.eligible

  return (
    <div className="flex flex-col gap-4">
      {error && <AlertBanner tone="error">{error}</AlertBanner>}
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <OutcomeField label="Stage" value={job.outcome_stage} />
        <OutcomeField label="Result" value={job.outcome_result} />
        <OutcomeDateField
          label="Applied on"
          value={job.applied_at}
          disabled={busy}
          onChange={(iso) => update({ applied_at: iso })}
        />
        <OutcomeDateField
          label="First response"
          value={job.first_response_at}
          disabled={busy}
          onChange={(iso) => update({ first_response_at: iso })}
        />
      </dl>
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={job.outcome_stage ?? ''}
          disabled={busy}
          onChange={(e) => e.target.value && update({ outcome_stage: e.target.value as OutcomeStage })}
          className={selectClass}
        >
          <option value="" disabled>
            Set stage…
          </option>
          {OUTCOME_STAGES.map((s) => (
            <option key={s} value={s}>
              {s.replace(/_/g, ' ')}
            </option>
          ))}
        </select>
        <select
          value={job.outcome_result ?? ''}
          disabled={busy}
          onChange={(e) => e.target.value && update({ outcome_result: e.target.value as OutcomeResult })}
          className={selectClass}
        >
          <option value="" disabled>
            Set result…
          </option>
          {OUTCOME_RESULTS.map((s) => (
            <option key={s} value={s}>
              {s.replace(/_/g, ' ')}
            </option>
          ))}
        </select>
        <select
          value={job.rejection_stage ?? ''}
          disabled={busy}
          onChange={(e) =>
            update({
              rejection_stage: e.target.value ? (e.target.value as OutcomeStage) : null,
            })
          }
          className={selectClass}
        >
          <option value="">Rejection stage…</option>
          {OUTCOME_STAGES.map((s) => (
            <option key={s} value={s}>
              {s.replace(/_/g, ' ')}
            </option>
          ))}
        </select>
        <button
          onClick={() => update({ first_response_at: new Date().toISOString() })}
          disabled={busy || !!job.first_response_at}
          className="rounded-lg border border-cyan px-3 py-2 text-sm text-cyan disabled:opacity-50"
        >
          {job.first_response_at ? 'Response logged' : 'Mark responded'}
        </button>
      </div>

      <label className="flex flex-col gap-1 text-xs text-muted">
        Feedback / outcome notes
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          placeholder="Paste genuine feedback, recruiter notes, or your own close-out reflection…"
          className="rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy || !!working}
          onClick={() => void saveNotes()}
          className="rounded-lg border border-border px-3 py-2 text-sm text-muted hover:text-text disabled:opacity-50"
        >
          Save notes
        </button>
        {showReflection && (
          <button
            type="button"
            disabled={busy || !!working}
            onClick={() => void runReflection()}
            className="rounded-lg border border-violet px-3 py-2 text-sm text-violet disabled:opacity-50"
          >
            {working?.includes('rejection') ? 'Writing…' : 'Generate rejection reflection'}
          </button>
        )}
        {eligible && (
          <button
            type="button"
            disabled={busy || !!working}
            onClick={() => void runJourneySummary()}
            className="rounded-lg border border-cyan px-3 py-2 text-sm text-cyan disabled:opacity-50"
          >
            {working?.includes('journey') ? 'Writing…' : 'Generate journey summary'}
          </button>
        )}
      </div>
      {eligibility.data &&
        eligibility.data.terminal_outcome &&
        !eligibility.data.eligible &&
        eligibility.data.proper_round_count < 3 && (
          <p className="text-xs text-muted">
            Journey summary unlocks after 3+ proper interview rounds (currently{' '}
            {eligibility.data.proper_round_count}).
          </p>
        )}
      {working && <p className="text-sm text-cyan">{working}</p>}

      {(reflections.length > 0 || summaries.length > 0) && (
        <div className="flex flex-col gap-2">
          <p className="micro-label">Close-out documents</p>
          {[...reflections, ...summaries].map((material) => (
            <ArtifactRow
              key={material.id}
              jobId={job.id}
              material={material}
              interviews={interviews}
              onChanged={onDone}
            />
          ))}
          <CloseoutPromoteButton jobId={job.id} onDone={onDone} />
        </div>
      )}

      <ExperienceBankForm jobId={job.id} onDone={onDone} />
    </div>
  )
}

function CloseoutPromoteButton({ jobId, onDone }: { jobId: number; onDone: () => void }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [ok, setOk] = useState<string>()
  const [candidates, setCandidates] = useState<
    { category: string; claim_text: string; source_title: string | null }[]
  >([])
  const [selected, setSelected] = useState<Record<string, boolean>>({})

  async function load() {
    setBusy(true)
    setError(undefined)
    setOk(undefined)
    try {
      const data = await listCloseoutLearnings(jobId)
      setCandidates(data.candidates)
      setSelected(Object.fromEntries(data.candidates.map((c) => [c.claim_text, true])))
      setOpen(true)
    } catch (err) {
      setError(apiErrorMessage(err, 'Could not load close-out learnings.'))
    } finally {
      setBusy(false)
    }
  }

  const chosen = candidates.filter((c) => selected[c.claim_text])

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        disabled={busy}
        onClick={() => void load()}
        className="self-start rounded-lg border border-violet px-3 py-2 text-sm text-violet disabled:opacity-50"
      >
        {busy && !open ? 'Loading…' : 'Review close-out learnings'}
      </button>
      <p className="text-xs text-muted">
        Skills practiced and next-interview playbook lines only. Gap diagnoses stay in the
        reflection. You pick which drafts land in Approve facts.
      </p>
      {open && (
        <div className="rounded-lg border border-border/70 bg-black/20 p-3">
          {candidates.length === 0 ? (
            <p className="text-xs text-muted">
              No portable skills or playbook bullets found. Add one below in the experience bank.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {candidates.map((c) => (
                <li key={c.claim_text}>
                  <label className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={!!selected[c.claim_text]}
                      onChange={(e) =>
                        setSelected((prev) => ({ ...prev, [c.claim_text]: e.target.checked }))
                      }
                      className="mt-1"
                    />
                    <span>
                      <span className="micro-label mr-2">
                        {c.category === 'process_skill' ? 'Skill' : 'Next-interview rule'}
                      </span>
                      {c.claim_text}
                      {c.source_title && (
                        <span className="mt-0.5 block text-xs text-muted">{c.source_title}</span>
                      )}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
          {candidates.length > 0 && (
            <button
              type="button"
              disabled={busy || chosen.length === 0}
              onClick={async () => {
                setBusy(true)
                setError(undefined)
                setOk(undefined)
                try {
                  const result = await promoteCloseoutLearnings(
                    jobId,
                    chosen.map((c) => c.claim_text),
                  )
                  if (result.promoted > 0) {
                    setOk(
                      `Queued ${result.promoted} draft${result.promoted === 1 ? '' : 's'} for Approve facts.`,
                    )
                  } else if (result.skipped_existing > 0) {
                    setOk('Those lines are already in Approve facts.')
                  }
                  onDone()
                } catch (err) {
                  setError(apiErrorMessage(err, 'Could not promote close-out learnings.'))
                } finally {
                  setBusy(false)
                }
              }}
              className="mt-3 self-start rounded-lg border border-cyan px-3 py-2 text-sm text-cyan disabled:opacity-50"
            >
              {busy ? 'Queuing…' : `Queue ${chosen.length} selected`}
            </button>
          )}
        </div>
      )}
      {error && <p className="text-xs text-warning">{error}</p>}
      {ok && <p className="text-xs text-emerald">{ok}</p>}
    </div>
  )
}

function ExperienceBankForm({ jobId, onDone }: { jobId: number; onDone: () => void }) {
  const [text, setText] = useState('')
  const [category, setCategory] = useState<'interview_learning' | 'process_skill'>('process_skill')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [ok, setOk] = useState<string>()

  return (
    <div className="rounded-lg border border-border/70 bg-black/20 p-3">
      <p className="text-xs text-muted">
        Add to experience bank — substantive skills practiced on this journey (e.g. Azure,
        Databricks) or process lessons. Drafts land in Approve facts before they ground future
        CVs and packs.
      </p>
      <div className="mt-2 flex flex-col gap-2 sm:flex-row">
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value as 'interview_learning' | 'process_skill')}
          className="rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
        >
          <option value="process_skill">Process skill</option>
          <option value="interview_learning">Interview learning</option>
        </select>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Practiced calibrated credit-risk modelling with XGBoost…"
          className="min-w-0 flex-1 rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
        />
        <button
          type="button"
          disabled={busy || !text.trim()}
          onClick={async () => {
            setBusy(true)
            setError(undefined)
            setOk(undefined)
            try {
              await promoteJobLearning(jobId, text.trim(), category)
              setText('')
              setOk('Queued for Approve facts.')
              onDone()
            } catch (err) {
              setError(apiErrorMessage(err, 'Could not save the learning.'))
            } finally {
              setBusy(false)
            }
          }}
          className="rounded-lg border border-cyan px-3 py-2 text-sm text-cyan disabled:opacity-50"
        >
          Add
        </button>
      </div>
      {error && <p className="mt-2 text-xs text-warning">{error}</p>}
      {ok && <p className="mt-2 text-xs text-emerald">{ok}</p>}
    </div>
  )
}

function OutcomeField({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="rounded-lg border border-border/70 bg-white/[0.02] p-3">
      <dt className="micro-label mb-1">{label}</dt>
      <dd className="leading-6 text-muted">{value ? value.replace(/_/g, ' ') : '—'}</dd>
    </div>
  )
}

function OutcomeDateField({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string
  value: string | null
  disabled: boolean
  onChange: (iso: string) => void
}) {
  return (
    <div className="rounded-lg border border-border/70 bg-white/[0.02] p-3">
      <dt className="micro-label mb-1">{label}</dt>
      <dd>
        <input
          type="date"
          value={value ? value.slice(0, 10) : ''}
          disabled={disabled}
          aria-label={label}
          onChange={(e) => {
            if (!e.target.value) return
            onChange(new Date(`${e.target.value}T12:00:00Z`).toISOString())
          }}
          className="w-full bg-transparent text-sm leading-6 text-muted outline-none [color-scheme:dark] focus:text-text disabled:opacity-50"
        />
      </dd>
    </div>
  )
}

function asText(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function asTextList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === 'string' && Boolean(item.trim()))
  }
  const text = asText(value)
  return text ? [text] : []
}

function titleize(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase())
}

function JobSummary({ summary }: { summary: Record<string, unknown> }) {
  const overview = asText(summary.role_overview)
  const responsibilities = asTextList(summary.responsibilities)
  const requirements = asTextList(summary.requirements)
  const applicationNotes = asTextList(summary.application_notes)
  const noiseRemoved = asTextList(summary.noise_removed)
  const facts = [
    ['Company domain', asText(summary.company_domain)],
    ['Location / hybrid', asText(summary.location_hybrid)],
    ['Compensation', asText(summary.compensation)],
  ].filter((entry): entry is [string, string] => entry[1] !== undefined)

  const renderedKeys = new Set([
    'role_overview',
    'responsibilities',
    'requirements',
    'company_domain',
    'location_hybrid',
    'compensation',
    'application_notes',
    'noise_removed',
  ])
  const extras = Object.entries(summary).filter(
    ([key, value]) => !renderedKeys.has(key) && value != null && value !== '',
  )

  return (
    <div className="flex flex-col gap-5 text-sm">
      {overview && <p className="max-w-5xl leading-7 text-text">{overview}</p>}

      {facts.length > 0 && (
        <dl className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {facts.map(([label, value]) => (
            <div key={label} className="rounded-lg border border-border/70 bg-white/[0.02] p-3">
              <dt className="micro-label mb-1">{label}</dt>
              <dd className="leading-6 text-muted">{value}</dd>
            </div>
          ))}
        </dl>
      )}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <SummaryList title="Responsibilities" items={responsibilities} />
        <SummaryList title="Requirements" items={requirements} />
      </div>

      {applicationNotes.length > 0 && (
        <SummaryList title="Application notes" items={applicationNotes} compact />
      )}

      {noiseRemoved.length > 0 && (
        <details className="rounded-lg border border-border/70 bg-white/[0.02] p-3">
          <summary className="cursor-pointer micro-label">Noise removed</summary>
          <ul className="mt-3 list-disc space-y-2 pl-5 text-muted">
            {noiseRemoved.map((item, index) => (
              <li key={`${index}-${item}`} className="leading-6">
                {item}
              </li>
            ))}
          </ul>
        </details>
      )}

      {extras.length > 0 && (
        <details className="rounded-lg border border-border/70 bg-white/[0.02] p-3">
          <summary className="cursor-pointer micro-label">Additional fields</summary>
          <dl className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
            {extras.map(([key, value]) => (
              <div key={key}>
                <dt className="micro-label mb-1">{titleize(key)}</dt>
                <dd className="break-words text-muted">{formatSummaryValue(value)}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </div>
  )
}

function SummaryList({
  title,
  items,
  compact = false,
}: {
  title: string
  items: string[]
  compact?: boolean
}) {
  if (items.length === 0) return null
  return (
    <section>
      <h3 className="micro-label mb-2">{title}</h3>
      <ul className={`list-disc pl-5 text-muted ${compact ? 'space-y-1' : 'space-y-2'}`}>
        {items.map((item, index) => (
          <li key={`${title}-${index}-${item}`} className="leading-6">
            {item}
          </li>
        ))}
      </ul>
    </section>
  )
}

function formatSummaryValue(value: unknown): string {
  if (Array.isArray(value)) return value.map((item) => formatSummaryValue(item)).join(', ')
  if (typeof value === 'object' && value !== null) return JSON.stringify(value)
  return String(value)
}
