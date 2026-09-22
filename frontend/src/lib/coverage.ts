import type { CoverageValue } from './types'

// KG-02 Coverage tab helpers: pure data-shaping so the chart components stay
// thin and the logic is unit-testable.

export const FACET_LABELS: Record<string, string> = {
  industry: 'Industry',
  role_family: 'Role family',
  project_type: 'Project type',
  capability: 'Capability',
  location: 'Location',
  seniority: 'Seniority',
}

export function facetLabel(facet: string): string {
  return FACET_LABELS[facet] ?? facet.replace(/_/g, ' ')
}

export interface CumulativeSeries {
  rows: Array<Record<string, number | string>>
  keys: string[]
}

// Stacked-area input: cumulative verified-evidence counts per facet value by
// month. Months are the union across the plotted values (sorted), each value's
// count carried forward so the area reads as "evidence accumulated so far".
// Values without any dated evidence are skipped; topN keeps the chart legible.
export function cumulativeSeries(values: CoverageValue[], topN = 6): CumulativeSeries {
  const plotted = values
    .filter((v) => v.monthly.length > 0)
    .sort((a, b) => b.verified_claims - a.verified_claims)
    .slice(0, topN)
  const months = Array.from(
    new Set(plotted.flatMap((v) => v.monthly.map((m) => m.month))),
  ).sort()
  if (months.length === 0) return { rows: [], keys: [] }

  const perValue = new Map(plotted.map((v) => [v.value, new Map(v.monthly.map((m) => [m.month, m.claims]))]))
  const running = new Map(plotted.map((v) => [v.value, 0]))
  const rows = months.map((month) => {
    const row: Record<string, number | string> = { month }
    for (const value of plotted) {
      const next = (running.get(value.value) ?? 0) + (perValue.get(value.value)?.get(month) ?? 0)
      running.set(value.value, next)
      row[value.value] = next
    }
    return row
  })
  return { rows, keys: plotted.map((v) => v.value) }
}

// Heatmap cell tone by verified-evidence depth against demand: a demanded value
// with nothing verified is the actionable gap; depth 1-2 is thin; 3+ is solid.
export function coverageTone(value: CoverageValue): 'gap' | 'thin' | 'solid' | 'quiet' {
  if (value.gap) return 'gap'
  if (value.verified_claims >= 3) return 'solid'
  if (value.verified_claims >= 1) return 'thin'
  return 'quiet'
}
