import { EmptyState } from './EmptyState'
import { Panel } from './Panel'
import { parseRationale, rationaleMeter, titleize } from '../lib/rationale'

// Surfaces the stored scoring rationale at the moment of decision. The backend
// persists, for each job, a `score_rationale` object where most keys are
// `{ score, reason }` dimensions plus a free-text `summary` recommendation
// (see scoring/prompts.py). Until now this was fetched by getJob() and thrown
// away; this panel renders it so the operator can see *why* a job was scored.

export function RationalePanel({
  rationale,
  expectedValue,
}: {
  rationale: Record<string, unknown> | null
  expectedValue: number | null
}) {
  if (!rationale || Object.keys(rationale).length === 0) {
    return (
      <Panel title="Why this score">
        <EmptyState message="Not scored yet — run Score to generate the priority-score rationale." />
      </Panel>
    )
  }

  const { summary, dimensions } = parseRationale(rationale)
  const composite = dimensions.find((d) => d.key === 'match_quality')
  const rest = dimensions.filter((d) => d.key !== 'match_quality')
  const successDim = dimensions.find((d) => d.key === 'success_probability')
  const effortDim = dimensions.find((d) => d.key === 'application_effort')
  const band = successBand(successDim?.score ?? null)

  return (
    <Panel title="Why this score">
      <div className="flex flex-col gap-4">
        {summary && (
          <div className="rounded-lg border border-cyan/40 bg-cyan/5 px-4 py-3">
            <p className="micro-label mb-1 text-cyan">Recommendation</p>
            <p className="leading-7 text-text">{summary}</p>
            {expectedValue != null && (
              <p className="mt-2 text-xs text-muted">
                Priority score{' '}
                <span className="text-cyan">{expectedValue.toFixed(1)}</span> ranks this job in your
                pipeline — a weighted blend of the observable fit dimensions below
                {composite
                  ? `, alongside match quality at ${composite.score}/100.`
                  : '.'}
              </p>
            )}
            {(band || effortDim) && (
              <p className="mt-1 text-xs text-muted">
                Shown separately, not mixed into the rank:
                {band && (
                  <>
                    {' '}
                    chances <span className="text-text">{band}</span>
                  </>
                )}
                {band && effortDim && ' ·'}
                {effortDim && (
                  <>
                    {' '}
                    application effort <span className="text-text">{effortDim.score}/5</span>
                  </>
                )}
                .
              </p>
            )}
          </div>
        )}

        {dimensions.length === 0 ? (
          <EmptyState message="Rationale stored but no scored dimensions found." />
        ) : (
          <>
            {/* Lead with the headline composite; keep the rest one click away. */}
            {composite && <DimensionRow dim={composite} />}
            {rest.length > 0 && (
              <details className="group">
                <summary className="cursor-pointer select-none micro-label text-muted hover:text-text">
                  Show full breakdown ({rest.length} dimensions)
                </summary>
                <ul className="mt-3 flex flex-col gap-4">
                  {rest.map((dim) => (
                    <li key={dim.key}>
                      <DimensionRow dim={dim} />
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </>
        )}
      </div>
    </Panel>
  )
}

// Mirrors success_band() in scoring/expected_value.py: the probability is an
// uncalibrated model guess, so only a coarse three-way band is honest.
function successBand(probability: number | null): string | null {
  if (probability == null) return null
  if (probability >= 0.5) return 'strong'
  if (probability >= 0.2) return 'competitive'
  return 'long shot'
}

function DimensionRow({ dim }: { dim: ReturnType<typeof parseRationale>['dimensions'][number] }) {
  const { pct, display, tone } = rationaleMeter(dim)
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium">
          {titleize(dim.key)}
          {dim.key === 'match_quality' && (
            <span className="ml-2 micro-label text-cyan">composite</span>
          )}
        </span>
        <span className="font-mono text-xs text-muted">{display}</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, backgroundColor: tone }}
        />
      </div>
      {dim.reason && <p className="text-xs leading-5 text-muted">{dim.reason}</p>}
    </div>
  )
}
