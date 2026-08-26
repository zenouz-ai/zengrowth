// A semantic status chip that never relies on colour alone: every state pairs a
// glyph, a colour, and a label so verified / unverified / archived / error are
// unmistakable for colour-blind and low-contrast cases.

export type ChipState =
  | 'verified'
  | 'unverified'
  | 'draft'
  | 'rejected'
  | 'archived'
  | 'error'
  | 'final'
  | 'pending'
  | 'imported'

interface ChipStyle {
  glyph: string
  label: string
  color: string
}

const STYLES: Record<ChipState, ChipStyle> = {
  verified: { glyph: '✓', label: 'Verified', color: 'var(--color-emerald)' },
  unverified: { glyph: '!', label: 'Unverified', color: 'var(--color-warning)' },
  draft: { glyph: '○', label: 'Awaiting review', color: 'var(--color-warning)' },
  rejected: { glyph: '✕', label: 'Rejected', color: 'var(--color-loss)' },
  archived: { glyph: '⌁', label: 'Archived', color: 'var(--color-muted)' },
  error: { glyph: '✕', label: 'Error', color: 'var(--color-loss)' },
  final: { glyph: '★', label: 'Final', color: 'var(--color-emerald)' },
  pending: { glyph: '…', label: 'Pending', color: 'var(--color-cyan)' },
  imported: { glyph: '⇣', label: 'Imported', color: 'var(--color-muted)' },
}

export function StateChip({
  state,
  label,
  className = '',
}: {
  state: ChipState
  label?: string
  className?: string
}) {
  const style = STYLES[state]
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${className}`}
      style={{ color: style.color, border: `1px solid ${style.color}`, background: `${style.color}1a` }}
    >
      <span aria-hidden className="font-mono leading-none">
        {style.glyph}
      </span>
      {label ?? style.label}
    </span>
  )
}
