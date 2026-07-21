import { useMemo, useState } from 'react'
import { AlertBanner } from './AlertBanner'
import { MarkdownPreview } from './MarkdownPreview'
import { EmptyState } from './EmptyState'
import { MaterialPreviewPanel } from './MaterialPreviewPanel'
import { Panel } from './Panel'
import { useAsyncData } from '../hooks/useAsyncData'
import { apiErrorMessage, downloadMaterial, generateAnswer, getMaterial } from '../lib/api'
import type { GeneratedMaterial } from '../lib/types'
import { materialStatusLabel } from '../lib/materialLabels'
import { StateChip } from './StateChip'

function latestAnswersPerQuestion(answers: GeneratedMaterial[]): GeneratedMaterial[] {
  const sorted = [...answers].sort((a, b) => b.version - a.version || b.id - a.id)
  const seen = new Set<string>()
  const result: GeneratedMaterial[] = []
  for (const answer of sorted) {
    const key = (answer.question ?? answer.title).trim().toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    result.push(answer)
  }
  return result.sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  )
}

function AnswerCard({
  jobId,
  material,
  expanded,
  onToggle,
  onUpdated,
}: {
  jobId: number
  material: GeneratedMaterial
  expanded: boolean
  onToggle: () => void
  onUpdated: () => void
}) {
  // Reuse the shared loader instead of a hand-rolled fetch effect.
  const detail = useAsyncData(() => getMaterial(jobId, material.id), [jobId, material.id])

  const question = material.question ?? material.title
  const body = detail.data?.draft_json?.body ?? detail.data?.fallback_content

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border/70 bg-black/20 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-xs uppercase tracking-wide text-muted">Question</p>
          <p className="font-medium">{question}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2 text-xs text-muted">
          {material.version > 1 && <span>v{material.version}</span>}
          {material.is_final && <StateChip state="final" />}
          <span>{materialStatusLabel(material.status)}</span>
        </div>
      </div>

      <div>
        <p className="text-xs uppercase tracking-wide text-muted">Answer</p>
        {detail.loading && !detail.data ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : detail.error ? (
          <AlertBanner tone="error">Could not load answer.</AlertBanner>
        ) : (
          <MarkdownPreview content={body ?? 'No answer text yet.'} className="mt-1" />
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onToggle}
          className="rounded-lg border border-cyan px-2 py-1 text-xs text-cyan"
        >
          {expanded ? 'Hide editor' : 'Edit'}
        </button>
        <button
          type="button"
          onClick={() => downloadMaterial(jobId, material.id, 'md')}
          className="rounded-lg border border-violet px-2 py-1 text-xs text-violet"
        >
          Download Markdown
        </button>
      </div>

      {expanded && (
        <MaterialPreviewPanel
          jobId={jobId}
          materialId={material.id}
          embedded
          onUpdated={() => {
            onUpdated()
            detail.refetch()
          }}
        />
      )}
    </li>
  )
}

interface AnswerPanelProps {
  jobId: number
  answers: GeneratedMaterial[]
  onUpdated: () => void
}

export function AnswerPanel({ jobId, answers, onUpdated }: AnswerPanelProps) {
  const [question, setQuestion] = useState('')
  const [limit, setLimit] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const listed = useMemo(() => latestAnswersPerQuestion(answers), [answers])

  async function onGenerate() {
    setBusy(true)
    setError(undefined)
    try {
      await generateAnswer(jobId, question, limit ? Number(limit) : undefined)
      setQuestion('')
      setLimit('')
      onUpdated()
    } catch (err) {
      setError(apiErrorMessage(err, 'Generate answer failed. Try again.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel title="Application answers">
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          {error && <AlertBanner tone="error">{error}</AlertBanner>}
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Application question"
            className="rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
          />
          <div className="flex gap-2">
            <input
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
              placeholder="Word limit"
              className="w-32 rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
            />
            <button
              onClick={onGenerate}
              disabled={busy || !question}
              className="rounded-lg border border-violet px-3 py-2 text-sm text-violet disabled:opacity-50"
            >
              {busy ? 'Generating…' : 'Generate answer'}
            </button>
          </div>
        </div>

        {listed.length === 0 ? (
          <EmptyState message="No application answers yet — enter a question above." />
        ) : (
          <ul className="flex flex-col gap-3">
            {listed.map((material) => (
              <AnswerCard
                key={material.id}
                jobId={jobId}
                material={material}
                expanded={expandedId === material.id}
                onToggle={() =>
                  setExpandedId((current) => (current === material.id ? null : material.id))
                }
                onUpdated={onUpdated}
              />
            ))}
          </ul>
        )}
      </div>
    </Panel>
  )
}
