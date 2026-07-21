import { describe, expect, it } from 'vitest'
import { backoff, parseSSEFrame } from './useSSE'

describe('parseSSEFrame', () => {
  it('parses an audit data frame with id', () => {
    const frame = 'id: 2026-06-01T00:00:00+00:00\nevent: audit\ndata: {"action":"score_job"}'
    const parsed = parseSSEFrame(frame)
    expect(parsed.keepalive).toBe(false)
    expect(parsed.id).toBe('2026-06-01T00:00:00+00:00')
    expect(JSON.parse(parsed.data!)).toEqual({ action: 'score_job' })
  })

  it('flags keepalive comments', () => {
    expect(parseSSEFrame(': keepalive').keepalive).toBe(true)
  })
})

describe('backoff', () => {
  it('grows with the attempt and stays capped', () => {
    const a0 = backoff(0)
    const a5 = backoff(5)
    expect(a0).toBeGreaterThan(0)
    expect(a0).toBeLessThanOrEqual(1_000)
    expect(a5).toBeLessThanOrEqual(30_000)
    expect(a5).toBeGreaterThan(a0)
  })
})
