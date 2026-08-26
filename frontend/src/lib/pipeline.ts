import { LIFECYCLE_STATES, type Job, type LifecycleState } from './types'

// Sort by expected_value descending, nulls last — matching the backend's
// `order_by(Job.expected_value.desc().nullslast())`.
export function byExpectedValueDesc(a: Job, b: Job): number {
  const av = a.expected_value
  const bv = b.expected_value
  if (av == null && bv == null) return 0
  if (av == null) return 1
  if (bv == null) return -1
  return bv - av
}

// Why a job is excluded from the curated pipeline board. Mirrors the backend's
// `curated=true` predicate (api/routers/jobs.py): archived, un-summarized, not
// scored, or (for auto-ingested roles only) below the fit threshold. Manual
// jobs you paste always pass the fit gate once prepared.
export function curationReason(job: Job, minFit?: number): string | null {
  if (job.lifecycle_state === 'archived') return 'archived'
  if (job.job_summary == null || job.summary_updated_at == null) return 'no clean summary'
  if (job.fit_score == null || job.expected_value == null) return 'not scored'
  if (job.source === 'manual') return null
  if (minFit != null && job.fit_score < minFit) return 'below fit threshold'
  return null
}

// Group jobs into the canonical lifecycle columns, each sorted by EV.
export function groupByState(jobs: Job[]): Record<LifecycleState, Job[]> {
  const groups = Object.fromEntries(LIFECYCLE_STATES.map((s) => [s, [] as Job[]])) as Record<
    LifecycleState,
    Job[]
  >
  for (const job of jobs) {
    ;(groups[job.lifecycle_state] ?? groups.discovered).push(job)
  }
  for (const state of LIFECYCLE_STATES) groups[state].sort(byExpectedValueDesc)
  return groups
}
