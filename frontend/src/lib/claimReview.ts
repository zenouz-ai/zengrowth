import type { EvidenceClaim } from './types'

export const AUTO_VERIFY_THRESHOLD = 0.75

export function confidenceTone(confidence: number): string {
  if (confidence >= AUTO_VERIFY_THRESHOLD) return 'var(--color-emerald)'
  if (confidence >= 0.5) return 'var(--color-warning)'
  return 'var(--color-loss)'
}

export function reviewContext(claim: EvidenceClaim): { why: string; next: string } {
  const hasSource = Boolean(claim.source_span && claim.source_span.trim())
  const belowBar = claim.confidence < AUTO_VERIFY_THRESHOLD

  let why: string
  if (!hasSource && belowBar) {
    why = 'Needs checking: no source excerpt and confidence below 75%.'
  } else if (!hasSource) {
    why = 'Needs checking: no source excerpt to compare against your documents.'
  } else if (belowBar) {
    why = 'Needs checking: confidence below the 75% auto-approve bar.'
  } else {
    why = 'Needs a quick human check before it can be used in CV generation.'
  }

  let next: string
  if (claim.verification_state === 'verified') {
    next = 'Approved — available for CV and cover-letter generation.'
  } else if (claim.verification_state === 'rejected') {
    next = 'Rejected — excluded from generated materials.'
  } else {
    next = 'If you approve this fact, it can back generated CVs and cover letters.'
  }

  return { why, next }
}
