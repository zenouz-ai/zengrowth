import { useState } from 'react'
import { EmptyState } from './EmptyState'
import { Skeleton } from './Skeleton'
import type { AuditEntry } from '../lib/types'

const INITIAL_VISIBLE = 12

// A durable, entity-scoped, human-readable decision history. Persisted entries
// come from /audit (survive reloads); live SSE deltas are merged on top and
// tagged so the stream annotates the timeline rather than replacing it.

const ACTION_LABELS: Record<string, string> = {
  score_job: 'Scored job',
  summarize_job: 'Cleaned job summary',
  generate_material: 'Generated material',
  revise_material: 'Revised material',
  mark_material_final: 'Marked material final',
  change_state: 'Changed lifecycle state',
  record_outcome: 'Recorded outcome',
  create_job: 'Job added',
  llm_call: 'LLM call',
}

function humanize(action: string): string {
  return ACTION_LABELS[action] ?? action.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const secs = Math.round((Date.now() - then) / 1000)
  if (secs < 60) return 'just now'
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return new Date(iso).toLocaleDateString()
}

function detailHint(entry: AuditEntry): string | undefined {
  const d = entry.detail
  if (!d) return undefined
  const parts: string[] = []
  if (typeof d.expected_value === 'number') {
    parts.push(`Priority ${(d.expected_value as number).toFixed(1)}`)
  }
  if (typeof d.fit_score === 'number') parts.push(`fit ${d.fit_score}`)
  if (typeof d.material_type === 'string') parts.push(d.material_type as string)
  if (typeof d.to_state === 'string') parts.push(`→ ${(d.to_state as string).replace(/_/g, ' ')}`)
  return parts.length ? parts.join(' · ') : undefined
}

export function AuditTimeline({
  persisted,
  live,
  loading,
}: {
  persisted: AuditEntry[]
  live: AuditEntry[]
  loading?: boolean
}) {
  const [expanded, setExpanded] = useState(false)

  // De-duplicate by id, preferring persisted; live-only items (not yet flushed)
  // are flagged so the operator can see real-time deltas before reload.
  const byId = new Map<number, { entry: AuditEntry; live: boolean }>()
  for (const entry of persisted) byId.set(entry.id, { entry, live: false })
  for (const entry of live) if (!byId.has(entry.id)) byId.set(entry.id, { entry, live: true })

  const rows = [...byId.values()].sort(
    (a, b) => new Date(b.entry.timestamp).getTime() - new Date(a.entry.timestamp).getTime(),
  )

  if (loading && persisted.length === 0 && live.length === 0) return <Skeleton className="h-24" />
  if (rows.length === 0) return <EmptyState message="No recorded activity for this job yet." />

  const visible = expanded ? rows : rows.slice(0, INITIAL_VISIBLE)

  return (
    <>
    <ul className="flex flex-col">
      {visible.map(({ entry, live: isLive }, i) => (
        <li
          key={`${entry.id}-${entry.timestamp}-${i}`}
          className="flex items-start gap-3 border-l border-border/70 py-2 pl-4"
        >
          <span
            className="mt-1.5 -ml-[21px] h-2 w-2 shrink-0 rounded-full"
            style={{ backgroundColor: isLive ? 'var(--color-cyan)' : 'var(--color-muted)' }}
          />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
              <span className="text-sm">
                {humanize(entry.action)}
                {isLive && <span className="ml-2 micro-label text-cyan">live</span>}
              </span>
              <span className="micro-label">{relativeTime(entry.timestamp)}</span>
            </div>
            <div className="flex flex-wrap items-center gap-x-2 text-xs text-muted">
              <span>{entry.actor}</span>
              {detailHint(entry) && <span>· {detailHint(entry)}</span>}
            </div>
          </div>
        </li>
      ))}
    </ul>
    {rows.length > INITIAL_VISIBLE && (
      <button
        onClick={() => setExpanded((v) => !v)}
        className="mt-2 micro-label text-muted hover:text-text"
      >
        {expanded ? 'Show less' : `Show ${rows.length - INITIAL_VISIBLE} earlier`}
      </button>
    )}
    </>
  )
}
