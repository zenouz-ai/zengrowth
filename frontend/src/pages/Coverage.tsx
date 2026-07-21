import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Area, AreaChart, ResponsiveContainer, Tooltip, Treemap, XAxis, YAxis } from 'recharts'
import { EmptyState } from '../components/EmptyState'
import { MetricCard } from '../components/MetricCard'
import { Panel } from '../components/Panel'
import { Skeleton } from '../components/Skeleton'
import { useAsyncData } from '../hooks/useAsyncData'
import { backfillKnowledgeFacets, getKnowledgeCoverage, listKnowledgeClaims } from '../lib/api'
import { CHART_COLORS, axisTick, tooltipStyle } from '../lib/chartTheme'
import { FACET_LABELS, coverageTone, cumulativeSeries, facetLabel } from '../lib/coverage'
import type { CoverageValue } from '../lib/types'

// KG-02 Coverage tab: what the evidence bank contains (treemap + evidence over
// time) and where it is thin against what scored JDs demand (heatmap). Facets
// are derived metadata over already-verified claims — this surface reads, it
// never writes to the truth path.

const SERIES_COLORS = [
  CHART_COLORS.neutral,
  CHART_COLORS.positive,
  CHART_COLORS.brand,
  CHART_COLORS.warning,
  CHART_COLORS.negative,
  '#9a8cff',
]

const TONE_STYLES: Record<ReturnType<typeof coverageTone>, { background: string; label: string }> = {
  gap: { background: 'rgba(255, 68, 102, 0.16)', label: 'gap' },
  thin: { background: 'rgba(247, 201, 72, 0.14)', label: 'thin' },
  solid: { background: 'rgba(0, 255, 163, 0.12)', label: 'solid' },
  quiet: { background: 'transparent', label: '—' },
}

interface TreemapCellProps {
  x?: number
  y?: number
  width?: number
  height?: number
  index?: number
  name?: string
  onSelect?: (name: string) => void
}

function TreemapCell({ x = 0, y = 0, width = 0, height = 0, index = 0, name, onSelect }: TreemapCellProps) {
  if (width <= 0 || height <= 0) return null
  const fill = SERIES_COLORS[index % SERIES_COLORS.length]
  return (
    <g onClick={() => name && onSelect?.(name)} style={{ cursor: 'pointer' }}>
      <rect x={x} y={y} width={width} height={height} fill={fill} fillOpacity={0.22} stroke="#2a2d3a" />
      {width > 70 && height > 22 && (
        <text x={x + 6} y={y + 16} fill="#e8ecf5" fontSize={11}>
          {name}
        </text>
      )}
    </g>
  )
}

export function Coverage() {
  const coverage = useAsyncData(() => getKnowledgeCoverage(), [])
  const claims = useAsyncData(() => listKnowledgeClaims(), [])
  const [facet, setFacet] = useState<string>('industry')
  const [selectedValue, setSelectedValue] = useState<string | null>(null)
  const [backfilling, setBackfilling] = useState(false)
  const [backfillNote, setBackfillNote] = useState<string | null>(null)

  const data = coverage.data
  const facetData = data?.facets.find((f) => f.facet === facet)
  const values = useMemo(() => facetData?.values ?? [], [facetData])
  const selected: CoverageValue | undefined = values.find((v) => v.value === selectedValue)
  const series = useMemo(() => cumulativeSeries(values), [values])
  const treemapData = useMemo(
    () =>
      values
        .filter((v) => v.verified_claims > 0)
        .map((v) => ({ name: v.value, size: v.verified_claims })),
    [values],
  )
  const jobsById = useMemo(
    () => new Map((data?.jobs ?? []).map((job) => [job.id, job])),
    [data],
  )
  const claimsById = useMemo(
    () => new Map((claims.data ?? []).map((claim) => [claim.id, claim])),
    [claims.data],
  )

  async function runBackfill() {
    setBackfilling(true)
    setBackfillNote(null)
    try {
      const result = await backfillKnowledgeFacets()
      setBackfillNote(
        `Faceted ${result.documents_faceted} document(s) and ${result.jobs_faceted} job(s) — ${result.facet_rows} facet row(s).`,
      )
      coverage.refetch()
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
        'Facet assignment failed — check the audit log.'
      setBackfillNote(detail)
    } finally {
      setBackfilling(false)
    }
  }

  if (coverage.loading && !data) return <Skeleton className="h-64" />
  if (!data) return <EmptyState message="Coverage could not be loaded." />

  const nothingFaceted = data.totals.faceted_claims === 0 && data.totals.faceted_jobs === 0
  const pendingWork = data.totals.unfaceted_claims > 0 || data.totals.unfaceted_jobs > 0

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <MetricCard label="Facts faceted" value={`${data.totals.faceted_claims}/${data.totals.claims}`} />
        <MetricCard label="Scored JDs faceted" value={`${data.totals.faceted_jobs}/${data.totals.scored_jobs}`} />
        <MetricCard
          label="Gaps in this facet"
          value={values.filter((v) => v.gap).length}
        />
        <MetricCard label="Values with evidence" value={values.filter((v) => v.verified_claims > 0).length} />
      </div>

      {(pendingWork || nothingFaceted) && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border/70 bg-white/[0.02] px-4 py-3 text-sm">
          <span className="text-muted">
            {nothingFaceted
              ? 'Nothing is faceted yet. Assign facets to map your evidence against a controlled vocabulary.'
              : `${data.totals.unfaceted_claims} fact(s) and ${data.totals.unfaceted_jobs} scored JD(s) still need facets.`}
          </span>
          <button
            onClick={() => void runBackfill()}
            disabled={backfilling}
            className="rounded-lg border border-border px-3 py-1.5 text-sm text-text hover:bg-white/5 disabled:opacity-50"
          >
            {backfilling ? 'Assigning…' : 'Assign facets'}
          </button>
          {backfillNote && <span className="text-muted">{backfillNote}</span>}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border/70 bg-white/[0.02] p-1.5">
        {Object.keys(FACET_LABELS).map((key) => (
          <button
            key={key}
            onClick={() => {
              setFacet(key)
              setSelectedValue(null)
            }}
            className={`rounded-lg px-3 py-1.5 text-sm ${
              facet === key ? 'bg-white/5 text-text' : 'text-muted hover:text-text'
            }`}
          >
            {facetLabel(key)}
          </button>
        ))}
      </div>

      {values.length === 0 ? (
        <EmptyState message={`No ${facetLabel(facet).toLowerCase()} facets yet — assign facets above once documents are ingested and jobs are scored.`} />
      ) : (
        <>
          <div className="grid gap-6 lg:grid-cols-2">
            <Panel title="Verified evidence by value">
              {treemapData.length === 0 ? (
                <EmptyState message="No verified evidence carries this facet yet." />
              ) : (
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <Treemap
                      data={treemapData}
                      dataKey="size"
                      isAnimationActive={false}
                      content={<TreemapCell onSelect={setSelectedValue} />}
                    >
                      <Tooltip contentStyle={tooltipStyle} />
                    </Treemap>
                  </ResponsiveContainer>
                </div>
              )}
            </Panel>

            <Panel title="Evidence over time (cumulative)">
              {series.rows.length === 0 ? (
                <EmptyState message="No dated verified evidence yet for this facet." />
              ) : (
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={series.rows}>
                      <XAxis dataKey="month" tick={axisTick} />
                      <YAxis tick={axisTick} allowDecimals={false} />
                      <Tooltip contentStyle={tooltipStyle} />
                      {series.keys.map((key, index) => (
                        <Area
                          key={key}
                          type="monotone"
                          stackId="1"
                          dataKey={key}
                          stroke={SERIES_COLORS[index % SERIES_COLORS.length]}
                          fill={`${SERIES_COLORS[index % SERIES_COLORS.length]}33`}
                          isAnimationActive={false}
                        />
                      ))}
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Panel>
          </div>

          <Panel title="Coverage vs demand">
            <p className="mb-3 text-sm text-muted">
              What recent scored JDs ask for, against the verified evidence that answers it. A{' '}
              <span className="text-negative">gap</span> is a value JDs demand with no verified fact
              yet — draft facts don't count until reviewed.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="micro-label text-muted">
                  <tr>
                    <th className="pb-2">{facetLabel(facet)}</th>
                    <th className="pb-2">JDs asking</th>
                    <th className="pb-2">Verified facts</th>
                    <th className="pb-2">Draft</th>
                    <th className="pb-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {values.map((value) => {
                    const tone = coverageTone(value)
                    return (
                      <tr
                        key={value.value}
                        onClick={() => setSelectedValue(value.value)}
                        className={`cursor-pointer border-t border-border/50 hover:bg-white/[0.03] ${
                          selectedValue === value.value ? 'bg-white/[0.04]' : ''
                        }`}
                      >
                        <td className="py-2 pr-3">{value.value}</td>
                        <td className="py-2 pr-3">{value.demand_jobs}</td>
                        <td className="py-2 pr-3">{value.verified_claims}</td>
                        <td className="py-2 pr-3 text-muted">{value.draft_claims}</td>
                        <td className="py-2">
                          <span
                            className="rounded px-2 py-0.5 text-xs"
                            style={{ background: TONE_STYLES[tone].background }}
                          >
                            {value.gap ? 'gap — no verified fact' : TONE_STYLES[tone].label}
                          </span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </Panel>

          {selected && (
            <Panel
              title={`${facetLabel(facet)}: ${selected.value}`}
              actions={
                <button onClick={() => setSelectedValue(null)} className="text-sm text-muted hover:text-text">
                  Close
                </button>
              }
            >
              <div className="grid gap-6 lg:grid-cols-2">
                <div>
                  <h3 className="micro-label mb-2 text-muted">
                    Verified facts ({selected.verified_claims})
                  </h3>
                  {selected.claim_ids.length === 0 ? (
                    <EmptyState message="No verified fact answers this yet — add or verify evidence in the Library." />
                  ) : (
                    <ul className="flex flex-col gap-2 text-sm">
                      {selected.claim_ids.map((id) => (
                        <li key={id} className="rounded-lg border border-border/60 px-3 py-2">
                          {claimsById.get(id)?.claim_text ?? id}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div>
                  <h3 className="micro-label mb-2 text-muted">
                    JDs demanding it ({selected.demand_jobs})
                  </h3>
                  {selected.job_ids.length === 0 ? (
                    <EmptyState message="No scored JD demands this value." />
                  ) : (
                    <ul className="flex flex-col gap-2 text-sm">
                      {selected.job_ids.map((id) => {
                        const job = jobsById.get(id)
                        return (
                          <li key={id} className="rounded-lg border border-border/60 px-3 py-2">
                            <Link to={`/jobs/${id}`} className="hover:text-cyan">
                              {job ? `${job.title} — ${job.company}` : `Job #${id}`}
                            </Link>
                          </li>
                        )
                      })}
                    </ul>
                  )}
                </div>
              </div>
            </Panel>
          )}
        </>
      )}
    </div>
  )
}
