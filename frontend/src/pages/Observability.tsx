import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { axisTick, CHART_COLORS, tooltipStyle, valueLabel } from '../lib/chartTheme'
import { MetricCard } from '../components/MetricCard'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { Skeleton } from '../components/Skeleton'
import { useAsyncData } from '../hooks/useAsyncData'
import { useSSE } from '../hooks/useSSE'
import {
  getObservabilityCosts,
  getObservabilityLatency,
  getObservabilityPerformance,
  getObservabilityStorage,
  getObservabilitySummary,
  listLlmCalls,
} from '../lib/api'
import type { AuditEntry } from '../lib/types'
import { NAV } from '../lib/navLabels'

export function Observability() {
  const summary = useAsyncData(() => getObservabilitySummary(), [], { refreshInterval: 30_000 })
  const costs = useAsyncData(() => getObservabilityCosts(30), [], { refreshInterval: 60_000 })
  const latency = useAsyncData(() => getObservabilityLatency(30), [], { refreshInterval: 60_000 })
  const performance = useAsyncData(() => getObservabilityPerformance(30), [], { refreshInterval: 60_000 })
  const storage = useAsyncData(() => getObservabilityStorage(), [], { refreshInterval: 120_000 })
  const calls = useAsyncData(() => listLlmCalls({ limit: 20 }), [], { refreshInterval: 30_000 })
  const { events, connected } = useSSE<AuditEntry>('/api/events/stream')

  const llmEvents = events.filter((e) => e.action === 'llm_call').slice(0, 15)
  const costRows = Array.isArray(costs.data) ? costs.data : []
  const latencyRows = Array.isArray(latency.data) ? latency.data : []
  const performanceRows = Array.isArray(performance.data) ? performance.data : []
  const callRows = Array.isArray(calls.data) ? calls.data : []

  if (summary.loading && !summary.data) return <Skeleton className="h-64" />

  const s = summary.data
  const today = s?.today
  const week = s?.['7d']

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={NAV.usage.label}
        description="LLM cost, latency, and usage across the system. Use this when you want to understand spend or debug slow operations — not needed for day-to-day job hunting."
        actions={
          <span className={`micro-label ${connected ? 'text-cyan' : 'text-muted'}`}>
            {connected ? 'live' : 'reconnecting'}
          </span>
        }
      />

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <MetricCard label="Cost today" value={`$${(today?.total_cost_usd ?? 0).toFixed(4)}`} />
        <MetricCard label="Cost 7d" value={`$${(week?.total_cost_usd ?? 0).toFixed(4)}`} />
        <MetricCard label="Tokens 7d" value={week?.total_tokens ?? 0} />
        <MetricCard label="Avg latency 7d" value={`${week?.avg_latency_ms ?? 0}ms`} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Cost over time (30d)">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={costRows}>
                <XAxis dataKey="key" tick={axisTick} />
                <YAxis tick={axisTick} />
                <Tooltip contentStyle={tooltipStyle} />
                <Area type="monotone" dataKey="cost_usd" stroke={CHART_COLORS.neutral} fill="#00d4ff33" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel title="Latency by operation (p95)">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={latencyRows.slice(0, 8)} margin={{ top: 16 }}>
                <XAxis dataKey="operation_name" tick={axisTick} interval={0} angle={-25} textAnchor="end" height={60} />
                <YAxis tick={axisTick} />
                <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
                <Bar dataKey="p95_ms" fill={CHART_COLORS.brand} radius={[4, 4, 0, 0]}>
                  <LabelList dataKey="p95_ms" {...valueLabel} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      </div>

      <Panel title="Performance scorecards">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="micro-label text-muted">
              <tr>
                <th className="pb-2">Operation</th>
                <th className="pb-2">Calls</th>
                <th className="pb-2">Success</th>
                <th className="pb-2">p50</th>
                <th className="pb-2">p95</th>
                <th className="pb-2">Avg cost</th>
              </tr>
            </thead>
            <tbody>
              {performanceRows.map((row) => (
                <tr key={row.operation_name} className="border-t border-border">
                  <td className="py-2">{row.operation_name}</td>
                  <td className="py-2">{row.call_count}</td>
                  <td className="py-2">{(row.success_rate * 100).toFixed(1)}%</td>
                  <td className="py-2">{row.latency_p50_ms}ms</td>
                  <td className="py-2">{row.latency_p95_ms}ms</td>
                  <td className="py-2">${row.avg_cost_usd.toFixed(5)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {storage.data && (
        <Panel title="Storage & retention">
          <div className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
            <div>
              <div className="micro-label text-muted">SQLite</div>
              <div>{(storage.data.sqlite_bytes / 1024 / 1024).toFixed(2)} MB</div>
            </div>
            <div>
              <div className="micro-label text-muted">Materials</div>
              <div>{(storage.data.materials_bytes / 1024 / 1024).toFixed(2)} MB</div>
            </div>
            <div>
              <div className="micro-label text-muted">Documents</div>
              <div>{(storage.data.knowledge_bytes / 1024 / 1024).toFixed(2)} MB</div>
            </div>
            <div>
              <div className="micro-label text-muted">Telemetry retention</div>
              <div>{storage.data.telemetry_retention_days} days</div>
            </div>
          </div>
        </Panel>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Recent LLM calls">
          <ul className="flex max-h-80 flex-col gap-2 overflow-y-auto text-sm">
            {callRows.map((call) => (
              <li key={call.id} className="rounded border border-border px-3 py-2">
                <div className="flex justify-between">
                  <span className="text-cyan">{call.operation_name}</span>
                  <span className="text-muted">{call.latency_ms}ms</span>
                </div>
                <div className="text-muted">
                  {call.request_model} · ${call.cost_usd.toFixed(5)} · {call.input_tokens}+{call.output_tokens} tok
                </div>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="Live LLM activity (SSE)">
          <ul className="flex max-h-80 flex-col gap-2 overflow-y-auto text-sm">
            {llmEvents.map((ev) => (
              <li key={ev.id} className="rounded border border-border px-3 py-2">
                <div className="text-cyan">{ev.detail?.operation_name as string}</div>
                <div className="text-muted">
                  {ev.detail?.model as string} · {ev.detail?.latency_ms as number}ms · $
                  {(ev.detail?.cost_usd as number)?.toFixed?.(5)}
                </div>
              </li>
            ))}
            {llmEvents.length === 0 && <li className="text-muted">Waiting for LLM calls…</li>}
          </ul>
        </Panel>
      </div>
    </div>
  )
}
