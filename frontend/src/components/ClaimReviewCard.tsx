import { useState } from 'react'
import { StateChip } from './StateChip'
import { AUTO_VERIFY_THRESHOLD, confidenceTone, reviewContext } from '../lib/claimReview'
import type { EvidenceClaim } from '../lib/types'

// The atomic unit of the safety-critical review flow. Designed so careful review
// is the path of least resistance: the source span is paired *with* the claim
// (not hidden as subtext), confidence is a calibrated meter with the auto-verify
// threshold marked, and the two actions are clearly differentiated rather than
// being equal-weight twins.

export function ClaimReviewCard({
  claim,
  busy,
  onVerify,
  onReject,
  editable = false,
  onSave,
}: {
  claim: EvidenceClaim
  busy?: boolean
  onVerify: () => void
  onReject: () => void
  editable?: boolean
  onSave?: (payload: { claim_text: string; source_span: string }) => Promise<void>
}) {
  return (
    <ClaimReviewCardBody
      key={`${claim.id}-${claim.updated_at}`}
      claim={claim}
      busy={busy}
      onVerify={onVerify}
      onReject={onReject}
      editable={editable}
      onSave={onSave}
    />
  )
}

function ClaimReviewCardBody({
  claim,
  busy,
  onVerify,
  onReject,
  editable = false,
  onSave,
}: {
  claim: EvidenceClaim
  busy?: boolean
  onVerify: () => void
  onReject: () => void
  editable?: boolean
  onSave?: (payload: { claim_text: string; source_span: string }) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [claimText, setClaimText] = useState(claim.claim_text)
  const [sourceSpan, setSourceSpan] = useState(claim.source_span ?? '')

  const pct = Math.max(0, Math.min(100, claim.confidence * 100))
  const isVerified = claim.verification_state === 'verified'
  const isRejected = claim.verification_state === 'rejected'
  const isDraft = !isVerified && !isRejected
  const hasSource = Boolean(claim.source_span && claim.source_span.trim())
  const { why, next } = reviewContext(claim)

  async function saveEdits() {
    if (!onSave) return
    setSaving(true)
    try {
      await onSave({
        claim_text: claimText.trim(),
        source_span: sourceSpan.trim(),
      })
      setEditing(false)
    } finally {
      setSaving(false)
    }
  }

  return (
    <article className="flex flex-col gap-3 rounded-xl border border-border/70 bg-white/[0.02] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <StateChip
          state={isVerified ? 'verified' : isRejected ? 'rejected' : 'draft'}
          label={isVerified ? 'Approved' : isRejected ? 'Rejected' : 'Awaiting check'}
        />
        <span className="micro-label">{claim.category}</span>
      </div>

      {isDraft && (
        <div className="rounded-lg border border-border/60 bg-white/[0.02] px-3 py-2 text-xs leading-5">
          <p className="text-muted">{why}</p>
          <p className="mt-1 text-text">{next}</p>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <p className="micro-label mb-1 text-muted">Fact</p>
          {editing ? (
            <textarea
              value={claimText}
              onChange={(e) => setClaimText(e.target.value)}
              rows={4}
              className="w-full rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
            />
          ) : (
            <p className="leading-6">{claim.claim_text}</p>
          )}
        </div>
        <div>
          <p className="micro-label mb-1 text-muted">Source excerpt</p>
          {editing ? (
            <textarea
              value={sourceSpan}
              onChange={(e) => setSourceSpan(e.target.value)}
              rows={4}
              placeholder="Paste the supporting excerpt from the source document"
              className="w-full rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
            />
          ) : hasSource ? (
            <blockquote className="rounded-lg border-l-2 border-cyan/50 bg-cyan/5 px-3 py-2 text-sm italic leading-6 text-muted">
              {claim.source_span}
            </blockquote>
          ) : (
            <p className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
              No source excerpt — cannot trace this fact to a document. Reject unless you can confirm it
              independently.
            </p>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <div className="flex items-baseline justify-between">
          <span className="micro-label text-muted">Confidence</span>
          <span className="font-mono text-xs" style={{ color: confidenceTone(claim.confidence) }}>
            {pct.toFixed(0)}% · {claim.confidence >= AUTO_VERIFY_THRESHOLD ? 'above' : 'below'}{' '}
            auto-verify bar
          </span>
        </div>
        <div className="relative h-2 w-full overflow-hidden rounded-full bg-white/[0.06]">
          <div
            className="h-full rounded-full"
            style={{ width: `${pct}%`, backgroundColor: confidenceTone(claim.confidence) }}
          />
          <span
            className="absolute top-0 h-full w-px bg-text/60"
            style={{ left: `${AUTO_VERIFY_THRESHOLD * 100}%` }}
            title="Auto-verify threshold (75%)"
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {editable && isDraft && onSave && (
            editing ? (
              <>
                <button
                  type="button"
                  disabled={busy || saving || !claimText.trim()}
                  onClick={() => void saveEdits()}
                  className="rounded-lg border border-cyan px-3 py-2 text-sm text-cyan disabled:opacity-50"
                >
                  {saving ? 'Saving…' : 'Save edits'}
                </button>
                <button
                  type="button"
                  disabled={busy || saving}
                  onClick={() => {
                    setClaimText(claim.claim_text)
                    setSourceSpan(claim.source_span ?? '')
                    setEditing(false)
                  }}
                  className="rounded-lg border border-border px-3 py-2 text-sm text-muted hover:text-text disabled:opacity-50"
                >
                  Cancel
                </button>
              </>
            ) : (
              <button
                type="button"
                disabled={busy}
                onClick={() => setEditing(true)}
                className="rounded-lg border border-border px-3 py-2 text-sm text-muted hover:text-text disabled:opacity-50"
              >
                Edit fact
              </button>
            )
          )}
          <button
            type="button"
            disabled={busy || isVerified || editing}
            onClick={onVerify}
            className="rounded-lg bg-emerald/15 px-4 py-2 text-sm font-medium text-emerald ring-1 ring-emerald/50 hover:bg-emerald/25 disabled:opacity-50"
          >
            ✓ Approve fact
          </button>
          <button
            type="button"
            disabled={busy || isRejected || editing}
            onClick={onReject}
            className="rounded-lg border border-border px-3 py-2 text-sm text-muted hover:border-loss hover:text-loss disabled:opacity-50"
          >
            ✕ Reject fact
          </button>
        </div>
      </div>
    </article>
  )
}
