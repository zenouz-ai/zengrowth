import { describe, expect, it } from 'vitest'
import { coverageTone, cumulativeSeries, facetLabel } from './coverage'
import type { CoverageValue } from './types'

function value(overrides: Partial<CoverageValue>): CoverageValue {
  return {
    value: 'insurance',
    verified_claims: 0,
    draft_claims: 0,
    claim_ids: [],
    demand_jobs: 0,
    job_ids: [],
    gap: false,
    monthly: [],
    ...overrides,
  }
}

describe('facetLabel', () => {
  it('maps known facets and humanizes unknown ones', () => {
    expect(facetLabel('role_family')).toBe('Role family')
    expect(facetLabel('some_new_facet')).toBe('some new facet')
  })
})

describe('cumulativeSeries', () => {
  it('accumulates counts across the union of months', () => {
    const series = cumulativeSeries([
      value({
        value: 'insurance',
        verified_claims: 3,
        monthly: [
          { month: '2026-05', claims: 2 },
          { month: '2026-07', claims: 1 },
        ],
      }),
      value({
        value: 'healthcare',
        verified_claims: 1,
        monthly: [{ month: '2026-06', claims: 1 }],
      }),
    ])
    expect(series.keys).toEqual(['insurance', 'healthcare'])
    expect(series.rows).toEqual([
      { month: '2026-05', insurance: 2, healthcare: 0 },
      { month: '2026-06', insurance: 2, healthcare: 1 },
      { month: '2026-07', insurance: 3, healthcare: 1 },
    ])
  })

  it('caps plotted values at topN by verified depth and skips undated values', () => {
    const values = [
      value({ value: 'a', verified_claims: 5, monthly: [{ month: '2026-06', claims: 5 }] }),
      value({ value: 'b', verified_claims: 4, monthly: [{ month: '2026-06', claims: 4 }] }),
      value({ value: 'c', verified_claims: 3, monthly: [] }),
      value({ value: 'd', verified_claims: 2, monthly: [{ month: '2026-06', claims: 2 }] }),
    ]
    const series = cumulativeSeries(values, 2)
    expect(series.keys).toEqual(['a', 'b'])
  })

  it('returns empty for no dated evidence', () => {
    expect(cumulativeSeries([value({})])).toEqual({ rows: [], keys: [] })
  })
})

describe('coverageTone', () => {
  it('flags demanded-but-unverified values as the gap', () => {
    expect(coverageTone(value({ demand_jobs: 3, gap: true }))).toBe('gap')
    expect(coverageTone(value({ verified_claims: 1 }))).toBe('thin')
    expect(coverageTone(value({ verified_claims: 3 }))).toBe('solid')
    expect(coverageTone(value({}))).toBe('quiet')
  })
})
