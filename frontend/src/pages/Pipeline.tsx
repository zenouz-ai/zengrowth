import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertBanner } from '../components/AlertBanner'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { Skeleton } from '../components/Skeleton'
import { StatusPill } from '../components/StatusPill'
import { useAsyncData } from '../hooks/useAsyncData'
import { listJobs } from '../lib/api'
import { curationReason, groupByState } from '../lib/pipeline'
import { NAV } from '../lib/navLabels'
import { LIFECYCLE_STATES, type Job } from '../lib/types'

function JobCard({ job }: { job: Job }) {
  return (
    <Link to={`/jobs/${job.id}`} className="glass block px-3 py-2 hover:border-cyan">
      <div className="truncate text-sm font-medium">{job.company}</div>
      <div className="truncate text-xs text-muted">{job.title}</div>
      <div className="mt-1 flex gap-3 text-xs">
        <span className="text-cyan">Priority {job.expected_value?.toFixed(1) ?? '—'}</span>
        <span className="text-muted">fit {job.fit_score?.toFixed(0) ?? '—'}</span>
      </div>
    </Link>
  )
}

export function Pipeline() {
  const curated = useAsyncData(() => listJobs({ curated: true }), [], { refreshInterval: 30_000 })
  const [showHidden, setShowHidden] = useState(false)
  // The unfiltered set lets us show exactly what curation removed and why — but
  // it is only fetched once the operator chooses to audit, so the common path
  // loads a single curated request.
  const all = useAsyncData(
    () => (showHidden ? listJobs() : Promise.resolve(null)),
    [showHidden],
  )

  if (curated.loading && !curated.data) {
    return (
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-32" />
        ))}
      </div>
    )
  }

  const groups = groupByState(curated.data ?? [])
  const curatedIds = new Set((curated.data ?? []).map((j) => j.id))
  const hidden = (all.data ?? []).filter((j) => !curatedIds.has(j.id))

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title={NAV.jobs.label}
        description="Your curated job board — scored roles grouped by lifecycle stage and sorted by priority score. Click a job to see why it scored, generate a CV or cover letter, and track the outcome."
      />

      {curated.error && curated.isStale && (
        <AlertBanner tone="warning">Showing stale data; refresh failed.</AlertBanner>
      )}
      {curated.error && !curated.data && <AlertBanner tone="error">Failed to load jobs.</AlertBanner>}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {LIFECYCLE_STATES.map((state) => (
          <div key={state} className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <StatusPill state={state} />
              <span className="micro-label">{groups[state].length}</span>
            </div>
            <div className="flex flex-col gap-2">
              {groups[state].length === 0 ? (
                <EmptyState message="—" />
              ) : (
                groups[state].map((job) => <JobCard key={job.id} job={job} />)
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Transparent curation: on demand, show what the board hides and why. */}
      <div className="rounded-xl border border-border/70 bg-white/[0.02] px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm text-muted">
            {!showHidden
              ? 'Auto-ingested low-fit jobs are hidden from this board. Jobs you paste manually always appear once prepared.'
              : all.loading && !all.data
                ? 'Loading hidden rows…'
                : hidden.length === 0
                  ? 'Nothing hidden — every job meets the curation bar.'
                  : `${hidden.length} job${hidden.length === 1 ? '' : 's'} hidden by curation.`}
          </p>
          <button
            onClick={() => setShowHidden((v) => !v)}
            className="rounded-lg border border-border px-3 py-1.5 text-sm text-muted hover:text-text"
          >
            {showHidden ? 'Hide' : 'Audit hidden rows'}
          </button>
        </div>

        {showHidden && hidden.length > 0 && (
          <ul className="mt-3 flex flex-col gap-2 border-t border-border/60 pt-3">
            {hidden.map((job) => (
              <li key={job.id}>
                <Link
                  to={`/jobs/${job.id}`}
                  className="flex items-center justify-between gap-3 rounded-lg px-2 py-1.5 text-sm opacity-80 hover:bg-white/[0.04] hover:opacity-100"
                >
                  <span className="min-w-0 truncate">
                    <span className="font-medium">{job.company}</span>{' '}
                    <span className="text-muted">— {job.title}</span>
                  </span>
                  <span className="shrink-0 micro-label text-warning">
                    {curationReason(job) ?? 'below fit threshold'}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
