import type { IngestionHealth } from './types'

export type IngestionBannerTone = 'warning' | 'error'

export interface IngestionBanner {
  tone: IngestionBannerTone
  message: string
}

function formatAge(seconds: number | null): string {
  if (seconds == null) return 'a while'
  const hours = seconds / 3600
  if (hours < 1) return 'under an hour'
  if (hours < 48) return `${Math.round(hours)} hours`
  return `${Math.round(hours / 24)} days`
}

/**
 * Turn ingestion health into a dashboard banner, or null when all is well
 * (SEC-01). A silently-stopped pull is the worst failure for a career tool — an
 * empty board reads as "no new roles" — so staleness is surfaced loudly. A fresh
 * install that has never run is intentionally quiet.
 */
export function ingestionHealthBanner(health: IngestionHealth | null | undefined): IngestionBanner | null {
  if (!health || health.never_run) return null

  if (health.stale) {
    return {
      tone: 'error',
      message:
        `Job discovery hasn't completed in ${formatAge(health.age_seconds)} — the nightly pull may ` +
        `have stopped. New roles could be missing; check Data sources or run a pull from Find jobs.`,
    }
  }

  const silent = [...(health.failed_boards ?? []), ...(health.zero_row_boards ?? [])]
  if (silent.length > 0) {
    const list = silent.join(', ')
    return {
      tone: 'warning',
      message:
        `Last job pull: ${silent.length} board${silent.length === 1 ? '' : 's'} returned no roles ` +
        `(possible source outage or changed feed): ${list}.`,
    }
  }

  return null
}
