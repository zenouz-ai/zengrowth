import { describe, expect, it } from 'vitest'
import { cvTailoringWarning, pdfPreviewHeightStyle } from './materialLabels'
import type { CvTailoringReport } from './types'

const applied: CvTailoringReport = {
  summary: { status: 'applied' },
  capabilities: { status: 'applied', requested: 6, applied: 6 },
  experience: { status: 'applied', roles_total: 3, roles_applied: 3 },
}

describe('cvTailoringWarning', () => {
  it('returns null when all sections applied', () => {
    expect(cvTailoringWarning(applied)).toBeNull()
  })

  it('warns when summary and capabilities fell back to template', () => {
    const report: CvTailoringReport = {
      ...applied,
      summary: { status: 'template_fallback', reason: 'ungrounded_entities' },
      capabilities: { status: 'template_fallback', reason: 'group_grounded', requested: 6, applied: 0 },
    }
    const msg = cvTailoringWarning(report)
    expect(msg).toContain('Professional Summary')
    expect(msg).toContain('Core Capabilities')
    expect(msg).toContain('partial alignment')
  })

  it('notes evidence_compose summary', () => {
    const report: CvTailoringReport = {
      ...applied,
      summary: { status: 'evidence_compose', source: 'verified_claims' },
    }
    const msg = cvTailoringWarning(report)
    expect(msg).toContain('composed from your closest verified claims')
  })

  it('surfaces alignment gaps without section fallbacks', () => {
    const report: CvTailoringReport = {
      ...applied,
      alignment_gaps: [{ term: 'langgraph', kind: 'requirement', status: 'missing', suggestion: 'Add a verified fact.' }],
    }
    const msg = cvTailoringWarning(report)
    expect(msg).toContain('1 JD term')
    expect(msg).toContain('gaps below')
  })
})

describe('pdfPreviewHeightStyle', () => {
  it('caps single-page preview height', () => {
    expect(pdfPreviewHeightStyle(1)).toEqual({
      height: 'min(70vh, 600px)',
      minHeight: '320px',
    })
  })

  it('uses the same compact height for multi-page CVs', () => {
    expect(pdfPreviewHeightStyle(2)).toEqual({
      height: 'min(70vh, 600px)',
      minHeight: '320px',
    })
  })
})
