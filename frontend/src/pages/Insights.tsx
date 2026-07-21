import { Link } from 'react-router-dom'
import { MetricCard } from '../components/MetricCard'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { Skeleton } from '../components/Skeleton'
import { useAsyncData } from '../hooks/useAsyncData'
import { getObservabilitySummary, getOutcomeFunnel } from '../lib/api'
import { NAV } from '../lib/navLabels'

// Insights is the calm home for everything Meta (PS-P3): progress + spend up
// front, with the deeper operator surfaces (cost, latency, traces, governance,
// graph) folded behind one "Advanced" disclosure rather than three top-level
// tabs. Nothing is deleted — the daily path just gets quieter.
const ADVANCED: { to: string; label: string; hint: string }[] = [
  { to: NAV.usage.to, label: NAV.usage.label, hint: 'LLM cost, latency, and token usage over time.' },
  { to: NAV.runLog.to, label: NAV.runLog.label, hint: 'Step-by-step pipeline run waterfalls for debugging.' },
  { to: NAV.dataSources.to, label: NAV.dataSources.label, hint: 'Configured ATS / LLM / file sources and their health.' },
  { to: NAV.documentGraph.to, label: NAV.documentGraph.label, hint: 'How your documents, facts, and entities connect.' },
  { to: NAV.findJobs.to, label: NAV.findJobs.label, hint: 'Pull from ATS boards or search for new leads.' },
]

export function Insights() {
  const funnel = useAsyncData(() => getOutcomeFunnel(), [], { refreshInterval: 60_000 })
  const spend = useAsyncData(() => getObservabilitySummary(), [], { refreshInterval: 60_000 })

  if (funnel.loading && !funnel.data) return <Skeleton className="h-64" />
  const f = funnel.data
  const week = spend.data?.['7d']

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={NAV.insights.label}
        description="How your search is going — and what it's costing. The deeper operator tools live under Advanced, out of the daily path."
      />

      {week && (
        <p className="text-sm text-muted">
          You've spent{' '}
          <span className="text-text">${week.total_cost_usd.toFixed(2)}</span> on Claude this week
          across {week.call_count} call{week.call_count === 1 ? '' : 's'}.
        </p>
      )}

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <MetricCard label="Applied" value={f?.total_applied ?? 0} />
        <MetricCard label="Responded" value={f?.responded ?? 0} />
        <MetricCard label="Interviewed" value={f?.interviewed ?? 0} />
        <MetricCard label="Offers" value={f?.offers ?? 0} />
      </div>

      {f && (
        <Panel title="Conversion">
          <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
            <Rate label="Response rate" value={f.response_rate} />
            <Rate label="Interview rate" value={f.interview_rate} />
            <Rate label="Offer rate" value={f.offer_rate} />
          </dl>
        </Panel>
      )}

      <details className="rounded-xl border border-border/70 bg-white/[0.02]">
        <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium hover:text-text">
          Advanced — cost, latency, traces, governance & graph
        </summary>
        <ul className="flex flex-col gap-2 border-t border-border/60 px-4 py-4 text-sm">
          {ADVANCED.map((item) => (
            <li key={item.to} className="flex flex-wrap items-baseline gap-x-2">
              <Link to={item.to} className="font-medium text-cyan hover:underline">
                {item.label}
              </Link>
              <span className="text-muted">— {item.hint}</span>
            </li>
          ))}
        </ul>
      </details>
    </div>
  )
}

function Rate({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="rounded-lg border border-border/70 bg-white/[0.02] p-3">
      <dt className="micro-label mb-1 text-muted">{label}</dt>
      <dd className="text-lg font-semibold">{value == null ? '—' : `${Math.round(value * 100)}%`}</dd>
    </div>
  )
}
