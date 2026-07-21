import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { OfferPanel } from './OfferPanel'
import {
  createOffer,
  draftOfferResponse,
  evaluateOffer,
  extractOffer,
  generateDeparturePack,
  generateOnboardingPack,
} from '../lib/api'
import type { GeneratedMaterial, Job, Offer } from '../lib/types'

vi.mock('../lib/api', () => ({
  apiErrorMessage: (_e: unknown, fallback: string) => fallback,
  createOffer: vi.fn(),
  deleteOffer: vi.fn(),
  downloadMaterial: vi.fn(),
  draftOfferResponse: vi.fn(),
  evaluateOffer: vi.fn(),
  extractOffer: vi.fn(),
  extractOfferFile: vi.fn(),
  generateDeparturePack: vi.fn(),
  generateOnboardingPack: vi.fn(),
  getMaterial: vi.fn(async () => ({ fallback_content: '# Evaluation' })),
  updateOffer: vi.fn(),
}))

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: 7,
    company: 'Northwind',
    title: 'Director of AI',
    location: 'London',
    hybrid_policy: null,
    compensation: null,
    seniority: null,
    application_url: null,
    posting_date: null,
    description: null,
    job_summary: null,
    summary_updated_at: null,
    source: 'manual',
    lifecycle_state: 'offer',
    fit_score: null,
    expected_value: null,
    score_rationale: null,
    applied_at: '2026-05-11T09:00:00Z',
    first_response_at: null,
    outcome_stage: 'offer',
    outcome_result: 'offer',
    rejection_stage: null,
    outcome_notes: null,
    outcome_updated_at: null,
    created_at: '2026-07-02T00:00:00Z',
    updated_at: '2026-07-02T00:00:00Z',
    ...overrides,
  }
}

function offer(overrides: Partial<Offer> = {}): Offer {
  return {
    id: 3,
    job_id: 7,
    status: 'received',
    base_salary: 140000,
    currency: 'GBP',
    bonus: '15% target',
    equity: null,
    pension: '6% employer match',
    holiday_days: 28,
    benefits: 'Private healthcare',
    other_terms: null,
    start_date: null,
    received_at: '2026-07-10T09:00:00Z',
    deadline_at: null,
    offer_text: null,
    notes: null,
    created_at: '2026-07-10T09:00:00Z',
    updated_at: '2026-07-10T09:00:00Z',
    ...overrides,
  }
}

function material(overrides: Partial<GeneratedMaterial> = {}): GeneratedMaterial {
  return {
    id: 21,
    job_id: 7,
    interview_id: null,
    material_type: 'offer_evaluation',
    audience: 'internal',
    effective_date: null,
    title: 'Offer evaluation — Northwind',
    question: null,
    word_limit: null,
    tex_path: null,
    pdf_path: null,
    markdown_path: '/x/eval.md',
    evidence_ids: [],
    version: 1,
    is_final: false,
    supersedes_id: null,
    page_count: null,
    page_fill: null,
    page_fit: 'unknown',
    status: 'created_markdown',
    created_at: '2026-07-11T00:00:00Z',
    ...overrides,
  }
}

function renderPanel(props: {
  offers?: Offer[]
  materials?: GeneratedMaterial[]
  onChanged?: () => void
}) {
  return render(
    <OfferPanel
      job={job()}
      offers={props.offers ?? []}
      materials={props.materials ?? []}
      onChanged={props.onChanged ?? (() => {})}
    />,
  )
}

describe('OfferPanel', () => {
  it('shows the record-offer call to action when no offer exists', () => {
    renderPanel({})
    screen.getByText(/record its terms here/)
    screen.getByText('Record an offer')
  })

  it('opens the offer form with backdatable dates and letter paste', () => {
    renderPanel({})
    fireEvent.click(screen.getByText('Record an offer'))
    screen.getByText(/Dates can be in the past/)
    screen.getByPlaceholderText('140000')
    screen.getByText('Received on')
    screen.getByText('Respond by')
    screen.getByPlaceholderText(/Paste the offer letter/)
    screen.getByText('Save offer')
  })

  it('submits a recorded offer', async () => {
    vi.mocked(createOffer).mockResolvedValueOnce(offer())
    renderPanel({})
    fireEvent.click(screen.getByText('Record an offer'))
    fireEvent.change(screen.getByPlaceholderText('140000'), { target: { value: '140000' } })
    fireEvent.change(screen.getByPlaceholderText('6% employer match'), {
      target: { value: '6% employer match' },
    })
    fireEvent.click(screen.getByText('Save offer'))
    await waitFor(() => {
      expect(createOffer).toHaveBeenCalledWith(
        7,
        expect.objectContaining({ base_salary: 140000, pension: '6% employer match' }),
      )
    })
  })

  it('renders offer terms with formatted salary and status', () => {
    renderPanel({ offers: [offer()] })
    expect(screen.getAllByText('£140,000').length).toBeGreaterThan(0)
    screen.getByText('15% target')
    screen.getByText('28 days')
    screen.getByText('Private healthcare')
    screen.getByText('2026-07-10')
  })

  it('shows a response-deadline countdown for live offers', () => {
    const soon = new Date(Date.now() + 3 * 86_400_000).toISOString()
    renderPanel({ offers: [offer({ deadline_at: soon })] })
    screen.getByText(/days? to respond/)
  })

  it('evaluates the offer against the market', async () => {
    vi.mocked(evaluateOffer).mockResolvedValueOnce(material())
    const onChanged = vi.fn()
    renderPanel({ offers: [offer()], onChanged })
    fireEvent.click(screen.getByText('Evaluate against the market'))
    await waitFor(() => {
      expect(evaluateOffer).toHaveBeenCalledWith(7, 3)
      expect(onChanged).toHaveBeenCalled()
    })
  })

  it('drafts a counter-offer response with the never-sent banner', async () => {
    vi.mocked(draftOfferResponse).mockResolvedValueOnce(
      material({ material_type: 'offer_response' }),
    )
    renderPanel({ offers: [offer()] })
    fireEvent.click(screen.getByText('Draft a response'))
    expect(screen.getByText(/nothing is sent by ZenGrowth/)).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText(/Optional guidance/), {
      target: { value: 'Ask for £150k base.' },
    })
    fireEvent.click(screen.getByText('Generate draft'))
    await waitFor(() => {
      expect(draftOfferResponse).toHaveBeenCalledWith(7, 3, {
        response_type: 'counter',
        instructions: 'Ask for £150k base.',
      })
    })
  })

  it('lists offer documents with labels', () => {
    renderPanel({
      offers: [offer()],
      materials: [
        material(),
        material({ id: 22, material_type: 'offer_response', title: 'Counter-offer draft — Northwind' }),
      ],
    })
    screen.getByText('Offer documents')
    screen.getByText('Offer evaluation — Northwind')
    screen.getByText('Counter-offer draft — Northwind')
  })

  it('offers a revised-offer action once an offer exists', () => {
    renderPanel({ offers: [offer()] })
    screen.getByText('record a revised offer')
  })

  it('shows paste/upload extraction in the add flow and prefills the form', async () => {
    vi.mocked(extractOffer).mockResolvedValueOnce({
      base_salary: 152000,
      currency: 'GBP',
      bonus: null,
      equity: null,
      pension: '5% match',
      holiday_days: 30,
      benefits: null,
      other_terms: null,
      start_date: null,
      received_at: null,
      deadline_at: null,
      offer_text: 'Dear candidate…',
      missing_fields: ['equity'],
      confidence_notes: 'No equity mentioned.',
    })
    renderPanel({})
    fireEvent.click(screen.getByText('Record an offer'))
    screen.getByText('Upload offer letter (PDF / DOCX)')
    fireEvent.change(screen.getByPlaceholderText(/Paste the offer email/), {
      target: { value: 'Dear candidate…' },
    })
    fireEvent.click(screen.getByText('Extract from pasted text'))
    await waitFor(() => {
      expect(extractOffer).toHaveBeenCalledWith(7, 'Dear candidate…')
      expect(screen.getByPlaceholderText('140000')).toHaveValue('152000')
      expect(screen.getByText(/Not found: equity/)).toBeInTheDocument()
    })
  })

  it('offers the onboarding pack once the offer is accepted', async () => {
    vi.mocked(generateOnboardingPack).mockResolvedValueOnce(
      material({ material_type: 'onboarding_pack', title: 'Onboarding pack — Northwind' }),
    )
    const onChanged = vi.fn()
    renderPanel({ offers: [offer({ status: 'accepted' })], onChanged })
    screen.getByText(/Offer accepted — congratulations/)
    fireEvent.click(screen.getByText('Generate onboarding pack'))
    await waitFor(() => {
      expect(generateOnboardingPack).toHaveBeenCalledWith(7)
      expect(onChanged).toHaveBeenCalled()
    })
  })

  it('hides the onboarding action while the offer is undecided', () => {
    renderPanel({ offers: [offer({ status: 'negotiating' })] })
    expect(screen.queryByText('Generate onboarding pack')).toBeNull()
    expect(screen.queryByText('Plan your departure')).toBeNull()
  })

  it('opens the departure form on acceptance and submits the brief', async () => {
    vi.mocked(generateDeparturePack).mockResolvedValueOnce(
      material({ material_type: 'departure_pack', title: 'Departure pack — leaving Contoso' }),
    )
    renderPanel({ offers: [offer({ status: 'accepted' })] })
    fireEvent.click(screen.getByText('Plan your departure'))
    screen.getByText(/check your\s+contract/)
    fireEvent.change(screen.getByLabelText('Current company'), { target: { value: 'Contoso' } })
    fireEvent.change(screen.getByPlaceholderText('e.g. 3 months'), {
      target: { value: '3 months' },
    })
    fireEvent.change(screen.getByPlaceholderText(/Delivered X saving/), {
      target: { value: 'Delivered the ML platform saving £2m/yr.' },
    })
    fireEvent.click(screen.getByText('Generate departure pack'))
    await waitFor(() => {
      expect(generateDeparturePack).toHaveBeenCalledWith(
        7,
        expect.objectContaining({
          current_company: 'Contoso',
          notice_period: '3 months',
          achievements: 'Delivered the ML platform saving £2m/yr.',
        }),
      )
    })
  })
})
