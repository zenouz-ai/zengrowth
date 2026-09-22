import { useEffect, useState } from 'react'
import {
  activateKnowledgeVersion,
  getKnowledgeSource,
  getKnowledgeVersionDiff,
  knowledgeSourceFileUrl,
  promoteKnowledgeTemplate,
  rejectKnowledgeClaim,
  summarizeKnowledgeVersionDiff,
  verifyKnowledgeClaim,
} from '../lib/api'
import { useAsyncData } from '../hooks/useAsyncData'
import { invalidateKnowledgeClaimsCache } from '../lib/knowledgeClaimsCache'
import type { SourceDocument } from '../lib/types'
import { ClaimReviewCard } from './ClaimReviewCard'
import { Skeleton } from './Skeleton'
import { SourceFilePreview } from './SourceFilePreview'

interface SourceDetailPanelProps {
  sourceId: number | null
  onClose: () => void
  onChanged?: () => void
}

const PDF_EXT = /\.pdf$/i

export function SourceDetailPanel({ sourceId, onClose, onChanged }: SourceDetailPanelProps) {
  const detail = useAsyncData(
    () => (sourceId == null ? Promise.resolve(null) : getKnowledgeSource(sourceId)),
    [sourceId],
  )
  const [busy, setBusy] = useState<string>()
  const [error, setError] = useState<string>()
  const [compareBase, setCompareBase] = useState<number>()
  const [compareTarget, setCompareTarget] = useState<number>()
  const [changeSummary, setChangeSummary] = useState<string>()
  const [summarizing, setSummarizing] = useState(false)

  const versions = detail.data?.versions ?? []

  // Default the comparison to the selected version vs its immediate predecessor.
  useEffect(() => {
    // Resets derived comparison state when the selected source changes; the
    // set-state-in-effect heuristic is suppressed here as in useAsyncData.ts.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setChangeSummary(undefined)
    if (detail.data && versions.length > 1) {
      const targetId = detail.data.id
      const idx = versions.findIndex((v) => v.id === targetId)
      const predecessor = versions[idx + 1] ?? versions.find((v) => v.id !== targetId)
      setCompareTarget(targetId)
      setCompareBase(predecessor?.id)
    } else {
      setCompareTarget(undefined)
      setCompareBase(undefined)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.data?.id, versions.length])

  const diff = useAsyncData(
    () =>
      compareBase == null || compareTarget == null || compareBase === compareTarget
        ? Promise.resolve(null)
        : getKnowledgeVersionDiff(compareTarget, compareBase),
    [compareBase, compareTarget],
  )

  async function summarizeChanges() {
    if (compareBase == null || compareTarget == null || compareBase === compareTarget) return
    setSummarizing(true)
    setError(undefined)
    try {
      setChangeSummary(await summarizeKnowledgeVersionDiff(compareTarget, compareBase))
    } catch (err) {
      const msg = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
      setError(msg ?? 'Summarize changes failed.')
    } finally {
      setSummarizing(false)
    }
  }

  async function run(label: string, fn: () => Promise<unknown>) {
    setBusy(label)
    setError(undefined)
    try {
      await fn()
      if (label.toLowerCase().includes('claim')) invalidateKnowledgeClaimsCache()
      detail.refetch()
      onChanged?.()
    } catch (err) {
      const msg = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
      setError(msg ?? `${label} failed.`)
    } finally {
      setBusy(undefined)
    }
  }

  if (sourceId == null) {
    return (
      <aside className="glass flex h-full items-center justify-center p-6 text-sm text-muted">
        Select a node to inspect its original file, summary, versions, and extracted facts.
      </aside>
    )
  }

  const source = detail.data ?? undefined
  const isTex = !!source && /\.tex$/i.test(source.filename)
  const fileUrl = source ? knowledgeSourceFileUrl(source.id, 'original') : ''
  const isPdf = !!source && PDF_EXT.test(source.filename)
  const isPreviewable = !!source && /\.(md|txt|tex)$/i.test(source.filename)

  return (
    <aside className="glass flex h-full flex-col gap-4 overflow-y-auto p-5">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-heading text-lg font-semibold">
            {source?.title || source?.filename || 'Source'}
          </h3>
          {source && (
            <p className="mt-1 text-xs text-muted">
              {source.filename} · {source.source_type} · v{source.version}
              {source.is_current ? ' · current' : ''}
            </p>
          )}
        </div>
        <button onClick={onClose} className="micro-label hover:text-text">
          close
        </button>
      </header>

      {error && (
        <div className="rounded-lg border border-loss/60 bg-loss/10 px-3 py-2 text-xs text-loss">
          {error}
        </div>
      )}

      {detail.loading && !source ? (
        <Skeleton className="h-48" />
      ) : !source ? (
        <p className="text-sm text-muted">Source not found.</p>
      ) : (
        <>
          {source.template_role === 'cv_style' && source.is_current && (
            <div className="rounded-lg border border-emerald/50 bg-emerald/10 px-3 py-2 text-xs text-emerald">
              Active CV template/style — used by future CV generation.
            </div>
          )}

          {source.summary && (
            <section>
              <p className="micro-label mb-1">Summary</p>
              <p className="text-sm leading-6">{source.summary}</p>
            </section>
          )}

          <section>
            <div className="mb-2 flex items-center justify-between">
              <p className="micro-label">Original file</p>
              <a
                href={fileUrl}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-cyan hover:underline"
              >
                open in new tab
              </a>
            </div>
            {isPdf ? (
              <iframe title="original" src={fileUrl} className="h-72 w-full rounded-lg border border-border bg-black/30" />
            ) : isPreviewable ? (
              <SourceFilePreview sourceId={source.id} filename={source.filename} />
            ) : (
              <p className="text-xs text-muted">Preview not available for this format.</p>
            )}
          </section>

          {isTex && !(source.template_role === 'cv_style' && source.is_current) && (
            <button
              disabled={!!busy}
              onClick={() => run('Promote template', () => promoteKnowledgeTemplate(source.id))}
              className="rounded-lg border border-emerald px-3 py-2 text-sm text-emerald disabled:opacity-50"
            >
              Use as active CV template/style
            </button>
          )}

          {source.versions && source.versions.length > 1 && (
            <section>
              <p className="micro-label mb-2">Versions</p>
              <ul className="flex flex-col gap-2">
                {source.versions.map((v: SourceDocument) => (
                  <li
                    key={v.id}
                    className="flex items-center justify-between rounded-lg border border-border/70 bg-white/[0.02] px-3 py-2 text-sm"
                  >
                    <span>
                      v{v.version}
                      {v.is_current && <span className="ml-2 micro-label text-cyan">current</span>}
                    </span>
                    {!v.is_current && (
                      <button
                        disabled={!!busy}
                        onClick={() => run('Activate version', () => activateKnowledgeVersion(v.id))}
                        className="rounded-lg border border-cyan px-2 py-1 text-xs text-cyan disabled:opacity-50"
                      >
                        make current
                      </button>
                    )}
                  </li>
                ))}
              </ul>

              <div className="mt-3 rounded-lg border border-border/70 bg-white/[0.02] p-3">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="text-muted">Compare</span>
                  <select
                    value={compareBase ?? ''}
                    onChange={(e) => setCompareBase(Number(e.target.value))}
                    className="rounded border border-border bg-black/30 px-2 py-1"
                  >
                    {source.versions.map((v) => (
                      <option key={v.id} value={v.id}>
                        v{v.version}
                      </option>
                    ))}
                  </select>
                  <span className="text-muted">to</span>
                  <select
                    value={compareTarget ?? ''}
                    onChange={(e) => setCompareTarget(Number(e.target.value))}
                    className="rounded border border-border bg-black/30 px-2 py-1"
                  >
                    {source.versions.map((v) => (
                      <option key={v.id} value={v.id}>
                        v{v.version}
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={summarizeChanges}
                    disabled={summarizing || compareBase === compareTarget}
                    className="ml-auto rounded border border-cyan px-2 py-1 text-cyan disabled:opacity-50"
                  >
                    {summarizing ? 'Summarizing…' : 'Summarize changes'}
                  </button>
                </div>

                {changeSummary && (
                  <p className="mt-2 rounded bg-cyan/10 px-3 py-2 text-xs leading-5 text-cyan">
                    {changeSummary}
                  </p>
                )}

                {compareBase === compareTarget ? (
                  <p className="mt-2 text-xs text-muted">Pick two different versions to compare.</p>
                ) : diff.loading && !diff.data ? (
                  <div className="mt-2">
                    <Skeleton className="h-24" />
                  </div>
                ) : diff.data ? (
                  <>
                    <p className="mt-2 micro-label">
                      <span className="text-emerald">+{diff.data.added}</span>{' '}
                      <span className="text-loss">−{diff.data.removed}</span> lines
                    </p>
                    {diff.data.lines.length === 0 ? (
                      <p className="mt-1 text-xs text-muted">No textual differences.</p>
                    ) : (
                      <pre className="mt-1 max-h-72 overflow-auto rounded bg-black/40 p-2 text-[11px] leading-4">
                        {diff.data.lines.map((line, i) => (
                          <div
                            key={i}
                            className={
                              line.op === 'add'
                                ? 'text-emerald'
                                : line.op === 'remove'
                                  ? 'text-loss'
                                  : line.op === 'gap'
                                    ? 'italic text-muted'
                                    : 'text-muted'
                            }
                          >
                            {line.op === 'add'
                              ? '+ '
                              : line.op === 'remove'
                                ? '- '
                                : line.op === 'gap'
                                  ? ''
                                  : '  '}
                            {line.text || ' '}
                          </div>
                        ))}
                      </pre>
                    )}
                  </>
                ) : null}
              </div>
            </section>
          )}

          {source.meta && Object.keys(source.meta).length > 0 && (
            <section>
              <p className="micro-label mb-2">Attributes</p>
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                {Object.entries(source.meta as Record<string, unknown>).map(([k, val]) => (
                  <div key={k} className="contents">
                    <dt className="text-muted">{k}</dt>
                    <dd className="truncate">{String(val)}</dd>
                  </div>
                ))}
              </dl>
            </section>
          )}

          <section>
            <p className="micro-label mb-2">Facts ({source.claims.length})</p>
            {source.claims.length === 0 ? (
              <p className="text-xs text-muted">No facts extracted from this source.</p>
            ) : (
              <ul className="flex flex-col gap-3">
                {source.claims.map((claim) => (
                  <li key={claim.id}>
                    <ClaimReviewCard
                      claim={claim}
                      busy={!!busy}
                      onVerify={() => run('Verify fact', () => verifyKnowledgeClaim(claim.id))}
                      onReject={() => run('Reject fact', () => rejectKnowledgeClaim(claim.id))}
                    />
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </aside>
  )
}
