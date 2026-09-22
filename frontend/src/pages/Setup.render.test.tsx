import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { Setup } from './Setup'

// Status resolves to "no key yet" so the wizard opens on Connect Claude.
vi.mock('../hooks/useAsyncData', () => ({
  useAsyncData: () => ({
    data: {
      anthropic_configured: false,
      anthropic_source: null,
      tavily_configured: false,
      openai_configured: false,
      has_documents: false,
      has_verified_facts: false,
      has_cv_template: false,
      setup_complete: false,
      // Operator profile fields (same mock covers /settings/profile).
      full_name: 'Jordan Avery',
      email: 'jordan@example.com',
      current_company: '',
      current_role: '',
      manager_name: '',
      notice_period: '',
      location: 'Remote',
      scoring_model: 'claude-sonnet-5',
      generation_model: 'claude-sonnet-5',
    },
    loading: false,
    isStale: false,
    error: undefined,
    refetch: vi.fn(),
  }),
}))

vi.mock('../lib/api', () => ({
  getSettingsStatus: vi.fn(),
  getOperatorProfile: vi.fn(),
  saveApiKey: vi.fn(),
  uploadKnowledgeSource: vi.fn(),
}))

describe('Setup wizard', () => {
  it('opens on the Connect Claude step with a key field and help link', () => {
    render(
      <MemoryRouter>
        <Setup />
      </MemoryRouter>,
    )
    expect(screen.getByText('Welcome to ZenGrowth')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Connect Claude' })).toBeInTheDocument()
    expect(screen.getByText('Get a key →')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Add this JD' })).toHaveAttribute('href', '/add')
  })
})
