import { STATE_COLORS } from '../lib/stateColors'
import type { LifecycleState } from '../lib/types'

export function StatusPill({ state }: { state: LifecycleState }) {
  const color = STATE_COLORS[state] ?? '#8a93ad'
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
      style={{ color, border: `1px solid ${color}`, background: `${color}1a` }}
    >
      {state.replace(/_/g, ' ')}
    </span>
  )
}
