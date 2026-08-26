import { describe, expect, it } from 'vitest'
import { ingestionHealthBanner } from './ingestionHealth'
import type { IngestionHealth } from './types'

const base: IngestionHealth = {
  last_completed_at: '2026-06-30T00:00:00Z',
  age_seconds: 3600,
  stale: false,
  never_run: false,
  degraded: false,
  added: 5,
  zero_row_boards: [],
  failed_boards: [],
}

describe('ingestionHealthBanner', () => {
  it('is null for a healthy, fresh run', () => {
    expect(ingestionHealthBanner(base)).toBeNull()
  })

  it('is null when ingestion has never run (fresh install)', () => {
    expect(ingestionHealthBanner({ ...base, never_run: true, stale: true })).toBeNull()
  })

  it('is null when health is unavailable', () => {
    expect(ingestionHealthBanner(null)).toBeNull()
    expect(ingestionHealthBanner(undefined)).toBeNull()
  })

  it('returns an error banner when the pull is stale', () => {
    const banner = ingestionHealthBanner({ ...base, stale: true, age_seconds: 3 * 24 * 3600 })
    expect(banner?.tone).toBe('error')
    expect(banner?.message).toContain('3 days')
    expect(banner?.message).toContain("hasn't completed")
  })

  it('warns when a board returned zero rows', () => {
    const banner = ingestionHealthBanner({ ...base, zero_row_boards: ['greenhouse:acme'] })
    expect(banner?.tone).toBe('warning')
    expect(banner?.message).toContain('greenhouse:acme')
    expect(banner?.message).toContain('1 board')
  })

  it('warns and lists failed + zero-row boards together', () => {
    const banner = ingestionHealthBanner({
      ...base,
      failed_boards: ['lever:x'],
      zero_row_boards: ['greenhouse:acme'],
    })
    expect(banner?.tone).toBe('warning')
    expect(banner?.message).toContain('2 boards')
    expect(banner?.message).toContain('lever:x')
    expect(banner?.message).toContain('greenhouse:acme')
  })

  it('prioritises the stale error over board warnings', () => {
    const banner = ingestionHealthBanner({
      ...base,
      stale: true,
      zero_row_boards: ['greenhouse:acme'],
    })
    expect(banner?.tone).toBe('error')
  })
})
