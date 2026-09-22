// Parsing + normalisation for the stored scoring rationale. Kept out of the
// component file so the logic is unit-testable and the component module only
// exports a component (react-refresh friendly). The backend persists, per job, a
// `score_rationale` object where most keys are `{ score, reason }` dimensions
// plus a free-text `summary` recommendation (see scoring/prompts.py).

export type Dimension = { key: string; score: number; reason?: string }

// How to normalise a dimension's score onto a 0–1 meter, with a display hint.
// Anything not listed is treated as a 0–100 score.
export const RATIONALE_SCALE: Record<
  string,
  { max: number; lowerIsBetter?: boolean; hint: string }
> = {
  application_effort: { max: 5, lowerIsBetter: true, hint: '/5 effort' },
  success_probability: { max: 1, hint: 'probability' },
}

// Order: composite first, then the contributing dimensions.
const ORDER = [
  'match_quality',
  'success_probability',
  'application_effort',
  'strategic_career_value',
  'role_relevance',
  'ai_technical_alignment',
  'leadership_alignment',
  'compensation_fit',
  'domain_fit',
  'hybrid_location_fit',
]

export function titleize(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function asReason(value: unknown): string | undefined {
  if (value && typeof value === 'object' && 'reason' in value) {
    const r = (value as { reason?: unknown }).reason
    return typeof r === 'string' && r.trim() ? r.trim() : undefined
  }
  return undefined
}

function asScore(value: unknown): number | undefined {
  if (typeof value === 'number') return value
  if (value && typeof value === 'object' && 'score' in value) {
    const s = (value as { score?: unknown }).score
    return typeof s === 'number' ? s : undefined
  }
  return undefined
}

export function parseRationale(rationale: Record<string, unknown>): {
  summary?: string
  dimensions: Dimension[]
} {
  const summary =
    typeof rationale.summary === 'string' && rationale.summary.trim()
      ? rationale.summary.trim()
      : undefined

  const dimensions: Dimension[] = []
  for (const [key, value] of Object.entries(rationale)) {
    if (key === 'summary' || key.startsWith('_')) continue
    const score = asScore(value)
    if (score == null) continue
    dimensions.push({ key, score, reason: asReason(value) })
  }
  dimensions.sort((a, b) => {
    const ia = ORDER.indexOf(a.key)
    const ib = ORDER.indexOf(b.key)
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib) || a.key.localeCompare(b.key)
  })
  return { summary, dimensions }
}

export function rationaleMeter(dim: Dimension): { pct: number; display: string; tone: string } {
  const scale = RATIONALE_SCALE[dim.key]
  if (scale) {
    const ratio = Math.max(0, Math.min(1, dim.score / scale.max))
    const pct = (scale.lowerIsBetter ? 1 - ratio : ratio) * 100
    const display =
      scale.max === 1 ? `${(dim.score * 100).toFixed(0)}%` : `${dim.score}${scale.hint}`
    return { pct, display, tone: toneFor(pct) }
  }
  const pct = Math.max(0, Math.min(100, dim.score))
  return { pct, display: `${dim.score}/100`, tone: toneFor(pct) }
}

function toneFor(pct: number): string {
  if (pct >= 67) return 'var(--color-emerald)'
  if (pct >= 40) return 'var(--color-cyan)'
  return 'var(--color-warning)'
}
