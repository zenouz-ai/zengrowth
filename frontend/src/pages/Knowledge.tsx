import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AlertBanner } from '../components/AlertBanner'
import { EmptyState } from '../components/EmptyState'
import { FactsPipelineHelp } from '../components/FactsPipelineHelp'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { Skeleton } from '../components/Skeleton'
import { StateChip } from '../components/StateChip'
import { useAsyncData } from '../hooks/useAsyncData'
import {
  importKnowledgeInbox,
  listKnowledgeSources,
  pasteKnowledgeSource,
  uploadKnowledgeSource,
} from '../lib/api'
import { filterClaims } from '../lib/knowledgeClaimsCache'
import { useKnowledgeClaims } from '../hooks/useKnowledgeClaims'
import { NAV } from '../lib/navLabels'
import type { PasteFormat, SourceDocumentType } from '../lib/types'

const SOURCE_TYPES: SourceDocumentType[] = ['document', 'cv', 'project', 'note', 'seed']
const PASTE_FORMATS: PasteFormat[] = ['tex', 'md', 'txt']

export function Knowledge() {
  const navigate = useNavigate()
  const sources = useAsyncData(() => listKnowledgeSources(), [])
  const allClaims = useKnowledgeClaims()
  const [sourceType, setSourceType] = useState<SourceDocumentType>('document')
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState<string>()
  const [message, setMessage] = useState<string>()
  const [error, setError] = useState<string>()

  // Paste & save state.
  const [pasteText, setPasteText] = useState('')
  const [pasteFilename, setPasteFilename] = useState('')
  const [pasteFormat, setPasteFormat] = useState<PasteFormat>('tex')
  const [pasteType, setPasteType] = useState<SourceDocumentType>('cv')
  const [supersedesId, setSupersedesId] = useState<number | ''>('')
  const [promoteTemplate, setPromoteTemplate] = useState(false)

  async function run(label: string, fn: () => Promise<unknown>) {
    setBusy(label)
    setError(undefined)
    setMessage(undefined)
    try {
      await fn()
      setMessage(`${label} completed.`)
      sources.refetch()
      allClaims.refetch()
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
      setError(detail ?? `${label} failed.`)
    } finally {
      setBusy(undefined)
    }
  }

  function savePaste() {
    run('Save pasted text', () =>
      pasteKnowledgeSource({
        text: pasteText,
        filename: pasteFilename || `pasted-${pasteType}`,
        format: pasteFormat,
        source_type: pasteType,
        supersedes_id: supersedesId === '' ? null : supersedesId,
        promote_template: pasteFormat === 'tex' && promoteTemplate,
      }),
    ).then(() => {
      setPasteText('')
      setPasteFilename('')
    })
  }

  const sourceList = Array.isArray(sources.data) ? sources.data : []
  const currentSources = sourceList.filter((s) => s.is_current)
  const claims = Array.isArray(allClaims.data) ? allClaims.data : []
  const draftCount = filterClaims(claims, 'draft').length
  const verifiedCount = filterClaims(claims, 'verified').length
  const rejectedCount = filterClaims(claims, 'rejected').length

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={NAV.documents.label}
        description="Upload or paste CVs, project notes, and supporting documents. ZenGrowth extracts facts from them — approve those facts on Approve facts before they can back generated materials."
        actions={
          <Link
            to={NAV.documentGraph.to}
            className="rounded-lg border border-cyan px-3 py-2 text-sm text-cyan hover:bg-cyan/10"
          >
            Open document graph
          </Link>
        }
      />

      <FactsPipelineHelp compact />

      {message && <AlertBanner tone="success">{message}</AlertBanner>}
      {error && <AlertBanner tone="error">{error}</AlertBanner>}

      <Panel title="Add documents">
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_auto_auto]">
          <input
            type="file"
            accept=".md,.txt,.pdf,.docx,.tex"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="rounded-lg border border-border bg-black/30 px-3 py-2 text-sm"
          />
          <select
            value={sourceType}
            onChange={(e) => setSourceType(e.target.value as SourceDocumentType)}
            className="rounded-lg border border-border bg-black/30 px-3 py-2 text-sm"
          >
            {SOURCE_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
          <button
            disabled={!file || !!busy}
            onClick={() => file && run('Upload', () => uploadKnowledgeSource(file, sourceType))}
            className="rounded-lg border border-cyan px-3 py-2 text-sm text-cyan disabled:opacity-50"
          >
            Upload
          </button>
        </div>
        <button
          disabled={!!busy}
          onClick={() => run('Inbox import', importKnowledgeInbox)}
          className="mt-3 rounded-lg border border-violet px-3 py-2 text-sm text-violet disabled:opacity-50"
        >
          Import local inbox
        </button>
        <p className="mt-2 text-xs text-muted">
          Local inbox path: data/knowledge/inbox. Supported: MD, TXT, PDF, DOCX, TEX.
        </p>
      </Panel>

      <Panel title="Paste & save">
        <textarea
          value={pasteText}
          onChange={(e) => setPasteText(e.target.value)}
          placeholder="Paste LaTeX, Markdown, or plain text here — e.g. a new version of your CV style and content."
          rows={8}
          className="w-full rounded-lg border border-border bg-black/30 px-3 py-2 font-mono text-xs outline-none focus:border-cyan"
        />
        {/* The essentials are paste + Save; everything else has a sensible
            default and hides under Advanced (PS-C6). */}
        <details className="mt-3 rounded-lg border border-border/60 bg-black/20 px-3 py-2">
          <summary className="cursor-pointer select-none text-xs text-muted hover:text-text">
            Advanced options (format, type, versioning, CV template)
          </summary>
          <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-4">
            <input
              value={pasteFilename}
              onChange={(e) => setPasteFilename(e.target.value)}
              placeholder="filename (optional)"
              className="rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
            />
            <select
              value={pasteFormat}
              onChange={(e) => setPasteFormat(e.target.value as PasteFormat)}
              className="rounded-lg border border-border bg-black/30 px-3 py-2 text-sm"
            >
              {PASTE_FORMATS.map((fmt) => (
                <option key={fmt} value={fmt}>
                  save as .{fmt}
                </option>
              ))}
            </select>
            <select
              value={pasteType}
              onChange={(e) => setPasteType(e.target.value as SourceDocumentType)}
              className="rounded-lg border border-border bg-black/30 px-3 py-2 text-sm"
            >
              {SOURCE_TYPES.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
            <select
              value={supersedesId}
              onChange={(e) => setSupersedesId(e.target.value === '' ? '' : Number(e.target.value))}
              className="rounded-lg border border-border bg-black/30 px-3 py-2 text-sm"
            >
              <option value="">new document (no parent)</option>
              {currentSources.map((s) => (
                <option key={s.id} value={s.id}>
                  new version of: {s.title || s.filename}
                </option>
              ))}
            </select>
          </div>
          <label
            className={`mt-3 flex items-center gap-2 text-sm ${pasteFormat === 'tex' ? '' : 'opacity-40'}`}
          >
            <input
              type="checkbox"
              disabled={pasteFormat !== 'tex'}
              checked={pasteFormat === 'tex' && promoteTemplate}
              onChange={(e) => setPromoteTemplate(e.target.checked)}
            />
            Use as active CV template/style going forward
          </label>
        </details>
        <div className="mt-3 flex justify-end">
          <button
            disabled={!pasteText.trim() || !!busy}
            onClick={savePaste}
            className="rounded-lg border border-cyan px-3 py-2 text-sm text-cyan disabled:opacity-50"
          >
            Save
          </button>
        </div>
      </Panel>

      <Panel title="Sources">
        {sources.loading && !sources.data ? (
          <Skeleton className="h-32" />
        ) : sourceList.length === 0 ? (
          <EmptyState message="No documents yet — upload a file or paste text above to start extracting facts." />
        ) : (
          <ul className="flex flex-col gap-2">
            {sourceList.map((source) => (
              <li key={source.id}>
                <button
                  onClick={() => navigate(`/knowledge/graph?source=${source.id}`)}
                  className="glass flex w-full min-w-0 flex-col gap-2 px-3 py-2 text-left text-sm hover:bg-white/[0.04] sm:flex-row sm:items-center sm:justify-between"
                >
                  <span className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                    <span className="min-w-0 break-words font-medium">
                      {source.title || source.filename}
                    </span>
                    <span className="shrink-0 text-muted">({source.source_type})</span>
                    {source.version > 1 && (
                      <span className="micro-label shrink-0 text-cyan">v{source.version}</span>
                    )}
                    {source.template_role === 'cv_style' && source.is_current && (
                      <span className="micro-label shrink-0 text-emerald">active template</span>
                    )}
                  </span>
                  <span className="micro-label shrink-0">{source.status}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel
        title="Facts from your documents"
        actions={
          <Link
            to={NAV.approveFacts.to}
            className="rounded-lg border border-cyan px-3 py-1.5 text-sm text-cyan hover:bg-cyan/10"
          >
            {NAV.approveFacts.label} →
          </Link>
        }
      >
        {allClaims.loading && !allClaims.data ? (
          <Skeleton className="h-24" />
        ) : (
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <ClaimSummaryCard
                label="Awaiting check"
                count={draftCount}
                chip="draft"
                to={NAV.approveFacts.to}
                highlight={draftCount > 0}
              />
              <ClaimSummaryCard label="Verified" count={verifiedCount} chip="verified" />
              <ClaimSummaryCard label="Rejected" count={rejectedCount} chip="rejected" />
            </div>
            {draftCount > 0 ? (
              <p className="text-sm text-muted">
                {draftCount} fact{draftCount === 1 ? '' : 's'} need approval on{' '}
                <Link to={NAV.approveFacts.to} className="text-cyan hover:underline">
                  {NAV.approveFacts.label}
                </Link>{' '}
                before they can back generated materials.
              </p>
            ) : (
              <EmptyState message="All facts approved — new extractions below 75% confidence will appear on Approve facts." />
            )}
          </div>
        )}
      </Panel>
    </div>
  )
}

function ClaimSummaryCard({
  label,
  count,
  chip,
  to,
  highlight = false,
}: {
  label: string
  count: number
  chip: 'draft' | 'verified' | 'rejected'
  to?: string
  highlight?: boolean
}) {
  const body = (
    <div
      className={`rounded-xl border px-4 py-3 ${
        highlight ? 'border-warning/50 bg-warning/10' : 'border-border/70 bg-white/[0.02]'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="micro-label text-muted">{label}</span>
        <StateChip
          state={chip === 'draft' ? 'draft' : chip === 'verified' ? 'verified' : 'rejected'}
        />
      </div>
      <div className="mt-1 text-2xl font-semibold">{count}</div>
    </div>
  )

  if (to) {
    return (
      <Link to={to} className="block hover:opacity-90">
        {body}
      </Link>
    )
  }
  return body
}
