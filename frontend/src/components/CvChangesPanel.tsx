import type { CvChangeLine, CvTailoringReport } from '../lib/types'
import { cvChangeHeadline, cvChangeLowImpact, cvGroundingProfileLabel, plainCvLine } from '../lib/cvChanges'

function changeLabel(change: CvChangeLine): string {
  if (change.section === 'summary') return 'Professional summary'
  if (change.section === 'capability') return `Core capability ${change.index + 1}`
  return `Role ${(change.role_index ?? 0) + 1}, bullet ${change.index + 1}`
}

export function CvChangesPanel({ tailoring }: { tailoring: CvTailoringReport | null | undefined }) {
  const summary = tailoring?.change_summary
  if (!summary) return null

  const headline = cvChangeHeadline(summary)
  const lowImpact = cvChangeLowImpact(summary)
  const profile = cvGroundingProfileLabel(tailoring?.grounding_profile)

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-border/70 bg-black/20 p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="micro-label">Changes from base CV</h4>
        <span className="text-xs text-muted">{profile} grounding</span>
      </div>
      {headline && <p className="text-sm text-text">{headline}</p>}
      {lowImpact && (
        <p className="text-xs text-muted">
          The PDF layout, employers, dates, and metrics stay fixed by design. With strict grounding
          most wording matches your template — reordering and light rewording only happen when every
          word is already in your verified evidence bank.
        </p>
      )}
      {summary.lines_changed === 0 ? (
        <p className="text-xs text-warning">
          No editable lines differ from your base CV. The LLM output was rejected or matched the
          template verbatim — consider using Request changes or submitting your generic CV.
        </p>
      ) : (
        <ul className="flex max-h-80 flex-col gap-2 overflow-y-auto text-xs">
          {summary.changes.map((change) => (
            <li key={`${change.section}-${change.role_index ?? 'x'}-${change.index}`} className="rounded border border-border/60 bg-black/30 p-2">
              <p className="font-medium text-cyan">{changeLabel(change)}</p>
              <p className="mt-1 text-muted">
                <span className="text-loss">−</span> {plainCvLine(change.before).slice(0, 220)}
                {plainCvLine(change.before).length > 220 ? '…' : ''}
              </p>
              <p className="mt-1 text-text">
                <span className="text-emerald">+</span> {plainCvLine(change.after).slice(0, 220)}
                {plainCvLine(change.after).length > 220 ? '…' : ''}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
