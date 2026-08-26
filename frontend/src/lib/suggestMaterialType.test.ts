import { describe, expect, it } from 'vitest'
import { suggestInternalMaterialType } from './suggestMaterialType'

describe('suggestInternalMaterialType', () => {
  it('spots culture comparison from the title', () => {
    expect(suggestInternalMaterialType('Acme vs Peer culture comparison')).toBe(
      'culture_comparison',
    )
  })

  it('spots Claude Code / practice briefs as session prep', () => {
    expect(suggestInternalMaterialType('Claude Code practice brief — modelling')).toBe(
      'session_prep',
    )
  })

  it('spots rejection reflections from headings', () => {
    const body = [
      '## Gaps Versus The Bar',
      '- Depth vs the bar.',
      '## Skills And Knowledge To Deepen',
      '- Practiced credit-risk modelling.',
    ].join('\n')
    expect(suggestInternalMaterialType('Close-out notes', body)).toBe('rejection_reflection')
  })

  it('leaves generic research packs alone', () => {
    expect(suggestInternalMaterialType('Intact research pack', '# Intact\n\nBusiness overview...')).toBeNull()
  })

  it('does not treat a take-home mention in the body as session prep', () => {
    const body = 'The process includes a take-home after the hiring-manager round.'
    expect(suggestInternalMaterialType('Intact research pack', body)).toBeNull()
  })
})
