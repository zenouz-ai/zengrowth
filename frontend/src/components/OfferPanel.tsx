import { useRef, useState } from 'react'
import { AlertBanner } from './AlertBanner'
import { ArtifactRow } from './ArtifactRow'
import {
  apiErrorMessage,
  createOffer,
  deleteOffer,
  draftOfferResponse,
  evaluateOffer,
  extractOffer,
  extractOfferFile,
  generateDeparturePack,
  generateOnboardingPack,
  updateOffer,
} from '../lib/api'
import { toIso } from '../lib/dates'
import {
  OFFER_STATUSES,
  type DeparturePackPayload,
  type GeneratedMaterial,
  type Job,
  type Offer,
  type OfferExtractResult,
  type OfferPayload,
  type OfferResponseType,
  type OfferStatus,
} from '../lib/types'

const STATUS_LABELS: Record<OfferStatus, string> = {
  received: 'Received',
  evaluating: 'Evaluating',
  negotiating: 'Negotiating',
  accepted: 'Accepted',
  declined: 'Declined',
  withdrawn: 'Withdrawn',
}

const RESPONSE_OPTIONS: { value: OfferResponseType; label: string; hint: string }[] = [
  {
    value: 'counter',
    label: 'Counter-offer',
    hint: 'A justified ask grounded in the market evaluation',
  },
  { value: 'accept', label: 'Acceptance', hint: 'Confirm the terms and ask for the contract' },
  {
    value: 'clarify',
    label: 'Clarification',
    hint: 'Get missing terms in writing before deciding',
  },
]

function formatMoney(amount: number | null, currency: string): string | null {
  if (amount == null) return null
  try {
    return new Intl.NumberFormat('en-GB', {
      style: 'currency',
      currency,
      maximumFractionDigits: 0,
    }).format(amount)
  } catch {
    return `${currency} ${amount.toLocaleString()}`
  }
}

function daysUntil(iso: string | null): number | null {
  if (!iso) return null
  const ms = new Date(iso).getTime() - Date.now()
  return Math.ceil(ms / 86_400_000)
}

export function OfferPanel({
  job,
  offers,
  materials,
  onChanged,
}: {
  job: Job
  offers: Offer[]
  materials: GeneratedMaterial[]
  onChanged: () => void
}) {
  const jobId = job.id
  const [error, setError] = useState<string>()
  const [adding, setAdding] = useState(false)
  const [working, setWorking] = useState<string>()
  const [extracted, setExtracted] = useState<OfferExtractResult | null>(null)
  const [planningDeparture, setPlanningDeparture] = useState(false)
  const hasAccepted = offers.some((o) => o.status === 'accepted')

  async function guard(label: string, fn: () => Promise<unknown>, fallback: string) {
    setError(undefined)
    setWorking(label)
    try {
      await fn()
      onChanged()
      return true
    } catch (err) {
      setError(apiErrorMessage(err, fallback))
      return false
    } finally {
      setWorking(undefined)
    }
  }

  if (offers.length === 0 && materials.length === 0 && !adding) {
    return (
      <div className="flex flex-col gap-3">
        {error && <AlertBanner tone="error">{error}</AlertBanner>}
        <p className="text-sm text-muted">
          When this process reaches an offer, record its terms here. ZenGrowth benchmarks the
          package against the market and your expectations, then drafts the acceptance,
          counter-offer, or clarification email — nothing is ever sent for you.
        </p>
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="self-start rounded-lg border border-cyan bg-cyan/10 px-4 py-2 text-sm font-medium text-cyan"
        >
          Record an offer
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {error && <AlertBanner tone="error">{error}</AlertBanner>}

      {offers.map((offer) => (
        <OfferCard
          key={offer.id}
          jobId={jobId}
          offer={offer}
          working={working}
          onGuard={guard}
        />
      ))}

      {materials.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="micro-label">Offer documents</p>
          {materials.map((material) => (
            <ArtifactRow key={material.id} jobId={jobId} material={material} />
          ))}
        </div>
      )}

      {hasAccepted && (
        <div className="rounded-lg border border-emerald/40 bg-emerald/5 px-3 py-3">
          <p className="mb-2 text-sm text-muted">
            Offer accepted — congratulations. Generate an <strong>onboarding pack</strong> (a
            30/60/90 plan carrying forward everything this process taught you), and plan your
            departure: resignation letter, manager conversation, handover, and the leaving
            checklist — captured while it all still matters.
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!!working}
              onClick={() =>
                guard(
                  'Researching and writing your onboarding pack — this can take a minute…',
                  () => generateOnboardingPack(jobId),
                  'Could not generate the onboarding pack — try again or check Setup for your Claude key.',
                )
              }
              className="rounded-lg border border-violet bg-violet/10 px-4 py-2 text-sm font-medium text-violet disabled:opacity-50"
            >
              Generate onboarding pack
            </button>
            <button
              type="button"
              disabled={!!working}
              onClick={() => setPlanningDeparture((v) => !v)}
              className="rounded-lg border border-violet px-4 py-2 text-sm text-violet disabled:opacity-50"
            >
              {planningDeparture ? 'Cancel departure plan' : 'Plan your departure'}
            </button>
          </div>
          {planningDeparture && (
            <DepartureForm
              disabled={!!working}
              onSubmit={async (payload) => {
                const ok = await guard(
                  'Writing your departure pack — this can take a minute…',
                  () => generateDeparturePack(jobId, payload),
                  'Could not generate the departure pack — try again or check Setup for your Claude key.',
                )
                if (ok) setPlanningDeparture(false)
              }}
            />
          )}
        </div>
      )}

      {working && (
        <p className="flex items-center gap-2 text-sm text-cyan">
          <span className="h-2 w-2 animate-pulse rounded-full bg-cyan" />
          {working}
        </p>
      )}

      {adding ? (
        <>
          <OfferExtractBox
            jobId={jobId}
            disabled={!!working}
            onExtracted={setExtracted}
          />
          <OfferForm
            key={extracted ? `extract-${extracted.offer_text?.length}-${extracted.base_salary}` : 'blank'}
            initial={extracted ? extractedToDraft(extracted) : undefined}
            onCancel={() => {
              setAdding(false)
              setExtracted(null)
            }}
            onSubmit={async (payload) => {
              const ok = await guard(
                'Saving the offer…',
                () => createOffer(jobId, payload),
                'Could not save the offer.',
              )
              if (ok) {
                setAdding(false)
                setExtracted(null)
              }
              return ok
            }}
          />
        </>
      ) : (
        offers.length > 0 && (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="micro-label self-start text-muted hover:text-text"
          >
            record a revised offer
          </button>
        )
      )}
    </div>
  )
}

/** Extraction result -> prefill values for the offer form. */
function extractedToDraft(extracted: OfferExtractResult): Partial<Offer> {
  return {
    base_salary: extracted.base_salary,
    currency: extracted.currency ?? undefined,
    bonus: extracted.bonus,
    equity: extracted.equity,
    pension: extracted.pension,
    holiday_days: extracted.holiday_days,
    benefits: extracted.benefits,
    other_terms: extracted.other_terms,
    start_date: extracted.start_date,
    received_at: extracted.received_at,
    deadline_at: extracted.deadline_at,
    offer_text: extracted.offer_text,
  }
}

function DepartureForm({
  disabled,
  onSubmit,
}: {
  disabled: boolean
  onSubmit: (payload: DeparturePackPayload) => Promise<void>
}) {
  const [currentCompany, setCurrentCompany] = useState('')
  const [currentRole, setCurrentRole] = useState('')
  const [managerName, setManagerName] = useState('')
  const [noticePeriod, setNoticePeriod] = useState('')
  const [lastDayTarget, setLastDayTarget] = useState('')
  const [responsibilities, setResponsibilities] = useState('')
  const [achievements, setAchievements] = useState('')
  const [notes, setNotes] = useState('')

  const inputClass =
    'w-full rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan'

  return (
    <div className="mt-3 flex flex-col gap-2 rounded-lg border border-border/70 bg-black/20 p-3">
      <p className="text-xs text-muted">
        A short brief about the role you're leaving. The pack works your notice against the new
        start date and includes the resignation letter, manager conversation script, handover
        plan, achievements to save for your Library, and the leaving checklist. Everything is a
        private document — nothing is sent, and anything unknown is flagged "check your
        contract".
      </p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-xs text-muted">
          Current company
          <input value={currentCompany} onChange={(e) => setCurrentCompany(e.target.value)} className={inputClass} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Current role
          <input value={currentRole} onChange={(e) => setCurrentRole(e.target.value)} className={inputClass} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Manager
          <input value={managerName} onChange={(e) => setManagerName(e.target.value)} className={inputClass} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Notice period
          <input
            value={noticePeriod}
            onChange={(e) => setNoticePeriod(e.target.value)}
            placeholder="e.g. 3 months"
            className={inputClass}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Preferred last day
          <input
            type="date"
            value={lastDayTarget}
            onChange={(e) => setLastDayTarget(e.target.value)}
            className={`${inputClass} [color-scheme:dark]`}
          />
        </label>
      </div>
      <label className="flex flex-col gap-1 text-xs text-muted">
        Key responsibilities to hand over
        <textarea
          value={responsibilities}
          onChange={(e) => setResponsibilities(e.target.value)}
          rows={2}
          placeholder="Teams, systems, in-flight projects, who depends on you…"
          className={inputClass}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted">
        Achievements worth recording (they become Library-ready bullets)
        <textarea
          value={achievements}
          onChange={(e) => setAchievements(e.target.value)}
          rows={2}
          placeholder="Delivered X saving £Y, built the Z team…"
          className={inputClass}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted">
        Anything else
        <input
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Expecting a counter-offer, sensitive dynamics, garden leave…"
          className={inputClass}
        />
      </label>
      <button
        type="button"
        disabled={disabled}
        onClick={() =>
          onSubmit({
            current_company: currentCompany.trim() || null,
            current_role: currentRole.trim() || null,
            manager_name: managerName.trim() || null,
            notice_period: noticePeriod.trim() || null,
            last_day_target: lastDayTarget || null,
            responsibilities: responsibilities.trim() || null,
            achievements: achievements.trim() || null,
            notes: notes.trim() || null,
          })
        }
        className="self-start rounded-lg border border-cyan px-3 py-2 text-sm text-cyan disabled:opacity-50"
      >
        Generate departure pack
      </button>
    </div>
  )
}

function OfferExtractBox({
  jobId,
  disabled,
  onExtracted,
}: {
  jobId: number
  disabled: boolean
  onExtracted: (result: OfferExtractResult) => void
}) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [notes, setNotes] = useState<string>()
  const fileRef = useRef<HTMLInputElement>(null)

  async function run(fn: () => Promise<OfferExtractResult>) {
    setBusy(true)
    setError(undefined)
    setNotes(undefined)
    try {
      const result = await fn()
      onExtracted(result)
      const missing = result.missing_fields.length
        ? ` Not found: ${result.missing_fields.join(', ').replace(/_/g, ' ')}.`
        : ''
      setNotes(
        `Terms extracted — review the prefilled form below before saving.${missing}` +
          (result.confidence_notes ? ` ${result.confidence_notes}` : ''),
      )
    } catch (err) {
      setError(apiErrorMessage(err, 'Could not extract the offer terms.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border/70 bg-black/20 p-3">
      <p className="text-xs text-muted">
        Got the offer as an email or a PDF letter? Paste or upload it and ZenGrowth prefills the
        form — you review every field before anything is saved. The document is kept with the
        offer and never enters your evidence bank.
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={4}
        placeholder="Paste the offer email or letter text here…"
        className="w-full rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
      />
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={busy || disabled || !text.trim()}
          onClick={() => run(() => extractOffer(jobId, text.trim()))}
          className="rounded-lg border border-violet bg-violet/10 px-3 py-2 text-sm font-medium text-violet disabled:opacity-50"
        >
          {busy ? 'Extracting…' : 'Extract from pasted text'}
        </button>
        <button
          type="button"
          disabled={busy || disabled}
          onClick={() => fileRef.current?.click()}
          className="rounded-lg border border-violet px-3 py-2 text-sm text-violet disabled:opacity-50"
        >
          Upload offer letter (PDF / DOCX)
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.docx,.txt,.md"
          className="hidden"
          aria-label="Offer letter file"
          onChange={(e) => {
            const file = e.target.files?.[0]
            e.target.value = ''
            if (file) run(() => extractOfferFile(jobId, file))
          }}
        />
      </div>
      {error && <p className="text-xs text-warning">{error}</p>}
      {notes && <p className="text-xs text-emerald">{notes}</p>}
    </div>
  )
}

function OfferCard({
  jobId,
  offer,
  working,
  onGuard,
}: {
  jobId: number
  offer: Offer
  working: string | undefined
  onGuard: (label: string, fn: () => Promise<unknown>, fallback: string) => Promise<boolean>
}) {
  const [editing, setEditing] = useState(false)
  const [drafting, setDrafting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [showLetter, setShowLetter] = useState(false)
  const busy = working !== undefined
  const terminal = offer.status === 'accepted' || offer.status === 'declined' || offer.status === 'withdrawn'
  const deadlineDays = terminal ? null : daysUntil(offer.deadline_at)

  const facts: [string, string | null][] = [
    ['Base salary', formatMoney(offer.base_salary, offer.currency)],
    ['Bonus', offer.bonus],
    ['Equity', offer.equity],
    ['Pension', offer.pension],
    ['Holiday', offer.holiday_days != null ? `${offer.holiday_days} days` : null],
    ['Benefits', offer.benefits],
    ['Other terms', offer.other_terms],
    ['Start date', offer.start_date],
    ['Received', offer.received_at?.slice(0, 10) ?? null],
    ['Respond by', offer.deadline_at?.slice(0, 10) ?? null],
  ]

  return (
    <div className="rounded-lg border border-border/70 bg-white/[0.02] p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-medium">
          {formatMoney(offer.base_salary, offer.currency) ?? 'Offer'}
          <span className="ml-2 text-xs uppercase tracking-wide text-muted">
            {STATUS_LABELS[offer.status]}
          </span>
          {deadlineDays != null && (
            <span
              className={`ml-2 text-xs ${deadlineDays <= 2 ? 'text-warning' : 'text-muted'}`}
            >
              {deadlineDays >= 0
                ? `${deadlineDays} day${deadlineDays === 1 ? '' : 's'} to respond`
                : 'response deadline passed'}
            </span>
          )}
        </p>
        <div className="flex items-center gap-2">
          <select
            value={offer.status}
            disabled={busy}
            onChange={(e) =>
              onGuard(
                'Updating the offer…',
                () => updateOffer(jobId, offer.id, { status: e.target.value as OfferStatus }),
                'Could not update the offer.',
              )
            }
            className="rounded-lg border border-border bg-black/30 px-2.5 py-1.5 text-xs"
            aria-label="Offer status"
          >
            {OFFER_STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABELS[s]}
              </option>
            ))}
          </select>
          {confirmDelete ? (
            <span className="flex items-center gap-1 text-xs">
              <button
                type="button"
                onClick={() =>
                  onGuard(
                    'Deleting the offer…',
                    () => deleteOffer(jobId, offer.id),
                    'Could not delete the offer.',
                  )
                }
                className="rounded border border-warning px-3 py-2 text-warning"
              >
                Delete
              </button>
              <button
                type="button"
                onClick={() => setConfirmDelete(false)}
                className="rounded border border-border px-3 py-2 text-muted"
              >
                Keep
              </button>
            </span>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmDelete(true)}
              className="text-xs text-muted hover:text-warning"
              aria-label="Delete offer"
            >
              remove
            </button>
          )}
        </div>
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
        {facts
          .filter((entry): entry is [string, string] => entry[1] != null)
          .map(([label, value]) => (
            <div key={label} className="rounded-lg border border-border/70 bg-black/20 p-2">
              <dt className="micro-label mb-0.5">{label}</dt>
              <dd className="break-words text-sm text-muted">{value}</dd>
            </div>
          ))}
      </dl>

      {offer.notes && <p className="mt-2 text-sm text-muted">{offer.notes}</p>}

      <div className="mt-3 flex flex-wrap gap-2 text-xs">
        <button
          type="button"
          disabled={busy}
          onClick={() =>
            onGuard(
              'Researching market benchmarks and evaluating the offer — this can take a minute…',
              () => evaluateOffer(jobId, offer.id),
              'Could not evaluate the offer — try again or check Setup for your Claude key.',
            )
          }
          title="Benchmark every component against market data and your expectations"
          className="rounded-lg border border-violet bg-violet/10 px-3 py-2 font-medium text-violet disabled:opacity-50"
        >
          Evaluate against the market
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => setDrafting((v) => !v)}
          className="rounded-lg border border-violet px-3 py-2 text-violet disabled:opacity-50"
        >
          {drafting ? 'Cancel response draft' : 'Draft a response'}
        </button>
        <button
          type="button"
          onClick={() => setEditing((v) => !v)}
          className="rounded-lg border border-border px-3 py-2 text-muted hover:text-text"
        >
          {editing ? 'Cancel edit' : 'Edit terms'}
        </button>
        {offer.offer_text && (
          <button
            type="button"
            onClick={() => setShowLetter((v) => !v)}
            className="rounded-lg border border-border px-3 py-2 text-muted hover:text-text"
          >
            {showLetter ? 'Hide offer letter' : 'View offer letter'}
          </button>
        )}
      </div>

      {drafting && (
        <ResponseDraftForm
          disabled={busy}
          onSubmit={async (responseType, instructions) => {
            const ok = await onGuard(
              'Writing the response draft…',
              () =>
                draftOfferResponse(jobId, offer.id, {
                  response_type: responseType,
                  instructions: instructions || undefined,
                }),
              'Could not draft the response.',
            )
            if (ok) setDrafting(false)
          }}
        />
      )}

      {showLetter && offer.offer_text && (
        <pre className="mt-3 max-h-64 overflow-y-auto whitespace-pre-wrap rounded-lg border border-border/70 bg-black/20 p-3 text-xs text-muted">
          {offer.offer_text}
        </pre>
      )}

      {editing && (
        <OfferForm
          initial={offer}
          onCancel={() => setEditing(false)}
          onSubmit={async (payload) => {
            const ok = await onGuard(
              'Saving the offer…',
              () => updateOffer(jobId, offer.id, payload),
              'Could not save the offer.',
            )
            if (ok) setEditing(false)
            return ok
          }}
        />
      )}
    </div>
  )
}

function ResponseDraftForm({
  disabled,
  onSubmit,
}: {
  disabled: boolean
  onSubmit: (responseType: OfferResponseType, instructions: string) => Promise<void>
}) {
  const [responseType, setResponseType] = useState<OfferResponseType>('counter')
  const [instructions, setInstructions] = useState('')
  const hint = RESPONSE_OPTIONS.find((o) => o.value === responseType)?.hint

  return (
    <div className="mt-3 flex flex-col gap-2 rounded-lg border border-border/70 bg-black/20 p-3">
      <p className="text-xs text-muted">
        Drafts are internal documents — <strong>nothing is sent by ZenGrowth</strong>. Counter
        drafts ground their asks in the latest offer evaluation, so evaluate first for the
        strongest case.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={responseType}
          onChange={(e) => setResponseType(e.target.value as OfferResponseType)}
          className="rounded-lg border border-border bg-black/30 px-3 py-2 text-sm"
          aria-label="Response type"
        >
          {RESPONSE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <span className="text-xs text-muted">{hint}</span>
      </div>
      <textarea
        value={instructions}
        onChange={(e) => setInstructions(e.target.value)}
        rows={2}
        placeholder="Optional guidance — e.g. ask for £150k base and one extra week of holiday…"
        className="w-full rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan"
      />
      <button
        type="button"
        disabled={disabled}
        onClick={() => onSubmit(responseType, instructions.trim())}
        className="self-start rounded-lg border border-cyan px-3 py-2 text-sm text-cyan disabled:opacity-50"
      >
        Generate draft
      </button>
    </div>
  )
}

function OfferForm({
  initial,
  onCancel,
  onSubmit,
}: {
  initial?: Partial<Offer>
  onCancel: () => void
  onSubmit: (payload: OfferPayload) => Promise<boolean>
}) {
  const [baseSalary, setBaseSalary] = useState(initial?.base_salary?.toString() ?? '')
  const [currency, setCurrency] = useState(initial?.currency ?? 'GBP')
  const [bonus, setBonus] = useState(initial?.bonus ?? '')
  const [equity, setEquity] = useState(initial?.equity ?? '')
  const [pension, setPension] = useState(initial?.pension ?? '')
  const [holidayDays, setHolidayDays] = useState(initial?.holiday_days?.toString() ?? '')
  const [benefits, setBenefits] = useState(initial?.benefits ?? '')
  const [otherTerms, setOtherTerms] = useState(initial?.other_terms ?? '')
  const [startDate, setStartDate] = useState(initial?.start_date ?? '')
  const [receivedAt, setReceivedAt] = useState(initial?.received_at?.slice(0, 10) ?? '')
  const [deadlineAt, setDeadlineAt] = useState(initial?.deadline_at?.slice(0, 10) ?? '')
  const [offerText, setOfferText] = useState(initial?.offer_text ?? '')
  const [notes, setNotes] = useState(initial?.notes ?? '')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState<string>()

  const inputClass =
    'w-full rounded-lg border border-border bg-black/30 px-3 py-2 text-sm outline-none focus:border-cyan'

  async function submit() {
    const salary = baseSalary.trim() ? Number(baseSalary) : null
    if (salary != null && (!Number.isFinite(salary) || salary < 0)) {
      setFormError('Base salary must be a number.')
      return
    }
    const holidays = holidayDays.trim() ? Number(holidayDays) : null
    if (holidays != null && (!Number.isInteger(holidays) || holidays < 0)) {
      setFormError('Holiday days must be a whole number.')
      return
    }
    setBusy(true)
    setFormError(undefined)
    try {
      await onSubmit({
        base_salary: salary,
        currency: currency.trim() || 'GBP',
        bonus: bonus.trim() || null,
        equity: equity.trim() || null,
        pension: pension.trim() || null,
        holiday_days: holidays,
        benefits: benefits.trim() || null,
        other_terms: otherTerms.trim() || null,
        start_date: startDate || null,
        received_at: toIso(receivedAt),
        deadline_at: toIso(deadlineAt),
        offer_text: offerText.trim() || null,
        notes: notes.trim() || null,
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-3 flex flex-col gap-3 rounded-lg border border-border/70 bg-black/20 p-3">
      <p className="text-xs text-muted">
        Record what the offer actually says — leave anything not offered blank, and the
        evaluation will flag it as a term to get in writing. Dates can be in the past.
      </p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-xs text-muted">
          Base salary
          <input
            value={baseSalary}
            onChange={(e) => setBaseSalary(e.target.value)}
            inputMode="numeric"
            placeholder="140000"
            className={inputClass}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Currency
          <input value={currency} onChange={(e) => setCurrency(e.target.value)} className={inputClass} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Bonus
          <input
            value={bonus}
            onChange={(e) => setBonus(e.target.value)}
            placeholder="15% target, paid annually"
            className={inputClass}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Equity
          <input
            value={equity}
            onChange={(e) => setEquity(e.target.value)}
            placeholder="RSUs, options, LTIP…"
            className={inputClass}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Pension
          <input
            value={pension}
            onChange={(e) => setPension(e.target.value)}
            placeholder="6% employer match"
            className={inputClass}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Holiday days
          <input
            value={holidayDays}
            onChange={(e) => setHolidayDays(e.target.value)}
            inputMode="numeric"
            placeholder="28"
            className={inputClass}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Start date
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className={`${inputClass} [color-scheme:dark]`}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Received on
          <input
            type="date"
            value={receivedAt}
            onChange={(e) => setReceivedAt(e.target.value)}
            className={`${inputClass} [color-scheme:dark]`}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Respond by
          <input
            type="date"
            value={deadlineAt}
            onChange={(e) => setDeadlineAt(e.target.value)}
            className={`${inputClass} [color-scheme:dark]`}
          />
        </label>
      </div>
      <label className="flex flex-col gap-1 text-xs text-muted">
        Benefits
        <textarea
          value={benefits}
          onChange={(e) => setBenefits(e.target.value)}
          rows={2}
          placeholder="Private healthcare, life assurance, wellbeing budget…"
          className={inputClass}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted">
        Other terms
        <input
          value={otherTerms}
          onChange={(e) => setOtherTerms(e.target.value)}
          placeholder="Notice period, probation, hybrid policy…"
          className={inputClass}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted">
        Offer letter / email (optional — feeds the evaluation verbatim)
        <textarea
          value={offerText}
          onChange={(e) => setOfferText(e.target.value)}
          rows={5}
          placeholder="Paste the offer letter or email here…"
          className={inputClass}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted">
        Notes
        <input
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Anything said verbally, your gut read…"
          className={inputClass}
        />
      </label>
      {formError && <p className="text-xs text-warning">{formError}</p>}
      <div className="flex gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={submit}
          className="rounded-lg border border-cyan bg-cyan/10 px-4 py-2 text-sm font-medium text-cyan disabled:opacity-50"
        >
          {busy ? 'Saving…' : initial?.id != null ? 'Save changes' : 'Save offer'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg border border-border px-4 py-2 text-sm text-muted hover:text-text"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}
