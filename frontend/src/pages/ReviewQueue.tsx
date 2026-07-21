import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertBanner } from '../components/AlertBanner'
import { ClaimReviewCard } from '../components/ClaimReviewCard'
import { EmptyState } from '../components/EmptyState'
import { FactsPipelineHelp } from '../components/FactsPipelineHelp'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { Skeleton } from '../components/Skeleton'
import { useKnowledgeClaims } from '../hooks/useKnowledgeClaims'
import {
  reopenKnowledgeClaim,
  rejectKnowledgeClaim,
  updateKnowledgeClaim,
  verifyKnowledgeClaim,
} from '../lib/api'
import { invalidateKnowledgeClaimsCache } from '../lib/knowledgeClaimsCache'
import { NAV } from '../lib/navLabels'

const UNDO_SECONDS = 8

type RecentAction = {
  id: string
  action: 'verified' | 'rejected'
  preview: string
}

function relativeAge(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const days = Math.floor((Date.now() - then) / 86_400_000)
  if (days === 0) return 'today'
  if (days === 1) return '1 day'
  return `${days} days`
}

// The single most safety-critical screen: it prevents fabricated content from
// reaching real applications. Facts at confidence >= 0.75 with direct source
// excerpts auto-approve upstream; everything else queues here as `draft`.
export function ReviewQueue() {
  const claims = useKnowledgeClaims('draft')
  const [busyId, setBusyId] = useState<string>()
  const [error, setError] = useState<string>()
  const [recentAction, setRecentAction] = useState<RecentAction | null>(null)
  // Track this session's decisions so the operator sees review progress.
  const [decided, setDecided] = useState<Set<string>>(new Set())
  const [sessionStart] = useState(() => Date.now())

  const queue = useMemo(() => claims.data ?? [], [claims.data])
  const total = queue.length + decided.size

  const sorted = useMemo(
    // Lowest-confidence first: the claims most likely to be fabricated get the
    // most attention while the operator is freshest.
    () => [...queue].sort((a, b) => a.confidence - b.confidence),
    [queue],
  )

  const oldestWaiting = useMemo(() => {
    if (queue.length === 0) return null
    const oldest = queue.reduce((min, claim) =>
      new Date(claim.created_at).getTime() < new Date(min.created_at).getTime() ? claim : min,
    )
    return relativeAge(oldest.created_at)
  }, [queue])

  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000)
    return () => window.clearInterval(timer)
  }, [])
  const sessionMinutes = Math.max(1, Math.round((now - sessionStart) / 60_000))

  useEffect(() => {
    if (!recentAction) return
    const timer = window.setTimeout(() => setRecentAction(null), UNDO_SECONDS * 1000)
    return () => window.clearTimeout(timer)
  }, [recentAction])

  async function decide(
    id: string,
    action: 'verified' | 'rejected',
    preview: string,
    fn: () => Promise<unknown>,
  ) {
    setBusyId(id)
    setError(undefined)
    try {
      await fn()
      invalidateKnowledgeClaimsCache()
      setDecided((prev) => new Set(prev).add(id))
      setRecentAction({ id, action, preview })
      await claims.refetch()
    } catch {
      setError('Action failed — the claim was not updated.')
    } finally {
      setBusyId(undefined)
    }
  }

  async function undoRecent() {
    if (!recentAction) return
    setBusyId(recentAction.id)
    setError(undefined)
    try {
      await reopenKnowledgeClaim(recentAction.id)
      invalidateKnowledgeClaimsCache()
      setDecided((prev) => {
        const next = new Set(prev)
        next.delete(recentAction.id)
        return next
      })
      setRecentAction(null)
      await claims.refetch()
    } catch {
      setError('Undo failed — the claim was not reopened.')
    } finally {
      setBusyId(undefined)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={NAV.approveFacts.label}
        description="Compare each extracted fact with its source excerpt from your documents. Approve facts you would stand behind on a real application — only approved facts can appear in generated CVs and cover letters."
        actions={
          <Link to={NAV.documents.to} className="micro-label hover:text-text">
            manage documents
          </Link>
        }
      />

      <FactsPipelineHelp />

      {error && <AlertBanner tone="error">{error}</AlertBanner>}

      {recentAction && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-emerald/40 bg-emerald/10 px-4 py-3 text-sm">
          <span>
            {recentAction.action === 'verified' ? 'Approved' : 'Rejected'}{' '}
            <span className="text-muted">— {recentAction.preview}</span>
          </span>
          <button
            type="button"
            disabled={!!busyId}
            onClick={() => void undoRecent()}
            className="rounded-lg border border-cyan px-3 py-1.5 text-sm text-cyan hover:bg-cyan/10 disabled:opacity-50"
          >
            Undo ({UNDO_SECONDS}s)
          </button>
        </div>
      )}

      {/* One clear backlog number; the progress bar appears only once the
          operator has started reviewing, so it never clutters an idle queue. */}
      <div className="flex flex-wrap items-center gap-4 rounded-xl border border-border/70 bg-white/[0.02] px-4 py-3">
        <div>
          <div className="micro-label text-muted">Awaiting check</div>
          <div className="text-2xl font-semibold">{queue.length}</div>
        </div>
        {oldestWaiting && queue.length > 0 && (
          <div>
            <div className="micro-label text-muted">Oldest waiting</div>
            <div className="text-sm font-medium">{oldestWaiting}</div>
          </div>
        )}
        {decided.size > 0 && (
          <div>
            <div className="micro-label text-muted">Throughput</div>
            <div className="text-sm font-medium">
              {decided.size} reviewed · ~{(decided.size / sessionMinutes).toFixed(1)}/min
            </div>
          </div>
        )}
        {decided.size > 0 && total > 0 && (
          <div className="ml-auto flex min-w-[160px] flex-1 flex-col gap-1 sm:max-w-xs">
            <div className="flex justify-between micro-label text-muted">
              <span>Checked this session</span>
              <span>
                {decided.size}/{total}
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
              <div
                className="h-full rounded-full bg-emerald transition-all"
                style={{ width: `${(decided.size / total) * 100}%` }}
              />
            </div>
          </div>
        )}
      </div>

      <Panel title="Queue">
        <p className="mb-4 text-xs text-muted">
          Lowest-confidence facts appear first. Edit a fact if the wording is wrong, then approve or
          reject. You have 8 seconds to undo after each decision.
        </p>
        {claims.loading && !claims.data ? (
          <Skeleton className="h-64" />
        ) : sorted.length === 0 ? (
          <div className="flex flex-col gap-4">
            <EmptyState message="All clear — no facts waiting for approval. New extractions below 75% confidence will appear here." />
            <FactsPipelineHelp compact />
          </div>
        ) : (
          <ul className="flex flex-col gap-4">
            {sorted.map((claim) => (
              <li key={claim.id}>
                <ClaimReviewCard
                  claim={claim}
                  busy={busyId === claim.id}
                  editable
                  onSave={async (payload) => {
                    await updateKnowledgeClaim(claim.id, payload)
                    invalidateKnowledgeClaimsCache()
                    await claims.refetch()
                  }}
                  onVerify={() =>
                    decide(claim.id, 'verified', claim.claim_text.slice(0, 60), () =>
                      verifyKnowledgeClaim(claim.id),
                    )
                  }
                  onReject={() =>
                    decide(claim.id, 'rejected', claim.claim_text.slice(0, 60), () =>
                      rejectKnowledgeClaim(claim.id),
                    )
                  }
                />
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  )
}
