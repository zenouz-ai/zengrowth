import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertBanner } from './AlertBanner'
import { EvidencePanel } from './EvidencePanel'
import {
  downloadMaterial,
  getMaterial,
  getMaterialFileUrl,
  fitMaterialToPages,
  markMaterialFinal,
  requestMaterialRevision,
  reviseMaterial,
  unmarkMaterialFinal,
} from '../lib/api'
import type { GeneratedMaterial, GeneratedMaterialDetail, MaterialDraft } from '../lib/types'
import { materialStatusLabel, materialTypeLabel, pageFitLabel, pdfPreviewHeightStyle, cvTailoringWarning } from '../lib/materialLabels'
import { NAV } from '../lib/navLabels'
import { MaterialRow } from './MaterialRow'
import { MarkdownPreview } from './MarkdownPreview'
import { CvChangesPanel } from './CvChangesPanel'

interface MaterialPreviewPanelProps {
  jobId: number
  materialId: number | null
  onUpdated: (nextMaterialId?: number) => void
  embedded?: boolean
}

export function MaterialPreviewPanel({ jobId, materialId, onUpdated, embedded = false }: MaterialPreviewPanelProps) {
  const [detail, setDetail] = useState<GeneratedMaterialDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [showStructured, setShowStructured] = useState(false)
  const [title, setTitle] = useState('')
  const [summary, setSummary] = useState('')
  const [capabilities, setCapabilities] = useState<string[]>([])
  const [experience, setExperience] = useState<Record<string, string[]>>({})
  const [bulletsText, setBulletsText] = useState('')
  const [body, setBody] = useState('')
  const [latex, setLatex] = useState('')
  const [markdownBody, setMarkdownBody] = useState('')
  const [instruction, setInstruction] = useState('')

  useEffect(() => {
    // Fetch-on-load that also seeds the editable form from server data; the
    // set-state-in-effect heuristic is suppressed here as in useAsyncData.ts.
    /* eslint-disable react-hooks/set-state-in-effect */
    if (!materialId) {
      setDetail(null)
      return
    }
    setLoading(true)
    setError(undefined)
    getMaterial(jobId, materialId)
      .then((data) => {
        setDetail(data)
        hydrateForm(data)
      })
      .catch(() => setError('Could not load material preview.'))
      .finally(() => setLoading(false))
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [jobId, materialId])

  function hydrateForm(data: GeneratedMaterialDetail) {
    const draft = data.draft_json
    setTitle(draft?.title ?? data.title)
    setSummary(draft?.summary ?? '')
    setCapabilities(draft?.capabilities ?? [])
    setExperience(draft?.experience ?? {})
    setBulletsText((draft?.bullets ?? []).join('\n'))
    setBody(draft?.body ?? '')
    setMarkdownBody(draft?.body ?? data.fallback_content ?? '')
    setLatex(data.tex_content ?? data.fallback_content ?? '')
    setShowStructured(false)
  }

  async function saveRevision() {
    if (!detail) return
    setBusy(true)
    setError(undefined)
    try {
      const payload =
        detail.material_type === 'answer'
          ? { mode: 'structured' as const, markdown_body: markdownBody }
          : showStructured && structuredEditable(detail)
            ? {
                mode: 'structured' as const,
                draft: {
                  title,
                  summary: summary.trim() || null,
                  capabilities: detail.material_type === 'cv' ? capabilities : capabilities.length ? capabilities : undefined,
                  experience: Object.keys(experience).length ? experience : undefined,
                  bullets: bulletsText
                    .split('\n')
                    .map((line) => line.trim())
                    .filter(Boolean),
                  body: body || null,
                },
              }
            : { mode: 'latex' as const, tex: latex }
      const revised = await reviseMaterial(jobId, detail.id, payload)
      setDetail(revised)
      hydrateForm(revised)
      onUpdated(revised.id)
    } catch {
      setError('Save & recompile failed.')
    } finally {
      setBusy(false)
    }
  }

  async function submitInstruction() {
    if (!detail || !instruction.trim()) return
    setBusy(true)
    setError(undefined)
    try {
      const revised = await requestMaterialRevision(jobId, detail.id, instruction.trim())
      setDetail(revised)
      hydrateForm(revised)
      setInstruction('')
      onUpdated(revised.id)
    } catch {
      setError('Revision request failed. Try rephrasing, or edit the LaTeX directly.')
    } finally {
      setBusy(false)
    }
  }

  async function shortenToFit() {
    if (!detail) return
    setBusy(true)
    setError(undefined)
    try {
      const revised = await fitMaterialToPages(jobId, detail.id)
      setDetail(revised)
      hydrateForm(revised)
      onUpdated(revised.id)
    } catch {
      setError('Could not shorten to two pages. Try the request box or edit the LaTeX directly.')
    } finally {
      setBusy(false)
    }
  }

  async function toggleFinal() {
    if (!detail) return
    setBusy(true)
    setError(undefined)
    try {
      const next = detail.is_final
        ? await unmarkMaterialFinal(jobId, detail.id)
        : await markMaterialFinal(jobId, detail.id)
      setDetail(next)
      onUpdated()
    } catch {
      setError(detail.is_final ? 'Put back for review failed.' : 'Mark as final failed.')
    } finally {
      setBusy(false)
    }
  }

  if (!materialId) return null
  if (loading) return <p className="text-sm text-muted">Loading preview…</p>
  if (!detail) return error ? <AlertBanner tone="error">{error}</AlertBanner> : null

  const canStructuredEdit = structuredEditable(detail)
  const isPdfMaterial = detail.material_type === 'cv' || detail.material_type === 'cover_letter'
  const evidenceIds = detail.draft_json?.evidence_ids ?? detail.evidence_ids ?? []
  const tailoringWarning =
    detail.material_type === 'cv' ? cvTailoringWarning(detail.tailoring) : null
  const quality = detail.draft_json?.quality_report

  return (
    <div
      className={`flex flex-col gap-4 border border-border/70 bg-white/[0.02] p-4 ${
        embedded ? '-mt-px rounded-b-lg border-t-0 ring-1 ring-cyan/60 ring-inset' : 'mt-4 rounded-lg'
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-semibold">
            {materialTypeLabel(detail.material_type)} · v{detail.version}
            {detail.is_final && (
              <span className="ml-2 rounded bg-emerald/20 px-2 py-0.5 text-xs text-emerald">Final</span>
            )}
          </h3>
          <p className="flex items-center gap-2 text-xs text-muted">
            <span>{materialStatusLabel(detail.status)}</span>
            {pageFitLabel(detail) && (
              <span
                className={
                  detail.page_fit === 'ok'
                    ? 'text-emerald'
                    : detail.page_fit === 'unknown'
                      ? 'text-muted'
                      : 'text-warning'
                }
              >
                {pageFitLabel(detail)}
              </span>
            )}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {detail.pdf_available && (
            <button
              type="button"
              onClick={() => downloadMaterial(jobId, detail.id, 'pdf')}
              className="rounded-lg border border-violet px-3 py-1 text-xs text-violet"
            >
              Download PDF
            </button>
          )}
          {detail.page_fit === 'long' && (
            <button
              type="button"
              disabled={busy}
              onClick={shortenToFit}
              className="rounded-lg border border-warning px-3 py-1 text-xs text-warning disabled:opacity-50"
            >
              {busy ? 'Shortening…' : 'Shorten to fit 2 pages'}
            </button>
          )}
          <button
            type="button"
            disabled={busy}
            onClick={toggleFinal}
            className={`rounded-lg border px-3 py-1 text-xs disabled:opacity-50 ${
              detail.is_final ? 'border-cyan text-cyan' : 'border-emerald text-emerald'
            }`}
          >
            {detail.is_final ? 'Put back for review' : 'Mark as final'}
          </button>
        </div>
      </div>

      {error && <AlertBanner tone="error">{error}</AlertBanner>}

      {tailoringWarning && <AlertBanner tone="warning">{tailoringWarning}</AlertBanner>}

      {quality && quality.jd_match.term_count > 0 && (
        <section className="flex flex-col gap-2 rounded-lg border border-border/70 bg-black/20 p-3">
          <div className="flex flex-wrap items-center gap-3">
            <h4 className="micro-label">JD match</h4>
            <span
              className={`text-sm font-semibold ${
                (quality.jd_match.score ?? 0) >= 70
                  ? 'text-emerald'
                  : (quality.jd_match.score ?? 0) >= 40
                    ? 'text-warning'
                    : 'text-muted'
              }`}
            >
              {quality.jd_match.score}%
            </span>
            <span className="text-xs text-muted">
              {quality.jd_match.matched.length} of {quality.jd_match.term_count} key JD terms covered
              {quality.impact.content_lines > 0
                ? ` · ${quality.impact.quantified_lines} of ${quality.impact.content_lines} lines quantified`
                : ''}
            </span>
          </div>
          {quality.jd_match.missing.length > 0 && (
            <div className="flex flex-wrap items-center gap-1 text-xs">
              <span className="text-muted">Not covered:</span>
              {quality.jd_match.missing.slice(0, 10).map((term) => (
                <span
                  key={term}
                  className="rounded border border-border/60 bg-black/30 px-1.5 py-0.5 text-muted"
                >
                  {term}
                </span>
              ))}
              {quality.jd_match.missing.length > 10 && (
                <span className="text-muted">+{quality.jd_match.missing.length - 10} more</span>
              )}
            </div>
          )}
          <p className="text-xs text-muted">
            Deterministic keyword coverage against this job&apos;s description — a tailoring signal,
            not a target. Only add a term via a verified fact that genuinely supports it.
          </p>
        </section>
      )}

      {quality && quality.tells.length > 0 && (
        <AlertBanner tone="warning">
          Reads like a template in places — consider rephrasing: {quality.tells.join(', ')}
        </AlertBanner>
      )}

      {detail.material_type === 'cv' && <CvChangesPanel tailoring={detail.tailoring} />}

      {detail.material_type === 'cv' && (detail.tailoring?.alignment_gaps?.length ?? 0) > 0 && (
        <section className="flex flex-col gap-2 rounded-lg border border-warning/40 bg-warning/5 p-3">
          <h4 className="micro-label text-warning">Evidence gaps for this role</h4>
          <p className="text-xs text-muted">
            These JD terms are not yet supported by verified claims. The CV uses the closest available
            experience; add facts on{' '}
            <Link to={NAV.approveFacts.to} className="text-cyan underline">
              {NAV.approveFacts.label}
            </Link>{' '}
            if they reflect your background.
          </p>
          <ul className="flex flex-col gap-2 text-xs">
            {detail.tailoring!.alignment_gaps!.slice(0, 8).map((gap) => (
              <li key={`${gap.kind}-${gap.term}`} className="rounded border border-border/60 bg-black/20 p-2">
                <p>
                  <span className="font-medium text-text">{gap.term}</span>
                  <span className="text-muted"> — {gap.suggestion}</span>
                </p>
                {gap.closest_claim_text && (
                  <p className="mt-1 text-muted">
                    Closest verified fact: {gap.closest_claim_text.slice(0, 160)}
                    {gap.closest_claim_text.length > 160 ? '…' : ''}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {detail.material_type === 'cv' &&
        (detail.tailoring?.experience_alignment?.length ?? 0) > 0 && (
          <section className="flex flex-col gap-1 text-xs text-muted">
            <h4 className="micro-label">Experience alignment</h4>
            {detail.tailoring!.experience_alignment!.map((note) => (
              <p key={note.role_index}>
                Role {note.role_index + 1}: {note.note}
              </p>
            ))}
          </section>
        )}

      <div className="rounded-lg border border-border/70 bg-black/20 p-3">
        <EvidencePanel evidenceIds={evidenceIds} />
      </div>

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="micro-label">PDF preview</h4>
          {detail.pdf_available ? (
            <a
              href={getMaterialFileUrl(jobId, detail.id, 'pdf', 'inline')}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-lg border border-cyan px-3 py-2 text-xs text-cyan hover:bg-cyan/10"
            >
              Open full PDF
            </a>
          ) : null}
        </div>
        {detail.pdf_available ? (
          <>
            {(detail.page_count ?? 1) > 1 ? (
              <p className="text-xs text-muted">
                {detail.page_count} pages — scroll inside the preview frame to see later pages, or
                open full PDF for easier reading on mobile.
                {pageFitLabel(detail) ? ` ${pageFitLabel(detail)}.` : ''}
              </p>
            ) : null}
            <iframe
              title="PDF preview"
              src={getMaterialFileUrl(jobId, detail.id, 'pdf', 'inline')}
              style={pdfPreviewHeightStyle(detail.page_count)}
              className="w-full rounded-lg border border-border/70 bg-white"
            />
          </>
        ) : detail.material_type === 'answer' ? (
          <MarkdownPreview
            content={detail.draft_json?.body ?? detail.fallback_content ?? 'No content.'}
          />
        ) : (
          <>
            <p className="text-xs text-muted">
              No PDF available — edit the LaTeX below and recompile.
            </p>
            <DraftPreview
              draft={detail.draft_json}
              fallback={detail.fallback_content}
              kind={detail.material_type === 'cover_letter' ? 'cover_letter' : 'cv'}
            />
          </>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <h4 className="micro-label">Request changes</h4>
        <textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          rows={3}
          placeholder="Describe the change in plain language, e.g. “Make the summary shorter”, “Add Kubernetes and Terraform to Core Capabilities”, or “The formatting looks off — fix the alignment and keep it to two pages.”"
          className="rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
        />
        <button
          type="button"
          disabled={busy || !instruction.trim()}
          onClick={submitInstruction}
          className="self-start rounded-lg border border-violet px-3 py-2 text-sm text-violet disabled:opacity-50"
        >
          {busy ? 'Applying…' : 'Submit request → new version'}
        </button>
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-2">
          <h4 className="micro-label">
            {detail.material_type === 'answer'
              ? 'Edit answer'
              : showStructured && canStructuredEdit
                ? 'Edit structured fields'
                : 'LaTeX source'}
          </h4>
          {isPdfMaterial && canStructuredEdit && (
            <label className="flex items-center gap-2 text-xs text-muted">
              <input
                type="checkbox"
                checked={showStructured}
                onChange={(e) => setShowStructured(e.target.checked)}
              />
              Edit structured fields instead
            </label>
          )}
        </div>

        {detail.material_type === 'answer' && (
          <textarea
            value={markdownBody}
            onChange={(e) => setMarkdownBody(e.target.value)}
            rows={10}
            className="rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
          />
        )}

        {isPdfMaterial && !showStructured && (
          <textarea
            value={latex}
            onChange={(e) => setLatex(e.target.value)}
            rows={20}
            spellCheck={false}
            className="font-mono rounded-lg border border-border bg-black/30 px-3 py-2 text-xs outline-none focus:border-cyan"
          />
        )}

        {isPdfMaterial && showStructured && canStructuredEdit && detail.material_type === 'cv' && (
          <>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Title"
              className="rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
            />
            <label className="flex flex-col gap-1">
              <span className="micro-label">Professional summary</span>
              <textarea
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
                placeholder="Professional summary"
                rows={6}
                className="rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
              />
            </label>
            {capabilities.length > 0 && (
              <div className="flex flex-col gap-2">
                <span className="micro-label">Core capabilities</span>
                {capabilities.map((line, index) => (
                  <textarea
                    key={`cap-${index}`}
                    value={line}
                    onChange={(e) =>
                      setCapabilities((prev) => prev.map((item, i) => (i === index ? e.target.value : item)))
                    }
                    rows={2}
                    className="font-mono rounded-lg border border-border bg-black/30 px-3 py-2 text-xs outline-none focus:border-cyan"
                  />
                ))}
              </div>
            )}
            {Object.keys(experience).length > 0 && (
              <div className="flex flex-col gap-3">
                <span className="micro-label">Professional experience bullets</span>
                {Object.entries(experience)
                  .sort(([a], [b]) => Number(a) - Number(b))
                  .map(([roleIndex, bullets]) => (
                    <label key={`exp-${roleIndex}`} className="flex flex-col gap-1">
                      <span className="text-xs text-muted">Role {Number(roleIndex) + 1}</span>
                      <textarea
                        value={bullets.join('\n')}
                        onChange={(e) =>
                          setExperience((prev) => ({
                            ...prev,
                            [roleIndex]: e.target.value
                              .split('\n')
                              .map((line) => line.trim())
                              .filter(Boolean),
                          }))
                        }
                        rows={Math.max(3, bullets.length + 1)}
                        className="font-mono rounded-lg border border-border bg-black/30 px-3 py-2 text-xs outline-none focus:border-cyan"
                      />
                    </label>
                  ))}
              </div>
            )}
            <p className="text-xs text-muted">
              Structured edits update the summary, core capabilities, and experience bullets. Keep the
              same line and bullet counts and preserve LaTeX commands — invalid structure reverts to the
              template on save. Use the LaTeX editor for header, education, or layout changes.
            </p>
          </>
        )}

        {isPdfMaterial && showStructured && canStructuredEdit && detail.material_type === 'cover_letter' && (
          <>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Title"
              className="rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
            />
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Cover letter body"
              rows={10}
              className="rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
            />
          </>
        )}

        <button
          type="button"
          disabled={busy}
          onClick={saveRevision}
          className="self-start rounded-lg border border-cyan px-3 py-2 text-sm text-cyan disabled:opacity-50"
        >
          {busy ? 'Saving…' : 'Save & recompile'}
        </button>
      </section>
    </div>
  )
}

function structuredEditable(detail: GeneratedMaterialDetail): boolean {
  return detail.preview_mode === 'structured'
}

function DraftPreview({
  draft,
  fallback,
  kind,
}: {
  draft: MaterialDraft | null
  fallback?: string | null
  kind: 'cv' | 'cover_letter'
}) {
  if (!draft) {
    return (
      <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg border border-border/70 bg-black/20 p-3 text-xs">
        {fallback ?? 'No structured draft available.'}
      </pre>
    )
  }
  if (kind === 'cv') {
    return (
      <div className="flex flex-col gap-3 text-sm">
        <p className="leading-7">{draft.summary || '—'}</p>
        {(draft.capabilities ?? []).length > 0 && (
          <ul className="list-none space-y-1 pl-0 font-mono text-xs text-muted">
            {draft.capabilities!.map((line) => (
              <li key={line} className="break-words">
                {line}
              </li>
            ))}
          </ul>
        )}
        {draft.experience &&
          Object.entries(draft.experience)
            .sort(([a], [b]) => Number(a) - Number(b))
            .map(([roleIndex, bullets]) => (
              <div key={roleIndex}>
                <p className="micro-label mb-1">Role {Number(roleIndex) + 1}</p>
                <ul className="list-disc space-y-1 pl-5 text-muted">
                  {bullets.map((bullet) => (
                    <li key={bullet} className="break-words">
                      {bullet}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
        {(draft.bullets ?? []).length > 0 && (
          <ul className="list-disc space-y-2 pl-5 text-muted">
            {(draft.bullets ?? []).map((bullet) => (
              <li key={bullet}>{bullet}</li>
            ))}
          </ul>
        )}
      </div>
    )
  }
  return <p className="whitespace-pre-wrap text-sm leading-7">{draft.body || '—'}</p>
}

interface MaterialVersionListProps {
  jobId: number
  materials: GeneratedMaterial[]
  selectedId: number | null
  onSelect: (id: number) => void
  onUpdated: (nextMaterialId?: number) => void
  onDownloadPdf: (material: GeneratedMaterial) => void
  onDownloadTex: (material: GeneratedMaterial) => void
  onDownloadMd: (material: GeneratedMaterial) => void
}

function primaryMaterial(versions: GeneratedMaterial[]): GeneratedMaterial {
  const final = versions.find((material) => material.is_final)
  if (final) return final
  return versions.reduce((latest, material) => (material.version > latest.version ? material : latest))
}

function previousMaterials(
  versions: GeneratedMaterial[],
  primary: GeneratedMaterial,
): GeneratedMaterial[] {
  return versions
    .filter((material) => material.id !== primary.id)
    .sort((a, b) => b.version - a.version)
}

function MaterialVersionItem({
  jobId,
  material,
  selectedId,
  onSelect,
  onUpdated,
  onDownloadPdf,
  onDownloadTex,
  onDownloadMd,
  archived = false,
}: {
  jobId: number
  material: GeneratedMaterial
  selectedId: number | null
  onSelect: (id: number) => void
  onUpdated: (nextMaterialId?: number) => void
  onDownloadPdf: (material: GeneratedMaterial) => void
  onDownloadTex: (material: GeneratedMaterial) => void
  onDownloadMd: (material: GeneratedMaterial) => void
  archived?: boolean
}) {
  const expanded = selectedId === material.id
  return (
    <li className="flex flex-col">
      <MaterialRow
        material={material}
        expanded={expanded}
        archived={archived}
        onSelect={() => onSelect(material.id)}
        onDownloadPdf={() => onDownloadPdf(material)}
        onDownloadTex={() => onDownloadTex(material)}
        onDownloadMd={() => onDownloadMd(material)}
      />
      {expanded && (
        <MaterialPreviewPanel
          jobId={jobId}
          materialId={material.id}
          onUpdated={onUpdated}
          embedded
        />
      )}
    </li>
  )
}

export function MaterialVersionList({
  jobId,
  materials,
  selectedId,
  onSelect,
  onUpdated,
  onDownloadPdf,
  onDownloadTex,
  onDownloadMd,
}: MaterialVersionListProps) {
  const [showPrevious, setShowPrevious] = useState<Record<string, boolean>>({})

  const grouped = materials.reduce<Record<string, GeneratedMaterial[]>>((acc, material) => {
    acc[material.material_type] ??= []
    acc[material.material_type].push(material)
    return acc
  }, {})

  const order = ['cv', 'cover_letter', 'answer']

  return (
    <div className="flex flex-col gap-4">
      {order
        .filter((type) => grouped[type]?.length)
        .map((type) => {
          const versions = grouped[type]
          const primary = primaryMaterial(versions)
          const previous = previousMaterials(versions, primary)
          const previousOpen = showPrevious[type] ?? false

          return (
            <section key={type}>
              <h3 className="micro-label mb-2">{materialTypeLabel(type)}</h3>
              <ul className="flex flex-col gap-2">
                <MaterialVersionItem
                  jobId={jobId}
                  material={primary}
                  selectedId={selectedId}
                  onSelect={onSelect}
                  onUpdated={onUpdated}
                  onDownloadPdf={onDownloadPdf}
                  onDownloadTex={onDownloadTex}
                  onDownloadMd={onDownloadMd}
                />
              </ul>

              {previous.length > 0 && (
                <div className="mt-2">
                  <button
                    type="button"
                    onClick={() =>
                      setShowPrevious((current) => ({ ...current, [type]: !previousOpen }))
                    }
                    className="text-xs text-muted hover:text-text"
                  >
                    {previousOpen
                      ? `Hide ${previous.length} previous version${previous.length === 1 ? '' : 's'}`
                      : `Show ${previous.length} previous version${previous.length === 1 ? '' : 's'}`}
                  </button>
                  {previousOpen && (
                    <ul className="mt-2 flex flex-col gap-2 border-l border-border/60 pl-3">
                      {previous.map((material) => (
                        <MaterialVersionItem
                          key={material.id}
                          jobId={jobId}
                          material={material}
                          selectedId={selectedId}
                          onSelect={onSelect}
                          onUpdated={onUpdated}
                          onDownloadPdf={onDownloadPdf}
                          onDownloadTex={onDownloadTex}
                          onDownloadMd={onDownloadMd}
                          archived
                        />
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </section>
          )
        })}
    </div>
  )
}
