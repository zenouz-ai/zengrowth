import { Link } from 'react-router-dom'
import { Bar, BarChart, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AlertBanner } from '../components/AlertBanner'
import { MetricCard } from '../components/MetricCard'
import { OperatorGuide } from '../components/OperatorGuide'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { Skeleton } from '../components/Skeleton'
import { useAsyncData } from '../hooks/useAsyncData'
import { useKnowledgeClaims } from '../hooks/useKnowledgeClaims'
import { getIngestionHealth, listJobs } from '../lib/api'
import { groupByState } from '../lib/pipeline'
import { ingestionHealthBanner } from '../lib/ingestionHealth'
import { axisTick, CHART_COLORS, tooltipStyle, valueLabel } from '../lib/chartTheme'
import { NAV } from '../lib/navLabels'
import { LIFECYCLE_STATES } from '../lib/types'

export function Dashboard() {
  const { data, loading } = useAsyncData(() => listJobs({ curated: true }), [], {
    refreshInterval: 30_000,
  })
  // Ingestion health drives the silent-pipeline banner (SEC-01). It's
  // best-effort: a failure here must never blank the dashboard, so null on error.
  const { data: ingestHealth } = useAsyncData(
    () => getIngestionHealth().catch(() => null),
    [],
    { refreshInterval: 60_000 },
  )
  const draftClaims = useKnowledgeClaims('draft')
  const ingestBanner = ingestionHealthBanner(ingestHealth ?? null)

  if (loading && !data) return <Skeleton className="h-64" />
  const jobs = data ?? []
  const groups = groupByState(jobs)
  const chartData = LIFECYCLE_STATES.map((s) => ({ state: s.replace(/_/g, ' '), count: groups[s].length }))
  const scored = jobs.filter((j) => j.fit_score != null)
  const awaitingCheck = draftClaims.data?.length ?? 0

  // Gentle nudge (PS-P5): strong matches the operator scored but never acted on.
  const NOT_APPLIED = new Set(['discovered', 'shortlisted', 'prepared', 'awaiting_approval', 'approved'])
  const strongUnapplied = jobs
    .filter((j) => (j.fit_score ?? 0) >= 80 && NOT_APPLIED.has(j.lifecycle_state))
    .sort((a, b) => (b.expected_value ?? 0) - (a.expected_value ?? 0))
  const topUnapplied = strongUnapplied[0]

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={NAV.dashboard.label}
        description="Your starting point — paste a job to score it and generate a tailored application, or pick up where you left off below."
        actions={
          <Link
            to={NAV.addJob.to}
            className="rounded-lg border border-cyan bg-cyan/10 px-4 py-2 text-sm font-medium text-cyan hover:bg-cyan/15"
          >
            Paste a job →
          </Link>
        }
      />

      <OperatorGuide />

      {ingestBanner && (
        <AlertBanner tone={ingestBanner.tone}>{ingestBanner.message}</AlertBanner>
      )}

      {topUnapplied && (
        <Link
          to={`/jobs/${topUnapplied.id}`}
          className="flex items-center justify-between gap-3 rounded-xl border border-cyan/40 bg-cyan/5 px-4 py-3 text-sm hover:bg-cyan/10"
        >
          <span className="text-text">
            {strongUnapplied.length === 1
              ? '1 strong match'
              : `${strongUnapplied.length} strong matches`}{' '}
            scored 80+ you haven't applied to yet — start with{' '}
            <span className="font-medium">{topUnapplied.company}</span>?
          </span>
          <span className="micro-label shrink-0 text-cyan">open →</span>
        </Link>
      )}

      {awaitingCheck > 0 && (
        <Link
          to={NAV.approveFacts.to}
          className="flex items-center justify-between gap-3 rounded-xl border border-warning/50 bg-warning/10 px-4 py-3 text-sm hover:bg-warning/15"
        >
          <span className="text-warning">
            {awaitingCheck} fact{awaitingCheck === 1 ? '' : 's'} need approval on {NAV.approveFacts.label}{' '}
            before they can back generated CVs and cover letters.
          </span>
          <span className="micro-label text-warning">check now →</span>
        </Link>
      )}

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <MetricCard label="Pipeline jobs" value={jobs.length} />
        <MetricCard label="Scored" value={scored.length} />
        <MetricCard label="Applied" value={groups.applied.length} />
        <MetricCard label="Interviewing" value={groups.interviewing.length} />
      </div>
      <Panel title="Jobs by stage">
        <p className="mb-3 text-xs text-muted">
          Count of scored, pipeline-ready jobs in each lifecycle stage. Archived roles and unscored
          or low-fit discovered postings are hidden here. Open{' '}
          <Link to={NAV.jobs.to} className="text-cyan hover:underline">
            {NAV.jobs.label}
          </Link>{' '}
          to work the board, or click a job to generate materials.
        </p>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 16 }}>
              <XAxis dataKey="state" tick={axisTick} interval={0} angle={-35} textAnchor="end" height={70} />
              <YAxis allowDecimals={false} tick={axisTick} />
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
              <Bar dataKey="count" fill={CHART_COLORS.neutral} radius={[4, 4, 0, 0]}>
                <LabelList dataKey="count" {...valueLabel} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Panel>
    </div>
  )
}
