import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertBanner } from '../components/AlertBanner'
import { Panel } from '../components/Panel'
import { getSettingsStatus, saveApiKey, uploadKnowledgeSource } from '../lib/api'
import { useAsyncData } from '../hooks/useAsyncData'
import type { KnowledgeIngestResult, SettingsStatus } from '../lib/types'

const STEPS = ['Connect Claude', 'Add your CV', 'Confirm style'] as const

// First-run wizard (PS-P1/PS-P4): one decision per screen, every step skippable.
// Gives step 1 of the canonical journey (add an LLM key) a real home so a new
// user reaches value without editing .env.
export function Setup() {
  const navigate = useNavigate()
  const status = useAsyncData(() => getSettingsStatus(), [])
  const [step, setStep] = useState(0)

  function finish() {
    navigate('/', { replace: true })
  }

  const s = status.data

  return (
    <div className="mx-auto mt-16 max-w-xl px-6">
      <header className="mb-6 text-center">
        <h1 className="font-heading text-2xl font-bold">Welcome to ZenGrowth</h1>
        <p className="mt-1 text-sm text-muted">
          ZenGrowth turns a job posting into a tailored, honest application grounded in your real
          experience. Three quick steps and you're ready.
        </p>
      </header>

      <ol className="mb-6 flex items-center justify-center gap-2 text-xs">
        {STEPS.map((label, i) => (
          <li key={label} className="flex items-center gap-2">
            <span
              className={`flex h-6 w-6 items-center justify-center rounded-full border font-mono ${
                i === step
                  ? 'border-cyan bg-cyan/10 text-cyan'
                  : i < step
                    ? 'border-emerald/50 bg-emerald/10 text-emerald'
                    : 'border-border text-muted'
              }`}
            >
              {i < step ? '✓' : i + 1}
            </span>
            <span className={i === step ? 'text-text' : 'text-muted'}>{label}</span>
            {i < STEPS.length - 1 && <span className="text-border">—</span>}
          </li>
        ))}
      </ol>

      {step === 0 && (
        <ConnectClaudeStep
          configured={!!s?.anthropic_configured}
          onDone={() => {
            status.refetch()
            setStep(1)
          }}
          onSkip={() => setStep(1)}
        />
      )}
      {step === 1 && (
        <AddCvStep
          onDone={() => {
            status.refetch()
            setStep(2)
          }}
          onSkip={() => setStep(2)}
        />
      )}
      {step === 2 && <ConfirmStyleStep status={s} onFinish={finish} />}

      <p className="mt-6 text-center">
        <button onClick={finish} className="micro-label text-muted hover:text-text">
          skip setup, go to the dashboard →
        </button>
      </p>
    </div>
  )
}

function ConnectClaudeStep({
  configured,
  onDone,
  onSkip,
}: {
  configured: boolean
  onDone: () => void
  onSkip: () => void
}) {
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()

  async function save() {
    setBusy(true)
    setError(undefined)
    try {
      await saveApiKey('anthropic', key.trim())
      onDone()
    } catch (err) {
      setError(messageFrom(err, 'Could not save the key. Check it and try again.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel title="Connect Claude">
      {configured ? (
        <div className="flex flex-col gap-3">
          <AlertBanner tone="success">Your Claude key is connected.</AlertBanner>
          <button
            onClick={onDone}
            className="self-start rounded-lg border border-cyan px-3 py-2 text-sm text-cyan hover:bg-cyan/10"
          >
            Continue →
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted">
            ZenGrowth uses your own Claude API key, so your data and spend stay yours. We validate it
            once, store it encrypted on this machine, and never display it again.
          </p>
          <input
            type="password"
            autoFocus
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="sk-ant-…"
            className="rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
          />
          {error && <AlertBanner tone="error">{error}</AlertBanner>}
          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={save}
              disabled={busy || key.trim().length < 8}
              className="rounded-lg border border-cyan px-3 py-2 text-sm text-cyan disabled:opacity-50"
            >
              {busy ? 'Validating…' : 'Connect'}
            </button>
            <a
              href="https://console.anthropic.com/settings/keys"
              target="_blank"
              rel="noreferrer"
              className="text-xs text-cyan hover:underline"
            >
              Get a key →
            </a>
            <button onClick={onSkip} className="micro-label text-muted hover:text-text">
              skip for now
            </button>
          </div>
        </div>
      )}
    </Panel>
  )
}

function AddCvStep({ onDone, onSkip }: { onDone: () => void; onSkip: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [result, setResult] = useState<KnowledgeIngestResult>()

  async function upload(file: File) {
    setBusy(true)
    setError(undefined)
    try {
      const r = await uploadKnowledgeSource(file, 'cv')
      setResult(r)
    } catch (err) {
      setError(messageFrom(err, 'Could not read that file. Try a PDF, DOCX, TeX, or text file.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel title="Add your CV">
      <div className="flex flex-col gap-3">
        <p className="text-sm text-muted">
          Drop in your CV (PDF, DOCX, TeX, MD, or text). ZenGrowth reads it and pulls out the facts
          it can use — the well-supported ones are ready immediately.
        </p>
        <input
          type="file"
          accept=".md,.txt,.pdf,.docx,.tex"
          disabled={busy}
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) void upload(file)
          }}
          className="rounded-lg border border-border bg-black/30 px-3 py-2 text-sm"
        />
        {busy && <p className="text-sm text-muted">Reading your CV…</p>}
        {error && <AlertBanner tone="error">{error}</AlertBanner>}
        {result && (
          <AlertBanner tone="success">
            I read your CV and pulled out {result.claims} fact{result.claims === 1 ? '' : 's'}.{' '}
            {result.verified_claims} {result.verified_claims === 1 ? 'is' : 'are'} clearly supported
            and ready to use
            {result.claims - result.verified_claims > 0
              ? `; ${result.claims - result.verified_claims} are worth a glance later on Library.`
              : '.'}
          </AlertBanner>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={onDone}
            disabled={busy}
            className="rounded-lg border border-cyan px-3 py-2 text-sm text-cyan disabled:opacity-50"
          >
            {result ? 'Continue →' : 'Done'}
          </button>
          <button onClick={onSkip} className="micro-label text-muted hover:text-text">
            skip for now
          </button>
        </div>
      </div>
    </Panel>
  )
}

function ConfirmStyleStep({
  status,
  onFinish,
}: {
  status: SettingsStatus | undefined
  onFinish: () => void
}) {
  const hasTemplate = !!status?.has_cv_template
  return (
    <Panel title="Confirm your CV style">
      <div className="flex flex-col gap-3">
        {hasTemplate ? (
          <AlertBanner tone="success">
            Your uploaded CV is set as the active template — generated CVs will keep its style.
          </AlertBanner>
        ) : (
          <p className="text-sm text-muted">
            No CV template detected yet. Upload a <code>.tex</code> CV on Library later to lock in your
            own style; until then, ZenGrowth uses a clean default.
          </p>
        )}
        <p className="text-sm text-muted">You're ready. Paste your first job posting to begin.</p>
        <button
          onClick={onFinish}
          className="self-start rounded-lg border border-emerald px-4 py-2 text-sm text-emerald hover:bg-emerald/10"
        >
          Go to ZenGrowth →
        </button>
      </div>
    </Panel>
  )
}

function messageFrom(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}
