import type { CvChangeSummary, CvTailoringReport } from './types'

/** One-line headline for how much the CV moved from the base template. */
export function cvChangeHeadline(summary: CvChangeSummary | null | undefined): string | null {
  if (!summary || summary.lines_total === 0) return null
  const pct = Math.round(summary.change_rate * 100)
  const parts = [`${summary.lines_changed} of ${summary.lines_total} editable lines changed (${pct}%)`]
  if (summary.summary_changed) parts.push('summary rewritten')
  if (summary.capabilities_changed > 0) {
    parts.push(`${summary.capabilities_changed}/${summary.capabilities_total} capability lines`)
  }
  if (summary.bullets_changed > 0) {
    parts.push(`${summary.bullets_changed}/${summary.bullets_total} experience bullets`)
  }
  return parts.join(' · ')
}

export function cvChangeLowImpact(summary: CvChangeSummary | null | undefined): boolean {
  return !!summary && summary.lines_total > 0 && summary.change_rate < 0.2
}

/** Plain text for a LaTeX CV line in the diff panel. */
export function plainCvLine(text: string): string {
  return text
    .replace(/\\[a-zA-Z]+\{([^}]*)\}/g, ' $1 ')
    .replace(/\\[a-zA-Z]+/g, ' ')
    .replace(/[{}$]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

export function cvGroundingProfileLabel(profile: CvTailoringReport['grounding_profile']): string {
  if (profile === 'priority') return 'Priority (fit ≥ 75)'
  if (profile === 'aligned') return 'Aligned (fit ≥ 70)'
  if (profile === 'strict') return 'Strict (fit < 70)'
  return 'Strict'
}
