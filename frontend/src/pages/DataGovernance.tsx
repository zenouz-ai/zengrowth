import { useState } from 'react'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { Skeleton } from '../components/Skeleton'
import { useAsyncData } from '../hooks/useAsyncData'
import { getDataSource, listDataSources } from '../lib/api'
import { NAV } from '../lib/navLabels'

export function DataGovernance() {
  const sources = useAsyncData(() => listDataSources(), [], { refreshInterval: 60_000 })
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const detail = useAsyncData(
    () => (selectedId ? getDataSource(selectedId) : Promise.resolve(null)),
    [selectedId],
  )

  if (sources.loading && !sources.data) return <Skeleton className="h-64" />

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={NAV.dataSources.label}
        description="Registry of configured data sources (ATS boards, LLM providers, file stores) and their health. Useful for operators evaluating the stack, not for daily applications."
      />

      <Panel title="Datasource registry">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="micro-label text-muted">
              <tr>
                <th className="pb-2">Name</th>
                <th className="pb-2">Kind</th>
                <th className="pb-2">Health</th>
                <th className="pb-2">Enabled</th>
                <th className="pb-2">Records</th>
                <th className="pb-2">PII</th>
              </tr>
            </thead>
            <tbody>
              {(sources.data ?? []).map((src) => (
                <tr
                  key={src.id}
                  className="cursor-pointer border-t border-border hover:bg-white/5"
                  onClick={() => setSelectedId(src.id ?? null)}
                >
                  <td className="py-2 text-cyan">{src.name}</td>
                  <td className="py-2">{src.kind}</td>
                  <td className="py-2">{src.health_status}</td>
                  <td className="py-2">{src.enabled ? 'yes' : 'no'}</td>
                  <td className="py-2">{src.record_count}</td>
                  <td className="py-2">{src.pii_flag ? 'yes' : 'no'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {selectedId && detail.data && (
        <Panel title={`Source detail: ${detail.data.source.name}`}>
          <div className="grid gap-4 text-sm sm:grid-cols-2">
            <div>
              <div className="micro-label text-muted">Last used</div>
              <div>{detail.data.source.last_used_at ?? '—'}</div>
            </div>
            <div>
              <div className="micro-label text-muted">Retention</div>
              <div>{detail.data.source.retention_days ?? 'default'}</div>
            </div>
            <div className="sm:col-span-2">
              <div className="micro-label text-muted">Notes</div>
              <div>{detail.data.source.notes ?? '—'}</div>
            </div>
          </div>
          {detail.data.lineage && (
            <div className="mt-4">
              <div className="micro-label mb-2 text-muted">Lineage</div>
              <pre className="overflow-x-auto rounded border border-border bg-black/30 p-3 text-xs">
                {JSON.stringify(detail.data.lineage, null, 2)}
              </pre>
            </div>
          )}
        </Panel>
      )}
    </div>
  )
}
