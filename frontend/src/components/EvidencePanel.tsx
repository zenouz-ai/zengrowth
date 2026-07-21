import { useState } from 'react'
import { Link } from 'react-router-dom'
import { StateChip } from './StateChip'
import { Skeleton } from './Skeleton'
import { useKnowledgeClaims } from '../hooks/useKnowledgeClaims'
import { NAV } from '../lib/navLabels'
import type { EvidenceClaim } from '../lib/types'

// Provenance trace for a generated material. evidence_ids are EvidenceClaim ids
// (the evidence bank is built only from verified claims), so we resolve them
// against the claim list. Any id that no longer maps to a *verified* claim is
// the anti-fabrication warning case: the material cites a claim that has since
// been rejected or unverified, or no longer exists.

export function EvidencePanel({ evidenceIds }: { evidenceIds: string[] }) {
  const [open, setOpen] = useState(false)
  const claims = useKnowledgeClaims()

  if (!evidenceIds || evidenceIds.length === 0) {
    return (
      <p className="text-xs text-muted">
        No evidence linked — this material was not generated against your approved fact bank.
      </p>
    )
  }

  const byId = new Map<string, EvidenceClaim>()
  for (const c of claims.data ?? []) byId.set(c.id, c)

  const resolved = evidenceIds.map((id) => ({ id, claim: byId.get(id) }))
  const ready = !claims.loading || claims.data != null
  const unverifiedCount = ready
    ? resolved.filter(({ claim }) => !claim || claim.verification_state !== 'verified').length
    : 0

  return (
    <section className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-2 text-left"
        >
          <span className="micro-label">Evidence</span>
          <span className="rounded-full border border-cyan/50 bg-cyan/10 px-2 py-0.5 text-xs text-cyan">
            Backed by {evidenceIds.length} fact{evidenceIds.length === 1 ? '' : 's'}
          </span>
          {ready && unverifiedCount > 0 && (
            <StateChip state="unverified" label={`${unverifiedCount} not approved`} />
          )}
          <span className="micro-label text-muted">{open ? 'hide' : 'show'}</span>
        </button>
      </div>

      {ready && unverifiedCount > 0 && (
        <p className="rounded-lg border border-warning/50 bg-warning/10 px-3 py-2 text-xs text-warning">
          This material cites {unverifiedCount} fact{unverifiedCount === 1 ? '' : 's'} that{' '}
          {unverifiedCount === 1 ? 'is' : 'are'} no longer approved. Check on {NAV.approveFacts.label} before sending.
        </p>
      )}

      {open &&
        (claims.loading && !claims.data ? (
          <Skeleton className="h-24" />
        ) : (
          <ul className="flex flex-col gap-2">
            {resolved.map(({ id, claim }) => (
              <li
                key={id}
                className="rounded-lg border border-border/70 bg-white/[0.02] p-3 text-sm"
              >
                {claim ? (
                  <>
                    <p className="leading-6">{claim.claim_text}</p>
                    {claim.source_span && (
                      <p className="mt-1 border-l-2 border-cyan/40 pl-2 text-xs italic text-muted">
                        {claim.source_span}
                      </p>
                    )}
                    <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                      <span className="flex items-center gap-2">
                        <StateChip
                          state={claim.verification_state === 'verified' ? 'verified' : 'unverified'}
                          label={claim.verification_state}
                        />
                        <span className="micro-label">
                          {claim.category} · {(claim.confidence * 100).toFixed(0)}%
                        </span>
                      </span>
                      <Link
                        to={`/knowledge/graph?source=${claim.source_document_id}`}
                        className="text-xs text-cyan hover:underline"
                      >
                        view source
                      </Link>
                    </div>
                  </>
                ) : (
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-muted">Fact {id} — no longer in the knowledge base.</span>
                    <StateChip state="error" label="missing" />
                  </div>
                )}
              </li>
            ))}
          </ul>
        ))}
    </section>
  )
}
