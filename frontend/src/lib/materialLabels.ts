import type { CSSProperties } from 'react'
import type { CvTailoringReport, GeneratedMaterial } from './types'

// Display helpers for generated materials. Kept in lib (not the MaterialRow
// component file) so component modules export only components — react-refresh
// friendly and reusable across MaterialRow, MaterialPreviewPanel, and AnswerPanel.

const TYPE_LABELS: Record<string, string> = {
  cv: 'CV',
  cover_letter: 'Cover letter',
  answer: 'Answer',
  // Internal interview artifacts (INT-01/02/03).
  company_briefing: 'Company briefing',
  interviewer_pack: 'Interviewer pack',
  tech_prep_pack: 'Technical prep pack',
  final_round_pack: 'Final-round pack',
  debrief: 'Debrief',
  email_draft: 'Email draft',
  interviewer_sim_prompt: 'Interview simulator prompt',
  // Offer stage (OFF-01/OFF-03).
  offer_evaluation: 'Offer evaluation',
  offer_response: 'Offer response draft',
  onboarding_pack: 'Onboarding pack',
  departure_pack: 'Departure pack',
}

export function materialTypeLabel(materialType: string): string {
  return TYPE_LABELS[materialType] ?? materialType.replace(/_/g, ' ')
}

export function materialStatusLabel(status: string): string {
  if (status === 'created_pdf' || status === 'created_markdown') return 'Ready'
  if (status === 'pdf_unavailable_no_latex_compiler') return 'PDF unavailable (no LaTeX)'
  return status.replace(/_/g, ' ')
}

export function pageFitLabel(material: GeneratedMaterial): string | null {
  if (material.material_type !== 'cv' || material.page_count == null) return null
  const pages =
    material.page_fill != null
      ? (material.page_count - 1 + material.page_fill).toFixed(2)
      : String(material.page_count)
  if (material.page_fit === 'ok') return `${pages} pp - fits`
  if (material.page_fit === 'long') return `${pages} pp - too long`
  if (material.page_fit === 'short') return `${pages} pp - too short`
  return `${material.page_count} pp`
}

function sectionNeedsAttention(status: string | undefined): boolean {
  return status === 'template_fallback' || status === 'partial' || status === 'evidence_compose'
}

/** Plain-English warning when CV tailoring used fallbacks or partial application. */
export function cvTailoringWarning(tailoring: CvTailoringReport | null | undefined): string | null {
  if (!tailoring) return null
  const notes: string[] = []

  if (tailoring.summary.status === 'evidence_compose') {
    notes.push(
      'Professional Summary was composed from your closest verified claims (not an LLM rewrite).',
    )
  } else if (sectionNeedsAttention(tailoring.summary.status)) {
    notes.push('Professional Summary')
  }

  if (sectionNeedsAttention(tailoring.capabilities.status)) {
    const n = tailoring.capabilities.lines_applied ?? tailoring.capabilities.applied
    const total = tailoring.capabilities.requested
    if (tailoring.capabilities.status === 'partial' && n != null && total != null) {
      notes.push(`Core Capabilities (${n}/${total} lines tailored)`)
    } else {
      notes.push('Core Capabilities')
    }
  }

  const exp = tailoring.experience
  if (exp.status === 'partial' && exp.roles_applied != null && exp.roles_total != null) {
    notes.push(`Experience (${exp.roles_applied}/${exp.roles_total} roles adjusted)`)
  } else if (exp.status === 'template_fallback') {
    notes.push('Experience bullets')
  }

  const gaps = tailoring.alignment_gaps?.length ?? 0
  const gapNote =
    gaps > 0
      ? ` ${gaps} JD term${gaps === 1 ? '' : 's'} lack verified evidence — see gaps below.`
      : ''

  if (notes.length === 0 && gaps === 0) return null

  if (notes.length === 0) {
    return `CV generated.${gapNote} Review evidence gaps before applying.`
  }

  const profile = tailoring.grounding_profile
  const profileNote =
    profile && profile !== 'strict' ? ` (${profile} grounding — fit score ≥ threshold).` : '.'

  return `CV generated with partial alignment: ${notes.join('; ')}.${profileNote}${gapNote} Review before applying.`
}

/** Compact iframe height; native PDF viewers scroll pages inside the frame. */
export function pdfPreviewHeightStyle(_pageCount?: number | null): CSSProperties {
  return { height: 'min(70vh, 600px)', minHeight: '320px' }
}
