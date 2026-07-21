import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertBanner } from '../components/AlertBanner'
import { EmptyState } from '../components/EmptyState'
import { MetricCard } from '../components/MetricCard'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { Skeleton } from '../components/Skeleton'
import { useAsyncData } from '../hooks/useAsyncData'
import { discoverySearch, getIngestionConfig, listDiscoverySearches, runIngestion } from '../lib/api'
import { NAV } from '../lib/navLabels'
import type { DiscoveryHit, DiscoverySearchRecord } from '../lib/types'

function formatWhen(iso: string): string {
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

function HitRow({ hit }: { hit: DiscoveryHit }) {
  const addUrl = `/add?url=${encodeURIComponent(hit.url)}`
  return (
    <li className="glass min-w-0 px-3 py-2 text-sm">
      <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 flex-1">
          <a
            href={hit.url}
            target="_blank"
            rel="noreferrer"
            className="break-words text-cyan hover:underline"
          >
            {hit.title}
          </a>
          {hit.snippet && <p className="mt-1 break-words text-xs text-muted">{hit.snippet}</p>}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {hit.score != null && (
            <span className="micro-label text-muted">score {hit.score.toFixed(2)}</span>
          )}
          <Link
            to={addUrl}
            className="rounded border border-emerald px-2 py-1 text-xs text-emerald hover:bg-emerald/10"
          >
            Add to pipeline
          </Link>
        </div>
      </div>
    </li>
  )
}

function SearchHistoryItem({
  record,
  expanded,
  onToggle,
  onRerun,
}: {
  record: DiscoverySearchRecord
  expanded: boolean
  onToggle: () => void
  onRerun: () => void
}) {
  return (
    <li className="glass min-w-0">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full min-w-0 flex-col gap-1 px-3 py-2 text-left text-sm sm:flex-row sm:items-center sm:justify-between"
      >
        <span className="min-w-0 truncate font-medium">{record.query}</span>
        <span className="micro-label shrink-0 text-muted">
          {record.result_count} hit{record.result_count === 1 ? '' : 's'} · {formatWhen(record.created_at)}
        </span>
      </button>
      {expanded && (
        <div className="border-t border-border/60 px-3 pb-3 pt-2">
          <div className="mb-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={onRerun}
              className="rounded border border-cyan px-2 py-1 text-xs text-cyan"
            >
              Run again
            </button>
          </div>
          {record.results.length === 0 ? (
            <p className="text-xs text-muted">No applyable job postings matched this search.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {record.results.map((h) => (
                <HitRow key={`${record.id}-${h.url}`} hit={h} />
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  )
}

export function Discover() {
  const config = useAsyncData(() => getIngestionConfig(), [])
  const history = useAsyncData(() => listDiscoverySearches(20), [])
  const [started, setStarted] = useState(false)
  const [hits, setHits] = useState<DiscoveryHit[]>()
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState<string>()
  const [error, setError] = useState<string>()
  const [expandedId, setExpandedId] = useState<number | null>(null)

  async function onIngest() {
    setBusy('ingest')
    setError(undefined)
    setStarted(false)
    try {
      await runIngestion()
      setStarted(true)
    } catch {
      setError('Could not start ingestion. Check the API is reachable and try again.')
    } finally {
      setBusy(undefined)
    }
  }

  async function onSearch(searchQuery?: string) {
    const q = (searchQuery ?? query).trim()
    if (!q) return
    setBusy('search')
    setError(undefined)
    try {
      const results = await discoverySearch(q)
      setHits(results)
      setQuery(q)
      const records = await listDiscoverySearches(20)
      history.refetch()
      const match = records.find((r) => r.query === q)
      if (match) setExpandedId(match.id)
    } catch {
      setError(
        'Search needs a Tavily key — add one in Setup, or skip discovery and paste a job you found directly on Jobs.',
      )
    } finally {
      setBusy(undefined)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={NAV.findJobs.label}
        description="Pull new roles from configured ATS boards or search Tavily for applyable job postings. New jobs flow into Jobs after ingestion and scoring."
      />
      <Panel
        title="ATS ingestion"
        actions={
          <button
            onClick={onIngest}
            disabled={busy === 'ingest'}
            className="rounded-lg border border-cyan px-3 py-2 text-sm text-cyan disabled:opacity-50"
          >
            {busy === 'ingest' ? 'Running…' : 'Run ingestion now'}
          </button>
        }
      >
        <p className="mb-3 text-sm text-muted">
          <strong className="text-text">Run ingestion</strong> pulls open roles from your configured
          Greenhouse and Lever boards (not Tavily). It skips stale and duplicate postings, adds new
          ones as <em>discovered</em>, then optionally runs a bounded precheck: summarize, score, and
          archive roles that are off-target or below your fit threshold. It runs in the background —
          new roles appear on the Jobs board as they are scored, and progress streams to the live
          activity feed.
        </p>
        {config.data ? (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <MetricCard label="Boards" value={config.data.ats_boards.length} />
            <MetricCard label="Max age (days)" value={config.data.max_posting_age_days} />
            <MetricCard
              label="Tavily"
              value={config.data.tavily_configured ? 'configured' : 'off'}
            />
          </div>
        ) : (
          <Skeleton className="h-20" />
        )}
        {started && (
          <div className="mt-3">
            <AlertBanner tone="success">
              Ingestion started in the background. New roles will appear on the{' '}
              <Link to="/pipeline" className="underline">
                Jobs
              </Link>{' '}
              board as they are scored — follow progress in the live activity feed.
            </AlertBanner>
          </div>
        )}
      </Panel>

      <Panel title="Tavily discovery">
        <p className="mb-3 text-sm text-muted">
          Searches are scoped to ATS and careers sites with apply links. Results are saved below so
          you can revisit prior searches. Use <strong className="text-text">Add to pipeline</strong>{' '}
          to open the manual job form with the posting URL prefilled.
        </p>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Head of AI London…"
            className="min-w-0 flex-1 rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
          />
          <button
            onClick={() => onSearch()}
            disabled={busy === 'search' || !query.trim()}
            className="shrink-0 rounded-lg border border-cyan px-3 py-2 text-sm text-cyan disabled:opacity-50"
          >
            {busy === 'search' ? 'Searching…' : 'Search'}
          </button>
        </div>
        {hits && hits.length === 0 && (
          <p className="mt-3 text-sm text-muted">No applyable job postings found.</p>
        )}
        {hits && hits.length > 0 && (
          <ul className="mt-3 flex flex-col gap-2">
            {hits.map((h) => (
              <HitRow key={h.url} hit={h} />
            ))}
          </ul>
        )}
      </Panel>

      <Panel title="Recent searches">
        {history.loading && !history.data ? (
          <Skeleton className="h-20" />
        ) : (history.data ?? []).length === 0 ? (
          <EmptyState message="No searches yet — run a Tavily search above." />
        ) : (
          <ul className="flex flex-col gap-2">
            {history.data!.map((record) => (
              <SearchHistoryItem
                key={record.id}
                record={record}
                expanded={expandedId === record.id}
                onToggle={() => setExpandedId((id) => (id === record.id ? null : record.id))}
                onRerun={() => onSearch(record.query)}
              />
            ))}
          </ul>
        )}
      </Panel>

      {error && <AlertBanner tone="error">{error}</AlertBanner>}
    </div>
  )
}
