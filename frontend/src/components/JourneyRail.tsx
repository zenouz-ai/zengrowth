import { useMemo } from 'react'
import { useKnowledgeClaims } from '../hooks/useKnowledgeClaims'
import type { GeneratedMaterial, Interview, Job } from '../lib/types'
import { StateChip } from './StateChip'

// The end-to-end journey visual (INT-01/04): Applied → each round → outcome,
// as an interactive, swipeable rail with per-stage artifact counts, plus a
// stats strip and the learnings captured along the way. Nodes select the
// matching round card below for detail + files.

const ROUND_SHORT: Record<Interview['round_type'], string> = {
  recruiter_screen: 'Screen',
  hiring_manager: 'Hiring manager',
  leadership_panel: 'Leadership',
  technical: 'Technical',
  team: 'Team',
  final_round: 'Final round',
  other: 'Interview',
}

type NodeState = 'done' | 'next' | 'future' | 'cancelled' | 'offer' | 'rejected'

interface JourneyNode {
  key: string
  interviewId: number | null
  label: string
  date: string | null
  state: NodeState
  artifactCount: number
  sublabel?: string
}

function shortDate(iso: string | null | undefined): string | null {
  if (!iso) return null
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return null
  return parsed.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

function daysBetween(fromIso: string, toIso: string): number {
  return Math.max(
    0,
    Math.round((new Date(toIso).getTime() - new Date(fromIso).getTime()) / 86_400_000),
  )
}

function buildNodes(
  job: Job,
  interviews: Interview[],
  materials: GeneratedMaterial[],
  employerMaterialCount: number,
): JourneyNode[] {
  const nodes: JourneyNode[] = []
  nodes.push({
    key: 'applied',
    interviewId: null,
    label: 'Applied',
    date: shortDate(job.applied_at),
    state: job.applied_at ? 'done' : 'future',
    artifactCount: materials.filter((m) => m.interview_id == null).length,
    sublabel:
      employerMaterialCount > 0
        ? `${employerMaterialCount} document${employerMaterialCount === 1 ? '' : 's'}`
        : undefined,
  })

  let nextMarked = false
  for (const interview of interviews) {
    let state: NodeState
    if (interview.status === 'cancelled') {
      state = 'cancelled'
    } else if (interview.status === 'completed') {
      state = 'done'
    } else if (!nextMarked) {
      state = 'next'
      nextMarked = true
    } else {
      state = 'future'
    }
    nodes.push({
      key: `interview-${interview.id}`,
      interviewId: interview.id,
      label: interview.title || ROUND_SHORT[interview.round_type],
      date: shortDate(interview.occurred_at ?? interview.scheduled_at),
      state,
      artifactCount: materials.filter((m) => m.interview_id === interview.id).length,
      sublabel: interview.participants?.length
        ? `${interview.participants.length} interviewer${interview.participants.length === 1 ? '' : 's'}`
        : undefined,
    })
  }

  const offerish =
    job.outcome_result === 'offer' ||
    job.outcome_result === 'accepted' ||
    job.outcome_stage === 'offer'
  if (offerish) {
    nodes.push({
      key: 'outcome',
      interviewId: null,
      label: 'Offer',
      date: null,
      state: 'offer',
      artifactCount: 0,
    })
  } else if (job.outcome_result === 'rejected') {
    nodes.push({
      key: 'outcome',
      interviewId: null,
      label: 'Rejected',
      date: null,
      state: 'rejected',
      artifactCount: 0,
    })
  } else if (interviews.length > 0) {
    nodes.push({
      key: 'outcome',
      interviewId: null,
      label: 'Decision',
      date: null,
      state: 'future',
      artifactCount: 0,
    })
  }
  return nodes
}

const NODE_STYLE: Record<NodeState, { dot: string; glyph: string; label: string }> = {
  done: { dot: 'border-cyan bg-cyan text-black', glyph: '✓', label: 'text-text' },
  next: { dot: 'border-cyan bg-cyan/15 text-cyan animate-pulse', glyph: '●', label: 'text-cyan' },
  future: { dot: 'border-border bg-black/30 text-muted', glyph: '○', label: 'text-muted' },
  cancelled: { dot: 'border-border bg-black/30 text-muted line-through', glyph: '✕', label: 'text-muted line-through' },
  offer: { dot: 'border-emerald bg-emerald/20 text-emerald', glyph: '★', label: 'text-emerald' },
  rejected: { dot: 'border-loss bg-loss/15 text-loss', glyph: '✕', label: 'text-loss' },
}

export function JourneyRail({
  job,
  interviews,
  materials,
  employerMaterialCount,
  selectedInterviewId,
  onSelectInterview,
}: {
  job: Job
  interviews: Interview[]
  materials: GeneratedMaterial[]
  employerMaterialCount: number
  selectedInterviewId: number | null
  onSelectInterview: (interviewId: number | null) => void
}) {
  const claims = useKnowledgeClaims()
  const learnings = useMemo(
    () =>
      (claims.data ?? []).filter((claim) => {
        if (claim.category !== 'interview_learning') return false
        const tags = claim.tags ?? []
        if (tags.includes(`job-${job.id}`)) return true
        // Legacy learnings tagged by company only (before job-scoped tags).
        return tags.includes(job.company) && !tags.some((t) => t.startsWith('job-'))
      }),
    [claims.data, job.id, job.company],
  )

  const nodes = useMemo(
    () => buildNodes(job, interviews, materials, employerMaterialCount),
    [job, interviews, materials, employerMaterialCount],
  )

  const completedRounds = interviews.filter((i) => i.status === 'completed').length
  const debriefs = materials.filter((m) => m.material_type === 'debrief').length
  const packs = materials.filter(
    (m) => m.material_type !== 'debrief' && m.material_type !== 'email_draft',
  ).length
  const lastEvent = interviews
    .map((i) => i.occurred_at ?? i.scheduled_at)
    .filter((d): d is string => !!d)
    .sort()
    .at(-1)
  const daysInProcess =
    job.applied_at && lastEvent ? daysBetween(job.applied_at, lastEvent) : null

  if (interviews.length === 0 && !job.applied_at) return null

  return (
    <div className="flex flex-col gap-4">
      {/* Stats strip — the journey at a glance. */}
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <JourneyStat label="Days in process" value={daysInProcess != null ? String(daysInProcess) : '—'} />
        <JourneyStat label="Rounds completed" value={String(completedRounds)} />
        <JourneyStat label="Prep packs" value={String(packs)} />
        <JourneyStat label="Debriefs" value={String(debriefs)} />
      </dl>

      {/* The rail: swipeable on mobile, full-width on desktop. */}
      <div
        className="-mx-1 overflow-x-auto px-1 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        role="tablist"
        aria-label="Application journey"
      >
        <ol className="flex min-w-max items-start">
          {nodes.map((node, index) => {
            const style = NODE_STYLE[node.state]
            const selected =
              node.interviewId != null && node.interviewId === selectedInterviewId
            const clickable = node.interviewId != null
            const reached = node.state === 'done' || node.state === 'offer'
            return (
              <li key={node.key} className="flex snap-start items-start">
                {index > 0 && (
                  <span
                    aria-hidden
                    className={`mt-[21px] h-px w-6 shrink-0 sm:w-12 ${
                      reached || node.state === 'next' ? 'bg-cyan/60' : 'bg-border'
                    }`}
                  />
                )}
                <button
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  disabled={!clickable}
                  onClick={() =>
                    clickable &&
                    onSelectInterview(selected ? null : node.interviewId)
                  }
                  className={`group flex w-[92px] flex-col items-center gap-1.5 rounded-xl px-1 py-2 text-center transition-all sm:w-[108px] ${
                    selected ? 'bg-cyan/10 ring-1 ring-cyan/60' : clickable ? 'hover:bg-white/[0.04]' : ''
                  }`}
                >
                  <span
                    aria-hidden
                    className={`flex h-[26px] w-[26px] items-center justify-center rounded-full border text-[11px] font-semibold transition-transform group-hover:scale-110 ${style.dot}`}
                  >
                    {style.glyph}
                  </span>
                  <span className={`w-full truncate text-xs font-medium leading-4 ${style.label}`}>
                    {node.label}
                  </span>
                  <span className="font-mono text-[10px] leading-3 text-muted">
                    {node.date ?? ' '}
                  </span>
                  {(node.artifactCount > 0 || node.sublabel) && (
                    <span className="text-[10px] leading-3 text-muted">
                      {node.artifactCount > 0
                        ? `${node.artifactCount} file${node.artifactCount === 1 ? '' : 's'}`
                        : node.sublabel}
                    </span>
                  )}
                </button>
              </li>
            )
          })}
        </ol>
      </div>

      {/* Learnings captured across the journey (INT-04). */}
      {learnings.length > 0 && (
        <details className="rounded-lg border border-border/70 bg-white/[0.02] px-3 py-2">
          <summary className="cursor-pointer select-none text-sm text-muted hover:text-text">
            <span className="font-medium text-text">{learnings.length}</span> learning
            {learnings.length === 1 ? '' : 's'} captured from this process
          </summary>
          <ul className="mt-2 flex flex-col gap-2">
            {learnings.map((claim) => (
              <li key={claim.id} className="flex items-start gap-2 text-sm">
                <StateChip
                  state={claim.verification_state === 'verified' ? 'verified' : 'draft'}
                  className="mt-0.5 shrink-0"
                />
                <span className="leading-6 text-text/90">{claim.claim_text}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function JourneyStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border/70 bg-white/[0.02] px-3 py-2">
      <dt className="micro-label">{label}</dt>
      <dd className="mt-0.5 font-heading text-lg font-semibold leading-6">{value}</dd>
    </div>
  )
}
