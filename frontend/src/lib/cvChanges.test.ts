import { describe, expect, it } from 'vitest'
import { cvChangeHeadline, cvChangeLowImpact, plainCvLine } from './cvChanges'
import type { CvChangeSummary } from './types'

describe('cvChanges', () => {
  it('formats change headline', () => {
    const summary: CvChangeSummary = {
      lines_total: 19,
      lines_changed: 12,
      lines_unchanged: 7,
      change_rate: 0.632,
      summary_changed: true,
      capabilities_changed: 5,
      capabilities_total: 6,
      bullets_changed: 8,
      bullets_total: 12,
      changes: [],
    }
    expect(cvChangeHeadline(summary)).toContain('12 of 19')
    expect(cvChangeHeadline(summary)).toContain('63%')
  })

  it('flags low-impact tailoring', () => {
    expect(cvChangeLowImpact({ lines_total: 10, lines_changed: 1, change_rate: 0.1 } as CvChangeSummary)).toBe(true)
    expect(cvChangeLowImpact({ lines_total: 10, lines_changed: 5, change_rate: 0.5 } as CvChangeSummary)).toBe(false)
  })

  it('strips latex for display', () => {
    expect(plainCvLine(String.raw`\textbf{Python} $|$ FastAPI`)).toBe('Python | FastAPI')
  })
})
