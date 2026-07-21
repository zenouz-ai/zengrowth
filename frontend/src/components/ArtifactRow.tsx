import { useState } from 'react'
import { AlertBanner } from './AlertBanner'
import { MarkdownPreview } from './MarkdownPreview'
import { StateChip } from './StateChip'
import { useAsyncData } from '../hooks/useAsyncData'
import { downloadMaterial, getMaterial } from '../lib/api'
import { materialTypeLabel } from '../lib/materialLabels'
import type { GeneratedMaterial } from '../lib/types'

/** One internal material (prep pack, debrief, offer document) with an
 * expandable markdown preview and download — shared by the interview
 * timeline and the Offer panel so the two render identically. */
export function ArtifactRow({ jobId, material }: { jobId: number; material: GeneratedMaterial }) {
  const [open, setOpen] = useState(false)
  const date = material.effective_date ?? material.created_at
  return (
    <div className="rounded-lg border border-border/70 bg-black/20 px-3 py-2 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" onClick={() => setOpen((v) => !v)} className="min-w-0 text-left">
          <span className="micro-label mr-2">{materialTypeLabel(material.material_type)}</span>
          <span className="text-text/90">{material.title}</span>
          {material.status === 'imported' && <StateChip state="imported" className="ml-2" />}
        </button>
        <div className="flex shrink-0 items-center gap-2 text-xs text-muted">
          {date && <span>{date.slice(0, 10)}</span>}
          <button
            type="button"
            onClick={() => downloadMaterial(jobId, material.id, 'md')}
            className="rounded border border-border px-3 py-2 hover:text-text"
          >
            Download
          </button>
        </div>
      </div>
      {open && <ArtifactPreview jobId={jobId} materialId={material.id} />}
    </div>
  )
}

function ArtifactPreview({ jobId, materialId }: { jobId: number; materialId: number }) {
  const detail = useAsyncData(() => getMaterial(jobId, materialId), [jobId, materialId])
  if (detail.loading && !detail.data) return <p className="mt-2 text-xs text-muted">Loading…</p>
  if (!detail.data) return <AlertBanner tone="error">Could not load the document.</AlertBanner>
  const content = detail.data.fallback_content ?? detail.data.draft_json?.body ?? 'No content.'
  return <MarkdownPreview content={content} className="mt-2 max-h-[70vh] overflow-y-auto" />
}
