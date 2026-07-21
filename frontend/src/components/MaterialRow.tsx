import type { GeneratedMaterial } from '../lib/types'
import { materialStatusLabel, materialTypeLabel, pageFitLabel } from '../lib/materialLabels'
import { StateChip } from './StateChip'

interface MaterialRowProps {
  material: GeneratedMaterial
  expanded: boolean
  onSelect: () => void
  onDownloadPdf: () => void
  onDownloadTex: () => void
  onDownloadMd: () => void
  archived?: boolean
}

export function MaterialRow({
  material,
  expanded,
  onSelect,
  onDownloadPdf,
  onDownloadTex,
  onDownloadMd,
  archived = false,
}: MaterialRowProps) {
  const isPdf = material.material_type === 'cv' || material.material_type === 'cover_letter'
  const pdfReady = material.status === 'created_pdf'

  return (
    <div
      className={`glass flex flex-col gap-2 px-3 py-2 text-sm ${
        expanded ? 'rounded-b-none ring-1 ring-cyan/60' : ''
      } ${archived ? 'opacity-80' : ''}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" onClick={onSelect} className="text-left">
          <span className="micro-label mr-2">{materialTypeLabel(material.material_type)}</span>
          <span>v{material.version}</span>
          {material.is_final && <StateChip state="final" className="ml-2" />}
          {archived && <StateChip state="archived" className="ml-2" />}
          <span className="ml-2 text-muted">{material.title}</span>
        </button>
        <div className="flex items-center gap-2">
          {pageFitLabel(material) && (
            <span
              className={`rounded px-2 py-0.5 text-xs ${
                material.page_fit === 'ok'
                  ? 'bg-emerald/20 text-emerald'
                  : material.page_fit === 'unknown'
                    ? 'text-muted'
                    : 'bg-warning/20 text-warning'
              }`}
            >
              {pageFitLabel(material)}
            </span>
          )}
          <span className="micro-label">{materialStatusLabel(material.status)}</span>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onSelect}
          className="rounded-lg border border-cyan px-2 py-1 text-xs text-cyan"
        >
          {expanded ? 'Hide preview' : 'Preview'}
        </button>
        {isPdf && (
          <>
            <button
              type="button"
              onClick={onDownloadPdf}
              disabled={!pdfReady}
              className="rounded-lg border border-violet px-2 py-1 text-xs text-violet disabled:opacity-40"
            >
              Download PDF
            </button>
            <button
              type="button"
              onClick={onDownloadTex}
              className="rounded-lg border border-border px-2 py-1 text-xs text-muted"
            >
              Download TeX
            </button>
          </>
        )}
        {material.material_type === 'answer' && (
          <button
            type="button"
            onClick={onDownloadMd}
            className="rounded-lg border border-violet px-2 py-1 text-xs text-violet"
          >
            Download Markdown
          </button>
        )}
      </div>
    </div>
  )
}
