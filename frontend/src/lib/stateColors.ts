import type { LifecycleState } from './types'

// Each lifecycle state maps to a semantic colour.
export const STATE_COLORS: Record<LifecycleState, string> = {
  discovered: '#8a93ad',
  shortlisted: '#00d4ff',
  prepared: '#00d4ff',
  awaiting_approval: '#f7c948',
  approved: '#00ffa3',
  applied: '#00ffa3',
  interviewing: '#6332ff',
  offer: '#00ffa3',
  rejected: '#ff4466',
  archived: '#5a6173',
}
