import { useState } from 'react'
import { AlertBanner } from './AlertBanner'
import { ArtifactRow } from './ArtifactRow'
import { EmptyState } from './EmptyState'
import { JourneyRail } from './JourneyRail'
import { toIso } from '../lib/dates'
import { useAsyncData } from '../hooks/useAsyncData'
import {
  apiErrorMessage,
  createInterview,
  deleteInterview,
  generateDebrief,
  generateEmailDraft,
  generatePack,
  generateSimPrompt,
  getInterview,
  importMaterial,
  promoteLearning,
  setInterviewTranscript,
  updateInterview,
} from '../lib/api'
import { materialTypeLabel } from '../lib/materialLabels'
import {
  INTERNAL_MATERIAL_TYPES,
  INTERVIEW_FORMATS,
  INTERVIEW_ROUND_TYPES,
  INTERVIEW_STATUSES,
  type GeneratedMaterial,
  type InternalMaterialType,
  type Interview,
  type InterviewFormat,
  type InterviewRoundType,
  type InterviewStatus,
  type Job,
  type PackType,
} from '../lib/types'

const ROUND_LABELS: Record<InterviewRoundType, string> = {
  recruiter_screen: 'Recruiter screen',
  hiring_manager: 'Hiring manager',
  leadership_panel: 'Leadership panel',
  technical: 'Technical',
  team: 'Team',
  final_round: 'Final round',
  other: 'Interview',
}

// Rounds carry no fixed sequence — any type, any order, any count; the
// timeline sorts by when each round actually happened. Formats read naturally
// whatever the medium.
const FORMAT_OPTION_LABELS: Record<InterviewFormat, string> = {
  phone: 'Phone call',
  video: 'Video (Teams / Zoom / Meet)',
  onsite: 'In person',
  other: 'Other',
}

const FORMAT_SHORT_LABELS: Record<InterviewFormat, string> = {
  phone: 'phone',
  video: 'video',
  onsite: 'in person',
  other: '',
}

function eventDate(interview: Interview): string | null {
  const raw = interview.occurred_at ?? interview.scheduled_at
  return raw ? raw.slice(0, 10) : null
}

/** Default prep-pack type for a round: technical/final get specialised packs,
 * named panels get the interviewer pack, anything else the company briefing. */
function defaultPackFor(interview: Interview): PackType {
  if (interview.round_type === 'technical') return 'tech_prep_pack'
  if (interview.round_type === 'final_round') return 'final_round_pack'
  if (interview.participants && interview.participants.length > 0) return 'interviewer_pack'
  return 'company_briefing'
}

const PACK_BUTTON_LABELS: Record<PackType, string> = {
  company_briefing: 'Regenerate foundation briefing',
  interviewer_pack: 'Prep for this round',
  tech_prep_pack: 'Prep for this round',
  final_round_pack: 'Prep for this round',
}

function findImportedPack(
  materials: GeneratedMaterial[],
  interview: Interview,
  packType: PackType,
): GeneratedMaterial | undefined {
  return materials.find(
    (m) =>
      m.status === 'imported' &&
      m.material_type === packType &&
      (m.interview_id === interview.id || m.interview_id == null),
  )
}

function findJobImportedFoundation(materials: GeneratedMaterial[]): GeneratedMaterial | undefined {
  return materials.find(
    (m) =>
      m.status === 'imported' &&
      m.material_type === 'company_briefing' &&
      m.interview_id == null,
  )
}

function parseParticipants(text: string): { name: string; role?: string }[] | null {
  const rows = text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [name, ...roleParts] = line.split(/\s*[-–—]\s+/)
      const role = roleParts.join(' - ').trim()
      return role ? { name: name.trim(), role } : { name: name.trim() }
    })
    .filter((row) => row.name)
  return rows.length ? rows : null
}

export function InterviewTimeline({
  job,
  interviews,
  materials,
  employerMaterialCount = 0,
  onChanged,
}: {
  job: Job
  interviews: Interview[]
  materials: GeneratedMaterial[]
  employerMaterialCount?: number
  onChanged: () => void
}) {
  const jobId = job.id
  const [error, setError] = useState<string>()
  const [adding, setAdding] = useState(false)
  const [importingFor, setImportingFor] = useState<number | 'job' | null>(null)
  const [generating, setGenerating] = useState<number | 'job' | null>(null)
  const [generatingKind, setGeneratingKind] = useState<'pack' | 'debrief' | null>(null)
  const [draftingEmail, setDraftingEmail] = useState(false)
  const [selectedRound, setSelectedRound] = useState<number | null>(null)

  function selectRound(interviewId: number | null) {
    setSelectedRound(interviewId)
    if (interviewId != null) {
      // Bring the matching round card into view beneath the rail.
      requestAnimationFrame(() => {
        document
          .getElementById(`interview-card-${interviewId}`)
          ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      })
    }
  }

  async function guard(fn: () => Promise<unknown>, fallback: string) {
    setError(undefined)
    try {
      await fn()
      onChanged()
      return true
    } catch (err) {
      setError(apiErrorMessage(err, fallback))
      return false
    }
  }

  async function runPack(
    packType: PackType,
    interviewId: number | null,
    opts?: { enhance?: boolean; sourceMaterialId?: number },
  ) {
    setGeneratingKind('pack')
    setGenerating(interviewId ?? 'job')
    try {
      await guard(
        () => generatePack(jobId, packType, interviewId, opts),
        'Could not generate the pack — try again or check Setup for your Claude key.',
      )
    } finally {
      setGenerating(null)
      setGeneratingKind(null)
    }
  }

  async function runDebrief(interviewId: number) {
    setGeneratingKind('debrief')
    setGenerating(interviewId)
    try {
      await guard(
        () => generateDebrief(jobId, interviewId),
        'Could not generate the debrief — paste the transcript or notes first.',
      )
    } finally {
      setGenerating(null)
      setGeneratingKind(null)
    }
  }

  const jobLevelPacks = materials.filter((m) => m.interview_id == null)

  return (
    <div className="flex flex-col gap-4">
      {error && <AlertBanner tone="error">{error}</AlertBanner>}

      {/* End-to-end journey visual: stages, milestones, files, learnings. */}
      <JourneyRail
        job={job}
        interviews={interviews}
        materials={materials}
        employerMaterialCount={employerMaterialCount}
        selectedInterviewId={selectedRound}
        onSelectInterview={selectRound}
      />

      {interviews.length === 0 && jobLevelPacks.length === 0 && (
        <EmptyState message="No interviews recorded yet. Add a round when you're invited — dates can be in the past, so a finished process can be recorded too." />
      )}

      {jobLevelPacks.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="micro-label">Job-level packs</p>
          {jobLevelPacks.map((material) => (
            <ArtifactRow key={material.id} jobId={jobId} material={material} />
          ))}
        </div>
      )}

      {interviews.length > 0 && (
        <ol className="relative flex flex-col gap-4 border-l border-border/70 pl-4">
          {interviews.map((interview) => (
            <InterviewCard
              key={interview.id}
              jobId={jobId}
              interview={interview}
              artifacts={materials.filter((m) => m.interview_id === interview.id)}
              onGuard={guard}
              importing={importingFor === interview.id}
              onToggleImport={() =>
                setImportingFor((current) => (current === interview.id ? null : interview.id))
              }
              onImported={() => {
                setImportingFor(null)
                onChanged()
              }}
              generating={generating === interview.id}
              anyGenerating={generating !== null}
              onGeneratePack={(packType, opts) => runPack(packType, interview.id, opts)}
              importedPack={findImportedPack(materials, interview, defaultPackFor(interview))}
              onGenerateDebrief={() => runDebrief(interview.id)}
              selected={selectedRound === interview.id}
            />
          ))}
        </ol>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setAdding((v) => !v)}
          className="rounded-lg border border-cyan bg-cyan/10 px-3 py-2 text-sm font-medium text-cyan"
        >
          {adding ? 'Cancel' : 'Add interview round'}
        </button>
        <button
          type="button"
          disabled={generating !== null}
          onClick={() => runPack('company_briefing', null)}
          className="rounded-lg border border-violet bg-violet/10 px-3 py-2 text-sm font-medium text-violet disabled:opacity-50"
        >
          {generating === 'job' ? 'Researching…' : 'Regenerate foundation briefing'}
        </button>
        {findJobImportedFoundation(materials) && (
          <button
            type="button"
            disabled={generating !== null}
            onClick={() =>
              runPack('company_briefing', null, {
                enhance: true,
                sourceMaterialId: findJobImportedFoundation(materials)!.id,
              })
            }
            title="Keep your imported research skeleton; add evidence citations and net-new sources"
            className="rounded-lg border border-violet px-3 py-2 text-sm text-violet disabled:opacity-50"
          >
            {generating === 'job' ? 'Enhancing…' : 'Enhance foundation with ZenGrowth'}
          </button>
        )}
        <button
          type="button"
          onClick={() => setDraftingEmail((v) => !v)}
          className="rounded-lg border border-border px-3 py-2 text-sm text-muted hover:text-text"
        >
          {draftingEmail ? 'Cancel email draft' : 'Draft an email'}
        </button>
        <button
          type="button"
          onClick={() => setImportingFor((current) => (current === 'job' ? null : 'job'))}
          className="rounded-lg border border-border px-3 py-2 text-sm text-muted hover:text-text"
        >
          {importingFor === 'job' ? 'Cancel import' : 'Import a pack or note'}
        </button>
      </div>

      {draftingEmail && (
        <EmailDraftForm
          onSubmit={async (payload) => {
            const ok = await guard(
              () => generateEmailDraft(jobId, payload),
              'Could not draft the email.',
            )
            if (ok) setDraftingEmail(false)
          }}
        />
      )}

      {generating !== null && (
        <p className="flex items-center gap-2 text-sm text-cyan">
          <span className="h-2 w-2 animate-pulse rounded-full bg-cyan" />
          {generatingKind === 'debrief'
            ? 'Writing the debrief — this can take a minute…'
            : 'Researching and writing the pack — this can take a minute…'}
        </p>
      )}

      {adding && (
        <AddRoundForm
          onSubmit={async (payload) => {
            const created = await createInterview(jobId, payload)
            onChanged()
            setAdding(false)
            selectRound(created.id)
            return true
          }}
        />
      )}

      {importingFor === 'job' && (
        <ImportArtifactForm
          onSubmit={async (payload) => {
            const ok = await guard(
              () => importMaterial(jobId, payload),
              'Could not import the document.',
            )
            if (ok) setImportingFor(null)
            return ok
          }}
        />
      )}
    </div>
  )
}

function InterviewCard({
  jobId,
  interview,
  artifacts,
  onGuard,
  importing,
  onToggleImport,
  onImported,
  generating,
  anyGenerating,
  onGeneratePack,
  onGenerateDebrief,
  selected = false,
  importedPack,
}: {
  jobId: number
  interview: Interview
  artifacts: GeneratedMaterial[]
  onGuard: (fn: () => Promise<unknown>, fallback: string) => Promise<boolean>
  importing: boolean
  onToggleImport: () => void
  onImported: () => void
  generating: boolean
  anyGenerating: boolean
  onGeneratePack: (
    packType: PackType,
    opts?: { enhance?: boolean; sourceMaterialId?: number },
  ) => void
  onGenerateDebrief: () => void
  selected?: boolean
  importedPack?: GeneratedMaterial
}) {
  const [showTranscript, setShowTranscript] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [savingLearning, setSavingLearning] = useState(false)
  const [editingDates, setEditingDates] = useState(false)
  const date = eventDate(interview)
  const upcoming = interview.status === 'scheduled'

  return (
    <li
      id={`interview-card-${interview.id}`}
      className={`relative rounded-lg border bg-white/[0.02] p-3 transition-shadow ${
        selected ? 'border-cyan/60 ring-1 ring-cyan/50' : 'border-border/70'
      }`}
    >
      <span
        className={`absolute -left-[21px] top-4 h-2.5 w-2.5 rounded-full ${
          upcoming ? 'border border-cyan bg-black' : 'bg-cyan'
        }`}
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium">
            {interview.title || ROUND_LABELS[interview.round_type]}
            <span className="ml-2 text-xs uppercase tracking-wide text-muted">
              {ROUND_LABELS[interview.round_type]}
              {FORMAT_SHORT_LABELS[interview.format] && ` · ${FORMAT_SHORT_LABELS[interview.format]}`}
            </span>
          </p>
          <p className="text-xs text-muted">
            {date ?? 'No date yet'}
            {upcoming ? ' · scheduled' : interview.status === 'cancelled' ? ' · cancelled' : ''}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={interview.status}
            onChange={(e) =>
              onGuard(
                () =>
                  updateInterview(jobId, interview.id, {
                    status: e.target.value as InterviewStatus,
                  }),
                'Could not update the round.',
              )
            }
            className="rounded-lg border border-border bg-black/30 px-2.5 py-1.5 text-xs"
            aria-label="Interview status"
          >
            {INTERVIEW_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          {confirmDelete ? (
            <span className="flex items-center gap-1 text-xs">
              <button
                type="button"
                onClick={() =>
                  onGuard(
                    () => deleteInterview(jobId, interview.id),
                    'Could not delete the round.',
                  )
                }
                className="rounded border border-warning px-3 py-2 text-warning"
              >
                Delete
              </button>
              <button
                type="button"
                onClick={() => setConfirmDelete(false)}
                className="rounded border border-border px-3 py-2 text-muted"
              >
                Keep
              </button>
            </span>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmDelete(true)}
              className="text-xs text-muted hover:text-warning"
              aria-label="Delete round"
            >
              remove
            </button>
          )}
        </div>
      </div>

      {interview.participants && interview.participants.length > 0 && (
        <p className="mt-2 text-xs text-muted">
          With:{' '}
          {interview.participants
            .map((p) => (p.role ? `${p.name} (${p.role})` : p.name))
            .join(', ')}
        </p>
      )}
      {interview.notes && <p className="mt-2 text-sm text-muted">{interview.notes}</p>}

      {artifacts.length > 0 && (
        <div className="mt-3 flex flex-col gap-2">
          {artifacts.map((material) => (
            <ArtifactRow key={material.id} jobId={jobId} material={material} />
          ))}
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2 text-xs">
        <button
          type="button"
          disabled={anyGenerating}
          onClick={() => onGeneratePack(defaultPackFor(interview))}
          className="rounded-lg border border-violet px-3 py-2 text-violet disabled:opacity-50"
        >
          {generating ? 'Researching…' : PACK_BUTTON_LABELS[defaultPackFor(interview)]}
        </button>
        {importedPack && (
          <button
            type="button"
            disabled={anyGenerating}
            onClick={() =>
              onGeneratePack(defaultPackFor(interview), {
                enhance: true,
                sourceMaterialId: importedPack.id,
              })
            }
            title="Keep your imported pack skeleton; add evidence citations and net-new sources"
            className="rounded-lg border border-violet px-3 py-2 text-violet disabled:opacity-50"
          >
            {generating ? 'Enhancing…' : 'Enhance with ZenGrowth'}
          </button>
        )}
        <button
          type="button"
          disabled={anyGenerating || !interview.can_debrief}
          onClick={onGenerateDebrief}
          title={
            interview.can_debrief
              ? 'Turn the transcript or notes into a structured debrief'
              : 'Add notes on the round or paste a transcript first'
          }
          className="rounded-lg border border-violet px-3 py-2 text-violet disabled:opacity-50"
        >
          Generate debrief
        </button>
        <button
          type="button"
          disabled={anyGenerating}
          onClick={() =>
            onGuard(
              () => generateSimPrompt(jobId, interview.id),
              'Could not create the simulator prompt.',
            )
          }
          title="Compose a mock-interviewer prompt to paste into a voice assistant (no LLM cost)"
          className="rounded-lg border border-border px-3 py-2 text-muted hover:text-text disabled:opacity-50"
        >
          Simulator prompt
        </button>
        <button
          type="button"
          onClick={() => setEditingDates((v) => !v)}
          className="rounded-lg border border-border px-3 py-2 text-muted hover:text-text"
        >
          {editingDates ? 'Cancel date edit' : 'Edit dates'}
        </button>
        <button
          type="button"
          onClick={() => setShowTranscript((v) => !v)}
          className="rounded-lg border border-border px-3 py-2 text-muted hover:text-text"
        >
          {showTranscript
            ? 'Hide transcript'
            : interview.has_transcript
              ? 'View / update transcript'
              : 'Paste transcript or notes'}
        </button>
        <button
          type="button"
          onClick={onToggleImport}
          className="rounded-lg border border-border px-3 py-2 text-muted hover:text-text"
        >
          {importing ? 'Cancel import' : 'Attach a pack / debrief'}
        </button>
        <button
          type="button"
          onClick={() => setSavingLearning((v) => !v)}
          className="rounded-lg border border-border px-3 py-2 text-muted hover:text-text"
        >
          {savingLearning ? 'Cancel' : 'Save a learning'}
        </button>
      </div>

      {savingLearning && (
        <LearningForm
          jobId={jobId}
          interviewId={interview.id}
          onSaved={() => {
            setSavingLearning(false)
            onImported()
          }}
        />
      )}

      {editingDates && (
        <EditRoundDatesForm
          interview={interview}
          onSubmit={async (payload) => {
            const ok = await onGuard(
              () => updateInterview(jobId, interview.id, payload),
              'Could not update the round dates.',
            )
            if (ok) setEditingDates(false)
            return ok
          }}
        />
      )}

      {showTranscript && (
        <TranscriptEditor
          jobId={jobId}
          interviewId={interview.id}
          onSaved={() => {
            setShowTranscript(false)
            onImported()
          }}
        />
      )}

      {importing && (
        <ImportArtifactForm
          interviewId={interview.id}
          onSubmit={async (payload) => {
            const ok = await onGuard(
              () => importMaterial(jobId, payload),
              'Could not import the document.',
            )
            if (ok) onImported()
            return ok
          }}
        />
      )}
    </li>
  )
}

function LearningForm({
  jobId,
  interviewId,
  onSaved,
}: {
  jobId: number
  interviewId: number
  onSaved: () => void
}) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string>()

  return (
    <div className="mt-3 flex flex-col gap-2">
      <p className="text-xs text-muted">
        Save a durable insight from this round (e.g. "prepare a crisper answer on GenAI
        governance ROI"). It joins the <strong>Approve facts</strong> queue as a draft — once you
        verify it there, future prep packs across all your applications reuse it.
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={2}
        placeholder="What did this round teach you?"
        className="w-full rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
      />
      {error && <p className="text-xs text-warning">{error}</p>}
      {saved ? (
        <p className="text-xs text-emerald">Saved — review it in Approve facts.</p>
      ) : (
        <button
          type="button"
          disabled={busy}
          onClick={async () => {
            if (!text.trim()) {
              setError('Write the learning first.')
              return
            }
            setBusy(true)
            setError(undefined)
            try {
              await promoteLearning(jobId, interviewId, text.trim())
              setSaved(true)
              setTimeout(onSaved, 1500)
            } catch (err) {
              setError(apiErrorMessage(err, 'Could not save the learning.'))
            } finally {
              setBusy(false)
            }
          }}
          className="self-start rounded-lg border border-cyan px-3 py-2 text-sm text-cyan disabled:opacity-50"
        >
          {busy ? 'Saving…' : 'Queue for review'}
        </button>
      )}
    </div>
  )
}

function TranscriptEditor({
  jobId,
  interviewId,
  onSaved,
}: {
  jobId: number
  interviewId: number
  onSaved: () => void
}) {
  const existing = useAsyncData(() => getInterview(jobId, interviewId), [jobId, interviewId])
  const [draft, setDraft] = useState<string>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const value = draft ?? existing.data?.transcript ?? ''

  async function save() {
    if (!value.trim()) {
      setError('Paste the transcript or meeting notes first.')
      return
    }
    setBusy(true)
    setError(undefined)
    try {
      await setInterviewTranscript(jobId, interviewId, value)
      onSaved()
    } catch (err) {
      setError(apiErrorMessage(err, 'Could not save the transcript.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-3 flex flex-col gap-2">
      <textarea
        value={value}
        onChange={(e) => setDraft(e.target.value)}
        rows={8}
        placeholder="Paste the interview transcript or your meeting notes…"
        className="w-full rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
      />
      {error && <p className="text-xs text-warning">{error}</p>}
      <button
        type="button"
        onClick={save}
        disabled={busy}
        className="self-start rounded-lg border border-cyan px-3 py-2 text-sm text-cyan disabled:opacity-50"
      >
        {busy ? 'Saving…' : 'Save transcript'}
      </button>
    </div>
  )
}

function AddRoundForm({
  onSubmit,
}: {
  onSubmit: (payload: {
    round_type: InterviewRoundType
    title: string | null
    format: InterviewFormat
    status: InterviewStatus
    scheduled_at: string | null
    occurred_at: string | null
    participants: { name: string; role?: string }[] | null
    notes: string | null
    transcript: string | null
  }) => Promise<boolean>
}) {
  const [roundType, setRoundType] = useState<InterviewRoundType>('recruiter_screen')
  const [title, setTitle] = useState('')
  const [format, setFormat] = useState<InterviewFormat>('video')
  const [status, setStatus] = useState<InterviewStatus>('scheduled')
  const [date, setDate] = useState('')
  const [participants, setParticipants] = useState('')
  const [notes, setNotes] = useState('')
  const [transcript, setTranscript] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()

  const inputClass =
    'rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan'

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border/70 bg-white/[0.02] p-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs text-muted">
          Round type
          <select
            value={roundType}
            onChange={(e) => setRoundType(e.target.value as InterviewRoundType)}
            className={inputClass}
          >
            {INTERVIEW_ROUND_TYPES.map((t) => (
              <option key={t} value={t}>
                {ROUND_LABELS[t]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Title (optional)
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. CDO + CIO final round"
            className={inputClass}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Format
          <select
            value={format}
            onChange={(e) => setFormat(e.target.value as InterviewFormat)}
            className={inputClass}
          >
            {INTERVIEW_FORMATS.map((f) => (
              <option key={f} value={f}>
                {FORMAT_OPTION_LABELS[f]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Status
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as InterviewStatus)}
            className={inputClass}
          >
            {INTERVIEW_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Date (past dates are fine — the timeline is backdatable)
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={inputClass} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Participants (one per line: Name — Role)
          <textarea
            value={participants}
            onChange={(e) => setParticipants(e.target.value)}
            rows={2}
            className={inputClass}
          />
        </label>
      </div>
      <label className="flex flex-col gap-1 text-xs text-muted">
        Round notes (brief)
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className={inputClass} />
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted">
        Interview script / transcript (optional)
        <textarea
          value={transcript}
          onChange={(e) => setTranscript(e.target.value)}
          rows={8}
          placeholder="Paste the interview script, transcript, or detailed meeting notes…"
          className={inputClass}
        />
      </label>
      {error && <p className="text-xs text-warning">{error}</p>}
      <button
        type="button"
        disabled={busy}
        onClick={async () => {
          setBusy(true)
          setError(undefined)
          try {
            const iso = toIso(date)
            const ok = await onSubmit({
              round_type: roundType,
              title: title.trim() || null,
              format,
              status,
              scheduled_at: iso,
              occurred_at: status === 'completed' ? iso : null,
              participants: parseParticipants(participants),
              notes: notes.trim() || null,
              transcript: transcript.trim() || null,
            })
            if (ok) {
              setTitle('')
              setNotes('')
              setTranscript('')
              setParticipants('')
              setDate('')
            }
          } catch (err) {
            setError(apiErrorMessage(err, 'Could not add the interview round.'))
          } finally {
            setBusy(false)
          }
        }}
        className="self-start rounded-lg border border-cyan bg-cyan/10 px-4 py-2 text-sm font-medium text-cyan disabled:opacity-50"
      >
        {busy ? 'Saving…' : 'Save round'}
      </button>
    </div>
  )
}

function EditRoundDatesForm({
  interview,
  onSubmit,
}: {
  interview: Interview
  onSubmit: (payload: {
    scheduled_at: string | null
    occurred_at: string | null
    sync_outcome: false
  }) => Promise<boolean>
}) {
  const initial = eventDate(interview) ?? ''
  const [scheduled, setScheduled] = useState(initial)
  const [occurred, setOccurred] = useState(
    interview.occurred_at ? interview.occurred_at.slice(0, 10) : initial,
  )
  const [busy, setBusy] = useState(false)
  const inputClass =
    'rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan'

  return (
    <div className="mt-3 flex flex-col gap-3 rounded-lg border border-border/70 bg-white/[0.02] p-4">
      <p className="text-xs text-muted">
        Correct when this round happened. Domain dates backdate; audit timestamps stay honest.
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs text-muted">
          Scheduled date
          <input
            type="date"
            value={scheduled}
            onChange={(e) => setScheduled(e.target.value)}
            className={inputClass}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Occurred date (completed rounds)
          <input
            type="date"
            value={occurred}
            onChange={(e) => setOccurred(e.target.value)}
            className={inputClass}
          />
        </label>
      </div>
      <button
        type="button"
        disabled={busy}
        onClick={async () => {
          setBusy(true)
          try {
            await onSubmit({
              scheduled_at: toIso(scheduled),
              occurred_at: interview.status === 'completed' ? toIso(occurred || scheduled) : null,
              sync_outcome: false,
            })
          } finally {
            setBusy(false)
          }
        }}
        className="self-start rounded-lg border border-cyan px-3 py-2 text-sm text-cyan disabled:opacity-50"
      >
        {busy ? 'Saving…' : 'Save dates'}
      </button>
    </div>
  )
}

function EmailDraftForm({
  onSubmit,
}: {
  onSubmit: (payload: { instructions?: string; inbound_email?: string }) => Promise<void>
}) {
  const [inbound, setInbound] = useState('')
  const [instructions, setInstructions] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()

  const inputClass =
    'rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan'

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border/70 bg-white/[0.02] p-4">
      <p className="text-xs text-muted">
        Paste the email you received and/or say what your email should do (e.g. "accept and
        propose Thursday", "thank-you follow-up saying I'm keen to progress"). The draft is
        saved here — nothing is sent by ZenGrowth.
      </p>
      <label className="flex flex-col gap-1 text-xs text-muted">
        Email you received (optional)
        <textarea
          value={inbound}
          onChange={(e) => setInbound(e.target.value)}
          rows={5}
          className={inputClass}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted">
        What should the email do?
        <input
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          placeholder="e.g. Reply accepting, propose Tuesday or Thursday morning"
          className={inputClass}
        />
      </label>
      {error && <p className="text-xs text-warning">{error}</p>}
      <button
        type="button"
        disabled={busy}
        onClick={async () => {
          if (!inbound.trim() && !instructions.trim()) {
            setError('Paste the email or describe what to write.')
            return
          }
          setBusy(true)
          setError(undefined)
          try {
            await onSubmit({
              inbound_email: inbound.trim() || undefined,
              instructions: instructions.trim() || undefined,
            })
          } finally {
            setBusy(false)
          }
        }}
        className="self-start rounded-lg border border-cyan bg-cyan/10 px-4 py-2 text-sm font-medium text-cyan disabled:opacity-50"
      >
        {busy ? 'Drafting…' : 'Draft email'}
      </button>
    </div>
  )
}

function ImportArtifactForm({
  interviewId,
  onSubmit,
}: {
  interviewId?: number
  onSubmit: (payload: {
    material_type: InternalMaterialType
    title: string
    content: string
    interview_id?: number | null
    effective_date?: string | null
  }) => Promise<boolean>
}) {
  const [materialType, setMaterialType] = useState<InternalMaterialType>('company_briefing')
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [date, setDate] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()

  const inputClass =
    'rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan'

  return (
    <div className="mt-3 flex flex-col gap-3 rounded-lg border border-border/70 bg-white/[0.02] p-4">
      <p className="text-xs text-muted">
        File an existing document — a research pack, debrief, or email you already have — as a
        dated artifact. Paste Obsidian-export markdown; YAML frontmatter and callouts are preserved.
        Set the date it was originally created to keep the timeline honest.
        {interviewId != null ? (
          <>
            {' '}
            This import will link to the selected round so prep packs and debriefs can reuse it in
            the learning loop.
          </>
        ) : (
          <>
            {' '}
            For round-specific packs, import from the round card so the artifact links to that
            interview (learning loop and timeline dedup depend on it).
          </>
        )}
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-xs text-muted">
          Type
          <select
            value={materialType}
            onChange={(e) => setMaterialType(e.target.value as InternalMaterialType)}
            className={inputClass}
          >
            {INTERNAL_MATERIAL_TYPES.map((t) => (
              <option key={t} value={t}>
                {materialTypeLabel(t)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted sm:col-span-2">
          Title
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Intact research pack"
            className={inputClass}
          />
        </label>
      </div>
      <label className="flex flex-col gap-1 text-xs text-muted">
        Content (Markdown)
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={8}
          placeholder="Paste the document…"
          className={inputClass}
        />
      </label>
      <label className="flex max-w-xs flex-col gap-1 text-xs text-muted">
        Original date (optional)
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={inputClass} />
      </label>
      {error && <p className="text-xs text-warning">{error}</p>}
      <button
        type="button"
        disabled={busy}
        onClick={async () => {
          if (!title.trim() || !content.trim()) {
            setError('Add a title and paste the document content.')
            return
          }
          setBusy(true)
          setError(undefined)
          try {
            const ok = await onSubmit({
              material_type: materialType,
              title: title.trim(),
              content,
              interview_id: interviewId ?? null,
              effective_date: toIso(date),
            })
            if (ok) {
              setTitle('')
              setContent('')
              setDate('')
            }
          } finally {
            setBusy(false)
          }
        }}
        className="self-start rounded-lg border border-cyan bg-cyan/10 px-4 py-2 text-sm font-medium text-cyan disabled:opacity-50"
      >
        {busy ? 'Importing…' : 'Import document'}
      </button>
    </div>
  )
}
