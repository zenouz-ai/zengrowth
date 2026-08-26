import { useState } from 'react'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { Skeleton } from '../components/Skeleton'
import { useAsyncData } from '../hooks/useAsyncData'
import { getPipelineRun, listPipelineRuns } from '../lib/api'
import { NAV } from '../lib/navLabels'
import type { PipelineStep } from '../lib/types'

export function Traces() {
  const runs = useAsyncData(() => listPipelineRuns(50), [], { refreshInterval: 30_000 })
  const [selectedTrace, setSelectedTrace] = useState<string | null>(null)
  const detail = useAsyncData(
    () => (selectedTrace ? getPipelineRun(selectedTrace) : Promise.resolve(null)),
    [selectedTrace],
  )

  if (runs.loading && !runs.data) return <Skeleton className="h-64" />

  const runDetail = detail.data
  const steps = runDetail?.steps ?? []
  const maxDuration = Math.max(...steps.map((s) => s.duration_ms), 1)

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={NAV.runLog.label}
        description="Step-by-step waterfall for ingestion, scoring, and materials runs. Open when you need to see where time was spent or why a pipeline step failed."
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Recent runs">
          <ul className="flex max-h-[32rem] flex-col gap-2 overflow-y-auto text-sm">
            {(runs.data ?? []).map((run) => (
              <li key={run.trace_id}>
                <button
                  type="button"
                  onClick={() => setSelectedTrace(run.trace_id)}
                  className={`w-full rounded border px-3 py-2 text-left ${
                    selectedTrace === run.trace_id ? 'border-cyan bg-cyan/5' : 'border-border'
                  }`}
                >
                  <div className="flex justify-between">
                    <span className="text-cyan">{run.pipeline_type}</span>
                    <span className="text-muted">{run.status}</span>
                  </div>
                  <div className="text-muted">
                    {run.step_count} steps · ${run.total_cost_usd.toFixed(4)} · {run.total_tokens} tok
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="Trace waterfall">
          {!selectedTrace && <p className="text-sm text-muted">Select a run to view steps.</p>}
          {selectedTrace && detail.loading && <Skeleton className="h-40" />}
          {runDetail && (
            <div className="flex flex-col gap-3">
              <div className="text-sm text-muted">
                {runDetail.run.pipeline_type} · {runDetail.run.status} · trace {runDetail.run.trace_id.slice(0, 12)}…
              </div>
              {steps.map((step) => (
                <WaterfallRow key={step.id} step={step} maxDuration={maxDuration} />
              ))}
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}

function WaterfallRow({ step, maxDuration }: { step: PipelineStep; maxDuration: number }) {
  const width = Math.max(4, (step.duration_ms / maxDuration) * 100)
  return (
    <div className="text-sm">
      <div className="mb-1 flex justify-between">
        <span>
          {step.step_name}{' '}
          <span className="text-muted">({step.step_type})</span>
          {step.decision && <span className="ml-2 text-cyan">{step.decision}</span>}
        </span>
        <span className="text-muted">{step.duration_ms}ms</span>
      </div>
      <div className="h-2 rounded bg-black/40">
        <div
          className="h-2 rounded bg-cyan/70"
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  )
}
