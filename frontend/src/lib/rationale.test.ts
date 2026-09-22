import { describe, expect, it } from 'vitest'
import { parseRationale, rationaleMeter } from './rationale'

describe('parseRationale', () => {
  it('extracts the summary and {score, reason} dimensions, composite first', () => {
    const { summary, dimensions } = parseRationale({
      summary: 'Strong fit on title and tech.',
      role_relevance: { score: 75, reason: 'Title matches.' },
      match_quality: { score: 72, reason: 'Strong overall alignment.' },
      success_probability: { score: 0.35, reason: 'Competitive but credible.' },
      _usage: { input_tokens: 10 },
    })
    expect(summary).toBe('Strong fit on title and tech.')
    // match_quality (composite) ordered ahead of role_relevance
    expect(dimensions.map((d) => d.key)).toEqual([
      'match_quality',
      'success_probability',
      'role_relevance',
    ])
    expect(dimensions[0]).toMatchObject({ score: 72, reason: 'Strong overall alignment.' })
    // internal keys (prefixed _) are dropped
    expect(dimensions.find((d) => d.key === '_usage')).toBeUndefined()
  })

  it('tolerates bare numbers and missing reasons', () => {
    const { summary, dimensions } = parseRationale({ domain_fit: 60, leadership_alignment: {} })
    expect(summary).toBeUndefined()
    // domain_fit (numeric) kept; leadership_alignment has no score -> dropped
    expect(dimensions.map((d) => d.key)).toEqual(['domain_fit'])
    expect(dimensions[0].reason).toBeUndefined()
  })
})

describe('rationaleMeter', () => {
  it('normalises 0–100 dimensions directly', () => {
    expect(rationaleMeter({ key: 'role_relevance', score: 75 })).toMatchObject({
      pct: 75,
      display: '75/100',
    })
  })

  it('inverts application_effort so lower effort fills more of the meter', () => {
    const easy = rationaleMeter({ key: 'application_effort', score: 1 })
    const hard = rationaleMeter({ key: 'application_effort', score: 5 })
    expect(easy.pct).toBeGreaterThan(hard.pct)
    expect(easy.display).toBe('1/5 effort')
  })

  it('renders success_probability as a percentage', () => {
    expect(rationaleMeter({ key: 'success_probability', score: 0.35 })).toMatchObject({
      pct: 35,
      display: '35%',
    })
  })
})
