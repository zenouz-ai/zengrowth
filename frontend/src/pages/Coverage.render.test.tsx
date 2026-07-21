import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { Coverage as CoverageData, EvidenceClaim } from '../lib/types'
import { Coverage } from './Coverage'

const coverage: CoverageData = {
  facets: [
    {
      facet: 'industry',
      vocabulary_size: 20,
      values: [
        {
          value: 'insurance',
          verified_claims: 2,
          draft_claims: 0,
          claim_ids: ['c1', 'c2'],
          demand_jobs: 1,
          job_ids: [7],
          gap: false,
          monthly: [{ month: '2026-06', claims: 2 }],
        },
        {
          value: 'healthcare',
          verified_claims: 0,
          draft_claims: 1,
          claim_ids: [],
          demand_jobs: 2,
          job_ids: [8, 9],
          gap: true,
          monthly: [],
        },
      ],
    },
    ...['role_family', 'project_type', 'capability', 'location', 'seniority'].map((facet) => ({
      facet,
      vocabulary_size: 10,
      values: [],
    })),
  ],
  jobs: [
    { id: 7, company: 'Acme', title: 'Head of Insurance AI' },
    { id: 8, company: 'Medico', title: 'Director of Healthcare AI' },
    { id: 9, company: 'Clinico', title: 'Head of Clinical ML' },
  ],
  totals: {
    claims: 3,
    faceted_claims: 3,
    unfaceted_claims: 0,
    scored_jobs: 3,
    faceted_jobs: 3,
    unfaceted_jobs: 0,
  },
}

const claims: EvidenceClaim[] = [
  {
    id: 'c1',
    source_document_id: 1,
    source_chunk_id: null,
    claim_text: 'Led insurance pricing models.',
    category: 'technical',
    confidence: 0.9,
    verification_state: 'verified',
    source_span: null,
    tags: null,
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
  },
]

vi.mock('../lib/api', () => ({
  getKnowledgeCoverage: vi.fn(() => Promise.resolve(coverage)),
  listKnowledgeClaims: vi.fn(() => Promise.resolve(claims)),
  backfillKnowledgeFacets: vi.fn(),
}))

describe('Coverage', () => {
  it('renders the heatmap with demand counts and flags the gap', async () => {
    render(
      <MemoryRouter>
        <Coverage />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('insurance')).toBeInTheDocument())
    expect(screen.getByText('healthcare')).toBeInTheDocument()
    expect(screen.getByText('gap — no verified fact')).toBeInTheDocument()
    // Totals strip reflects faceting progress (facts and JDs both fully faceted).
    expect(screen.getAllByText('3/3')).toHaveLength(2)
  })

  it('drills into a value showing its claims and demanding JDs', async () => {
    render(
      <MemoryRouter>
        <Coverage />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('insurance')).toBeInTheDocument())
    screen.getByText('insurance').click()
    await waitFor(() =>
      expect(screen.getByText('Led insurance pricing models.')).toBeInTheDocument(),
    )
    expect(screen.getByText('Head of Insurance AI — Acme')).toBeInTheDocument()
  })

  it('switches facets and shows the empty state for unfaceted ones', async () => {
    render(
      <MemoryRouter>
        <Coverage />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('insurance')).toBeInTheDocument())
    screen.getByText('Role family').click()
    await waitFor(() =>
      expect(screen.getByText(/No role family facets yet/)).toBeInTheDocument(),
    )
  })
})
