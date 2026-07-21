import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ClaimReviewCard } from './ClaimReviewCard'
import { OperatorGuide } from './OperatorGuide'
import { reviewContext } from '../lib/claimReview'
import type { EvidenceClaim } from '../lib/types'

beforeEach(() => {
  // OperatorGuide remembers dismissal in localStorage; start each test fresh.
  localStorage.clear()
})

function claim(p: Partial<EvidenceClaim>): EvidenceClaim {
  return {
    id: 'c1',
    source_document_id: 1,
    source_chunk_id: 1,
    claim_text: 'Led a team of 8 engineers.',
    category: 'leadership',
    confidence: 0.6,
    verification_state: 'draft',
    source_span: 'Managed a team of 8 across two squads.',
    tags: null,
    created_at: '',
    updated_at: '',
    ...p,
  }
}

describe('ClaimReviewCard', () => {
  it('pairs the fact with its source excerpt and shows confidence relative to the bar', () => {
    render(<ClaimReviewCard claim={claim({})} onVerify={vi.fn()} onReject={vi.fn()} />)
    expect(screen.getByText('Led a team of 8 engineers.')).toBeInTheDocument()
    expect(screen.getByText('Managed a team of 8 across two squads.')).toBeInTheDocument()
    expect(screen.getByText(/below auto-verify bar/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /approve fact/i })).toBeInTheDocument()
  })

  it('warns when a fact has no source excerpt', () => {
    render(<ClaimReviewCard claim={claim({ source_span: null })} onVerify={vi.fn()} onReject={vi.fn()} />)
    expect(screen.getByText(/cannot trace this fact to a document/i)).toBeInTheDocument()
  })

  it('explains why the fact is queued and what happens next', () => {
    render(<ClaimReviewCard claim={claim({})} onVerify={vi.fn()} onReject={vi.fn()} />)
    const ctx = reviewContext(claim({}))
    expect(screen.getByText(ctx.why)).toBeInTheDocument()
    expect(screen.getByText(ctx.next)).toBeInTheDocument()
  })
})

describe('OperatorGuide', () => {
  it('shows a one-line welcome pointing at the next step, and dismisses', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <OperatorGuide />
      </MemoryRouter>,
    )
    expect(screen.getByText(/New here\?/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Library' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Jobs' })).toBeInTheDocument()
    await user.click(screen.getByText('dismiss'))
    expect(screen.queryByText(/New here\?/i)).not.toBeInTheDocument()
  })
})
