import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { InterviewTimeline } from './InterviewTimeline'
import { createInterview } from '../lib/api'
import type { GeneratedMaterial, Interview, Job } from '../lib/types'

vi.mock('../lib/api', () => ({
  apiErrorMessage: (_e: unknown, fallback: string) => fallback,
  createInterview: vi.fn(),
  deleteInterview: vi.fn(),
  downloadMaterial: vi.fn(),
  generateDebrief: vi.fn(),
  generateEmailDraft: vi.fn(),
  generatePack: vi.fn(),
  generateSimPrompt: vi.fn(),
  getInterview: vi.fn(async () => ({ transcript: null })),
  getMaterial: vi.fn(async () => ({ fallback_content: '# Pack' })),
  importMaterial: vi.fn(),
  listKnowledgeClaims: vi.fn(async () => []),
  promoteLearning: vi.fn(),
  setInterviewTranscript: vi.fn(),
  updateInterview: vi.fn(),
}))

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: 7,
    company: 'Intact',
    title: 'Director of AI',
    location: null,
    hybrid_policy: null,
    compensation: null,
    seniority: null,
    application_url: null,
    posting_date: null,
    description: null,
    job_summary: null,
    summary_updated_at: null,
    source: 'manual',
    lifecycle_state: 'interviewing',
    fit_score: null,
    expected_value: null,
    score_rationale: null,
    applied_at: '2026-05-11T09:00:00Z',
    first_response_at: null,
    outcome_stage: 'interview',
    outcome_result: null,
    rejection_stage: null,
    outcome_notes: null,
    outcome_updated_at: null,
    created_at: '2026-07-02T00:00:00Z',
    updated_at: '2026-07-02T00:00:00Z',
    ...overrides,
  }
}

function interview(overrides: Partial<Interview> = {}): Interview {
  return {
    id: 1,
    job_id: 7,
    round_type: 'recruiter_screen',
    title: null,
    format: 'phone',
    status: 'completed',
    scheduled_at: '2026-05-16T10:00:00Z',
    occurred_at: '2026-05-16T10:00:00Z',
    participants: [{ name: 'Sam Recruiter', role: 'Talent partner' }],
    notes: null,
    has_transcript: false,
    can_debrief: false,
    transcript_updated_at: null,
    created_at: '2026-07-02T00:00:00Z',
    updated_at: '2026-07-02T00:00:00Z',
    ...overrides,
  }
}

function artifact(overrides: Partial<GeneratedMaterial> = {}): GeneratedMaterial {
  return {
    id: 11,
    job_id: 7,
    interview_id: null,
    material_type: 'company_briefing',
    audience: 'internal',
    effective_date: '2026-05-13T09:00:00Z',
    title: 'Intact research pack',
    question: null,
    word_limit: null,
    tex_path: null,
    pdf_path: null,
    markdown_path: '/x/pack.md',
    evidence_ids: [],
    version: 1,
    is_final: false,
    supersedes_id: null,
    page_count: null,
    page_fill: null,
    page_fit: 'unknown',
    status: 'imported',
    created_at: '2026-07-02T00:00:00Z',
    ...overrides,
  }
}

function renderTimeline(props: {
  interviews?: Interview[]
  materials?: GeneratedMaterial[]
  jobOverrides?: Partial<Job>
}) {
  return render(
    <InterviewTimeline
      job={job(props.jobOverrides)}
      interviews={props.interviews ?? []}
      materials={props.materials ?? []}
      employerMaterialCount={2}
      onChanged={() => {}}
    />,
  )
}

describe('InterviewTimeline', () => {
  it('shows an empty state when there is nothing yet', () => {
    renderTimeline({ jobOverrides: { applied_at: null, outcome_stage: null } })
    screen.getByText(/No interviews recorded yet/)
  })

  it('renders rounds with dates, participants, and attached artifacts', () => {
    renderTimeline({
      interviews: [
        interview(),
        interview({
          id: 2,
          round_type: 'final_round',
          status: 'scheduled',
          occurred_at: null,
          scheduled_at: '2026-07-09T09:00:00Z',
          participants: null,
        }),
      ],
      materials: [artifact({ interview_id: 1, material_type: 'debrief', title: 'Screen debrief' })],
    })
    expect(screen.getAllByText('Recruiter screen').length).toBeGreaterThan(0)
    screen.getByText('2026-05-16')
    screen.getByText(/Sam Recruiter \(Talent partner\)/)
    expect(screen.getAllByText('Final round').length).toBeGreaterThan(0)
    screen.getByText(/2026-07-09/)
    screen.getByText('Screen debrief')
  })

  it('renders the journey rail with stage nodes and stats', () => {
    renderTimeline({
      interviews: [
        interview(),
        interview({
          id: 2,
          round_type: 'final_round',
          status: 'scheduled',
          occurred_at: null,
          scheduled_at: '2026-07-09T09:00:00Z',
          participants: null,
        }),
      ],
      materials: [artifact({ interview_id: 1, material_type: 'debrief', title: 'Screen debrief' })],
    })
    // Rail landmarks: Applied node, Decision terminal, stats strip.
    screen.getByRole('tablist', { name: 'Application journey' })
    screen.getByText('Applied')
    screen.getByText('Decision')
    screen.getByText('Days in process')
    screen.getByText('Rounds completed')
    // The screen round node (after the non-clickable Applied node) selects its card.
    const railNode = screen.getAllByRole('tab')[1]
    fireEvent.click(railNode)
    expect(railNode).toHaveAttribute('aria-selected', 'true')
  })

  it('lists job-level packs separately', () => {
    renderTimeline({ materials: [artifact()] })
    screen.getByText('Job-level packs')
    screen.getByText('Intact research pack')
  })

  it('opens the add-round form with a backdatable date field', () => {
    renderTimeline({})
    fireEvent.click(screen.getByText('Add interview round'))
    expect(screen.getByText(/past dates are fine/)).toBeInTheDocument()
    screen.getByText('Save round')
    screen.getByText(/Interview script \/ transcript/)
    // Formats read naturally whatever the medium (Teams/Zoom, in person, phone).
    screen.getByText('Video (Teams / Zoom / Meet)')
    screen.getByText('In person')
    screen.getByText('Phone call')
  })

  it('submits transcript when saving a round', async () => {
    vi.mocked(createInterview).mockResolvedValueOnce(
      interview({ id: 99, has_transcript: true, can_debrief: true }),
    )
    renderTimeline({})
    fireEvent.click(screen.getByText('Add interview round'))
    fireEvent.change(screen.getByPlaceholderText(/interview script/i), {
      target: { value: 'Interviewer: walk me through your AI CoE.' },
    })
    fireEvent.click(screen.getByText('Save round'))
    await waitFor(() => {
      expect(createInterview).toHaveBeenCalledWith(
        7,
        expect.objectContaining({
          transcript: 'Interviewer: walk me through your AI CoE.',
        }),
      )
    })
  })

  it('supports any round order and shows a friendly format label', () => {
    // Technical first, no screening round — flows are not a fixed sequence.
    renderTimeline({
      interviews: [
        interview({
          id: 3,
          round_type: 'technical',
          format: 'onsite',
          occurred_at: '2026-05-14T10:00:00Z',
          participants: null,
        }),
        interview({
          id: 4,
          round_type: 'leadership_panel',
          format: 'video',
          status: 'scheduled',
          occurred_at: null,
          scheduled_at: '2026-05-20T10:00:00Z',
          participants: null,
        }),
      ],
    })
    expect(screen.getAllByText(/in person/).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Leadership').length).toBeGreaterThan(0)
  })

  it('opens the import form for filing existing packs', () => {
    renderTimeline({})
    fireEvent.click(screen.getByText('Import a pack or note'))
    expect(screen.getByText(/File an existing document/)).toBeInTheDocument()
    screen.getByText('Import document')
  })

  it('disables debrief generation until transcript or notes exist', () => {
    renderTimeline({ interviews: [interview({ has_transcript: false, can_debrief: false })] })
    expect(screen.getByText('Generate debrief')).toBeDisabled()
  })

  it('enables debrief generation once a transcript exists', () => {
    renderTimeline({
      interviews: [interview({ has_transcript: true, can_debrief: true })],
    })
    expect(screen.getByText('Generate debrief')).toBeEnabled()
  })

  it('enables debrief when the round has notes but no transcript', () => {
    renderTimeline({
      interviews: [
        interview({
          has_transcript: false,
          can_debrief: true,
          notes: 'Strong rapport; prepare governance ROI examples.',
        }),
      ],
    })
    expect(screen.getByText('Generate debrief')).toBeEnabled()
  })

  it('opens the save-a-learning form routed to Approve facts', () => {
    renderTimeline({ interviews: [interview()] })
    fireEvent.click(screen.getByText('Save a learning'))
    expect(screen.getByText(/Approve facts/)).toBeInTheDocument()
    screen.getByText('Queue for review')
  })

  it('opens the email draft form', () => {
    renderTimeline({})
    fireEvent.click(screen.getByText('Draft an email'))
    expect(screen.getByText(/nothing is sent by ZenGrowth/)).toBeInTheDocument()
    screen.getByText('Draft email')
  })

  it('shows enhance button when an imported pack exists for the round', () => {
    renderTimeline({
      interviews: [interview({ round_type: 'technical' })],
      materials: [
        artifact({
          interview_id: 1,
          material_type: 'tech_prep_pack',
          title: 'Imported tech pack',
          status: 'imported',
        }),
      ],
    })
    screen.getByText('Enhance with ZenGrowth')
    screen.getByText('Prep for this round')
  })

  it('shows foundation enhance when job-level import exists', () => {
    renderTimeline({
      materials: [artifact({ material_type: 'company_briefing', status: 'imported' })],
    })
    screen.getByText('Regenerate foundation briefing')
    screen.getByText('Enhance foundation with ZenGrowth')
  })
})
