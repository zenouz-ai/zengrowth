import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AlertBanner } from '../components/AlertBanner'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { createJob, extractJob } from '../lib/api'
import type { Job } from '../lib/types'

type Fields = Partial<
  Pick<
    Job,
    'company' | 'title' | 'location' | 'hybrid_policy' | 'seniority' | 'application_url' | 'posting_date' | 'description'
  >
>

const FIELD_LABELS: [keyof Fields, string][] = [
  ['company', 'Company'],
  ['title', 'Title'],
  ['location', 'Location'],
  ['hybrid_policy', 'Hybrid policy'],
  ['seniority', 'Seniority'],
  ['application_url', 'Application URL'],
  ['posting_date', 'Posting date (YYYY-MM-DD)'],
]

export function AddJob() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [raw, setRaw] = useState('')
  const [url, setUrl] = useState('')
  const [fields, setFields] = useState<Fields>({})
  const [notes, setNotes] = useState<string>()
  const [missing, setMissing] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<React.ReactNode>()

  useEffect(() => {
    const prefill = searchParams.get('url')
    if (!prefill) return
    // One-way prefill from the ?url deep link into form state; the
    // set-state-in-effect heuristic is the intended pattern for this external sync.
    /* eslint-disable react-hooks/set-state-in-effect */
    setUrl(prefill)
    setFields((f) => ({ ...f, application_url: prefill }))
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [searchParams])

  function set<K extends keyof Fields>(key: K, value: string) {
    setFields((f) => ({ ...f, [key]: value || undefined }))
  }

  async function onExtract() {
    setBusy(true)
    setError(undefined)
    try {
      const r = await extractJob(raw, url || undefined)
      setFields({
        company: r.company ?? undefined,
        title: r.title ?? undefined,
        location: r.location ?? undefined,
        hybrid_policy: r.hybrid_policy ?? undefined,
        seniority: r.seniority ?? undefined,
        application_url: r.application_url ?? url ?? undefined,
        posting_date: r.posting_date ?? undefined,
        description: r.description ?? raw,
      })
      setNotes(r.confidence_notes ?? undefined)
      setMissing(r.missing_fields ?? [])
    } catch {
      setError(
        <span>
          Couldn't read that automatically — your Claude key may be missing.{' '}
          <button className="text-cyan underline" onClick={() => navigate('/setup')}>
            Connect it in Setup
          </button>
          , or just fill the fields in below.
        </span>,
      )
    } finally {
      setBusy(false)
    }
  }

  async function onSave() {
    setBusy(true)
    setError(undefined)
    try {
      const job = await createJob({ ...fields, description: fields.description ?? raw, source: 'manual' })
      navigate(`/jobs/${job.id}`)
    } catch (err) {
      const resp = (err as { response?: { status?: number; data?: { detail?: { job_id?: number } } } })
        .response
      if (resp?.status === 409 && resp.data?.detail?.job_id) {
        const id = resp.data.detail.job_id
        setError(
          <span>
            Duplicate of an existing job.{' '}
            <button className="text-cyan underline" onClick={() => navigate(`/jobs/${id}`)}>
              Open it
            </button>
            .
          </span>,
        )
      } else {
        setError('Save failed. Company and title are required.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Add job"
        description="Paste a job description and ZenGrowth extracts the fields for you. The reference URL is stored only — it is never fetched automatically."
      />
      <Panel title="Paste to fill">
        <p className="mb-3 text-sm text-muted">
          Paste a job description; fields are extracted into the form below. The URL is stored as a
          reference only and is never fetched.
        </p>
        <textarea
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          rows={6}
          placeholder="Paste the job description…"
          className="w-full rounded-lg border border-border bg-black/30 p-3 text-sm outline-none focus:border-cyan"
        />
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="Reference URL (optional)"
          className="mt-2 w-full rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
        />
        <button
          onClick={onExtract}
          disabled={busy || !raw}
          className="mt-3 rounded-lg border border-cyan px-3 py-2 text-sm text-cyan disabled:opacity-50"
        >
          {busy ? 'Working…' : 'Extract fields'}
        </button>
        {notes && <p className="mt-3 text-xs text-muted">{notes}</p>}
        {missing.length > 0 && (
          <p className="mt-1 text-xs text-warning">Missing: {missing.join(', ')}</p>
        )}
      </Panel>

      <Panel title="Review & save">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {FIELD_LABELS.map(([key, label]) => (
            <label key={key} className="flex flex-col gap-1">
              <span className="micro-label">{label}</span>
              <input
                value={(fields[key] as string) ?? ''}
                onChange={(e) => set(key, e.target.value)}
                className="rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
              />
            </label>
          ))}
        </div>
        {error && (
          <div className="mt-4">
            <AlertBanner tone="error">{error}</AlertBanner>
          </div>
        )}
        <button
          onClick={onSave}
          disabled={busy || !fields.company || !fields.title}
          className="mt-4 rounded-lg border border-emerald px-3 py-2 text-sm text-emerald disabled:opacity-50"
        >
          Save job
        </button>
      </Panel>
    </div>
  )
}
