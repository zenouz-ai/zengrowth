import { Link } from 'react-router-dom'
import { Bar, BarChart, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Panel } from '../components/Panel'
import { useAsyncData } from '../hooks/useAsyncData'
import { axisTick, CHART_COLORS, tooltipStyle, valueLabel } from '../lib/chartTheme'
import { publicPipeline, publicScores, publicSummary } from '../lib/api'

// Anonymous, redacted snapshot. No company/title/url data is ever fetched here —
// only the aggregate /api/public/* endpoints.
export function PublicDashboard() {
  const summary = useAsyncData(() => publicSummary(), [])
  const pipeline = useAsyncData(() => publicPipeline(), [])
  const scores = useAsyncData(() => publicScores(), [])

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <header className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="font-heading text-2xl font-bold">ZenGrowth</h1>
          <p className="text-sm text-muted">Public pipeline telemetry (anonymized)</p>
        </div>
        <Link to="/login" className="micro-label hover:text-text">
          operator login
        </Link>
      </header>

      {/* Narrative for an evaluator (e.g. a hiring manager reviewing the
          engineering) — what this is and how the privacy guarantee works. */}
      <div className="mb-8 rounded-xl border border-border/70 bg-white/[0.02] px-5 py-4">
        <p className="leading-7 text-text">
          ZenGrowth is a transparency-first career pipeline: it discovers roles, scores each with an
          auditable priority-score rationale, verifies every supporting claim against a source
          document, and generates application materials traced back to that evidence.
        </p>
        <p className="mt-2 text-xs text-muted">
          This page shows aggregate progress only. Counts and score buckets smaller than 5 are
          suppressed (k-anonymity, k=5, with complementary suppression so a hidden cell can't be
          recovered by subtraction), and no company, title, or job-level data is ever exposed —
          the page calls only the aggregate <code>/api/public/*</code> endpoints.
        </p>
        <p className="mt-2 text-xs text-muted">
          Honest caveat: these are one operator&rsquo;s figures. Suppression prevents singling out
          an individual job, not identifying whose search this is — anyone who knows that can read
          the coarse funnel above.
        </p>
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <FunnelStep label="Total" value={summary.data?.total_jobs} />
        <FunnelStep label="Applied" value={summary.data?.applied} arrow />
        <FunnelStep label="Interviewing" value={summary.data?.interviewing} arrow />
        <FunnelStep label="Offers" value={summary.data?.offers} arrow tone="var(--color-emerald)" />
      </div>

      {(summary.data?.suppressed ?? 0) > 0 && (
        <p className="mb-6 text-xs text-muted">
          Some summary counts below 5 are hidden for anonymity ({summary.data?.suppressed} hidden).
        </p>
      )}

      <Panel title="Pipeline by state" className="mb-6">
        {(pipeline.data?.suppressed ?? 0) > 0 && (
          <p className="mb-2 text-xs text-muted">
            State counts below 5 are hidden for anonymity ({pipeline.data?.suppressed} hidden).
          </p>
        )}
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={pipeline.data?.states ?? []} margin={{ top: 16 }}>
              <XAxis dataKey="state" tick={axisTick} interval={0} angle={-35} textAnchor="end" height={70} />
              <YAxis allowDecimals={false} tick={axisTick} />
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
              <Bar dataKey="count" fill={CHART_COLORS.brand} radius={[4, 4, 0, 0]}>
                <LabelList dataKey="count" {...valueLabel} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      <Panel title="Fit-score distribution">
        <p className="mb-2 text-xs text-muted">
          Small buckets are suppressed for anonymity ({scores.data?.suppressed ?? 0} hidden).
        </p>
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={scores.data?.buckets ?? []} margin={{ top: 16 }}>
              <XAxis dataKey="label" tick={axisTick} />
              <YAxis allowDecimals={false} tick={axisTick} />
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
              <Bar dataKey="count" fill={CHART_COLORS.positive} radius={[4, 4, 0, 0]}>
                <LabelList dataKey="count" {...valueLabel} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Panel>
    </div>
  )
}

function FunnelStep({
  label,
  value,
  arrow = false,
  tone,
}: {
  label: string
  value?: number
  arrow?: boolean
  tone?: string
}) {
  return (
    <div className="relative glass px-4 py-3">
      {arrow && (
        <span className="absolute -left-2.5 top-1/2 hidden -translate-y-1/2 text-muted sm:block">
          ›
        </span>
      )}
      <div className="micro-label">{label}</div>
      <div className="mt-1 text-2xl font-semibold" style={tone ? { color: tone } : undefined}>
        {value ?? '—'}
      </div>
    </div>
  )
}
