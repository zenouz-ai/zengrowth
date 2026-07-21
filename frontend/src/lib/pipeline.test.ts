import { describe, expect, it } from 'vitest'
import { byExpectedValueDesc, curationReason, groupByState } from './pipeline'
import { LIFECYCLE_STATES, type Job } from './types'

function job(p: Partial<Job>): Job {
  return {
    id: 1,
    company: 'C',
    title: 'T',
    location: null,
    hybrid_policy: null,
    compensation: null,
    seniority: null,
    application_url: null,
    posting_date: null,
    description: null,
    job_summary: null,
    summary_updated_at: null,
    source: 'manual',
    lifecycle_state: 'discovered',
    fit_score: null,
    expected_value: null,
    score_rationale: null,
    applied_at: null,
    first_response_at: null,
    outcome_stage: null,
    outcome_result: null,
    rejection_stage: null,
    outcome_notes: null,
    outcome_updated_at: null,
    created_at: '',
    updated_at: '',
    ...p,
  }
}

describe('byExpectedValueDesc', () => {
  it('sorts higher priority score first and nulls last', () => {
    const jobs = [
      job({ id: 1, expected_value: null }),
      job({ id: 2, expected_value: 5 }),
      job({ id: 3, expected_value: 12 }),
    ]
    const ids = [...jobs].sort(byExpectedValueDesc).map((j) => j.id)
    expect(ids).toEqual([3, 2, 1])
  })
})

describe('groupByState', () => {
  it('buckets every lifecycle state and sorts each by EV', () => {
    const groups = groupByState([
      job({ id: 1, lifecycle_state: 'applied', expected_value: 3 }),
      job({ id: 2, lifecycle_state: 'applied', expected_value: 9 }),
      job({ id: 3, lifecycle_state: 'discovered', expected_value: 1 }),
    ])
    expect(Object.keys(groups)).toEqual([...LIFECYCLE_STATES])
    expect(groups.applied.map((j) => j.id)).toEqual([2, 1])
    expect(groups.discovered.map((j) => j.id)).toEqual([3])
    expect(groups.offer).toEqual([])
  })
})

describe('curationReason', () => {
  const curated = job({
    lifecycle_state: 'shortlisted',
    job_summary: { role_overview: 'x' },
    summary_updated_at: '2026-01-01',
    fit_score: 80,
    expected_value: 7,
  })

  it('returns null for a fully curated job', () => {
    expect(curationReason(curated, 50)).toBeNull()
  })

  it('explains each exclusion reason', () => {
    expect(curationReason({ ...curated, lifecycle_state: 'archived' })).toBe('archived')
    expect(curationReason({ ...curated, job_summary: null })).toBe('no clean summary')
    expect(curationReason({ ...curated, fit_score: null })).toBe('not scored')
    expect(curationReason({ ...curated, source: 'greenhouse', fit_score: 20 }, 50)).toBe(
      'below fit threshold',
    )
  })

  it('never hides manual jobs for low fit once prepared', () => {
    expect(curationReason({ ...curated, source: 'manual', fit_score: 20 }, 50)).toBeNull()
  })
})
