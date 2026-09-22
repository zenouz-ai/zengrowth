import { useState } from 'react'
import { AlertBanner } from './AlertBanner'
import { MarkdownPreview } from './MarkdownPreview'
import { StateChip } from './StateChip'
import { useAsyncData } from '../hooks/useAsyncData'
import {
  apiErrorMessage,
  deleteMaterial,
  downloadMaterial,
  getMaterial,
  patchMaterialMeta,
  reviseMaterialMarkdown,
} from '../lib/api'
import { materialTypeLabel } from '../lib/materialLabels'
import {
  INTERNAL_MATERIAL_TYPES,
  type GeneratedMaterial,
  type Interview,
  type InternalMaterialType,
} from '../lib/types'

/** One internal material (prep pack, debrief, offer document) with an
 * expandable markdown preview and download — shared by the interview
 * timeline and the Offer panel so the two render identically. */
export function ArtifactRow({
  jobId,
  material,
  interviews = [],
  onChanged,
}: {
  jobId: number
  material: GeneratedMaterial
  interviews?: Interview[]
  onChanged?: () => void
}) {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const date = material.effective_date ?? material.created_at
  const canManage = !!onChanged

  async function run(fn: () => Promise<unknown>, fallback: string) {
    setBusy(true)
    setError(undefined)
    try {
      await fn()
      onChanged?.()
    } catch (err) {
      setError(apiErrorMessage(err, fallback))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-lg border border-border/70 bg-black/20 px-3 py-2 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" onClick={() => setOpen((v) => !v)} className="min-w-0 text-left">
          <span className="micro-label mr-2">{materialTypeLabel(material.material_type)}</span>
          <span className="text-text/90">{material.title}</span>
          {material.status === 'imported' && <StateChip state="imported" className="ml-2" />}
        </button>
        <div className="flex shrink-0 flex-wrap items-center gap-2 text-xs text-muted">
          {date && <span>{date.slice(0, 10)}</span>}
          <button
            type="button"
            onClick={() => downloadMaterial(jobId, material.id, 'md')}
            className="rounded border border-border px-3 py-2 hover:text-text"
          >
            Download
          </button>
          {canManage && (
            <>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setOpen(true)
                  setEditing((v) => !v)
                }}
                className="rounded border border-cyan px-3 py-2 text-cyan disabled:opacity-50"
              >
                {editing ? 'Cancel edit' : 'Edit'}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  if (!window.confirm(`Delete “${material.title}”? This cannot be undone.`)) return
                  void run(
                    () => deleteMaterial(jobId, material.id),
                    'Could not delete this document.',
                  )
                }}
                className="rounded border border-warning/60 px-3 py-2 text-warning disabled:opacity-50"
              >
                Delete
              </button>
            </>
          )}
        </div>
      </div>
      {error && (
        <div className="mt-2">
          <AlertBanner tone="error">{error}</AlertBanner>
        </div>
      )}
      {canManage && interviews.length > 0 && (
        <label className="mt-2 flex max-w-sm flex-col gap-1 text-xs text-muted">
          Link to round
          <select
            value={material.interview_id ?? ''}
            disabled={busy}
            onChange={(e) => {
              const value = e.target.value
              void run(
                () =>
                  value
                    ? patchMaterialMeta(jobId, material.id, { interview_id: Number(value) })
                    : patchMaterialMeta(jobId, material.id, { clear_interview: true }),
                'Could not update the round link.',
              )
            }}
            className="rounded-lg border border-border bg-black/30 px-2 py-1.5 text-sm outline-none focus:border-cyan"
          >
            <option value="">Job-level (no round)</option>
            {interviews.map((round) => (
              <option key={round.id} value={round.id}>
                {round.title || round.round_type.replace(/_/g, ' ')}
              </option>
            ))}
          </select>
        </label>
      )}
      {canManage && (
        <label className="mt-2 flex max-w-sm flex-col gap-1 text-xs text-muted">
          Type
          <select
            value={material.material_type}
            disabled={busy}
            onChange={(e) => {
              const material_type = e.target.value as InternalMaterialType
              void run(
                () => patchMaterialMeta(jobId, material.id, { material_type }),
                'Could not reclassify this document.',
              )
            }}
            className="rounded-lg border border-border bg-black/30 px-2 py-1.5 text-sm outline-none focus:border-cyan"
          >
            {INTERNAL_MATERIAL_TYPES.map((t) => (
              <option key={t} value={t}>
                {materialTypeLabel(t)}
              </option>
            ))}
          </select>
        </label>
      )}
      {open && (
        <ArtifactPreview
          jobId={jobId}
          materialId={material.id}
          editing={editing}
          busy={busy}
          onSave={async (body) => {
            await run(
              () => reviseMaterialMarkdown(jobId, material.id, body),
              'Could not save the edit.',
            )
            setEditing(false)
          }}
        />
      )}
    </div>
  )
}

function ArtifactPreview({
  jobId,
  materialId,
  editing,
  busy,
  onSave,
}: {
  jobId: number
  materialId: number
  editing: boolean
  busy: boolean
  onSave: (body: string) => Promise<void>
}) {
  const detail = useAsyncData(() => getMaterial(jobId, materialId), [jobId, materialId])
  const [draft, setDraft] = useState<string>()
  if (detail.loading && !detail.data) return <p className="mt-2 text-xs text-muted">Loading…</p>
  if (!detail.data) return <AlertBanner tone="error">Could not load the document.</AlertBanner>
  const content = detail.data.fallback_content ?? detail.data.draft_json?.body ?? 'No content.'
  if (editing) {
    const value = draft ?? content
    return (
      <div className="mt-2 flex flex-col gap-2">
        <textarea
          value={value}
          onChange={(e) => setDraft(e.target.value)}
          rows={16}
          className="w-full rounded-lg border border-border bg-black/30 px-3 py-2 font-mono text-xs outline-none focus:border-cyan"
        />
        <button
          type="button"
          disabled={busy}
          onClick={() => onSave(value)}
          className="self-start rounded-lg border border-cyan px-3 py-2 text-xs text-cyan disabled:opacity-50"
        >
          Save new version
        </button>
      </div>
    )
  }
  return <MarkdownPreview content={content} className="mt-2 max-h-[70vh] overflow-y-auto" />
}
