import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { extractJob } from '../lib/api'
import { JD_CAPTURE_STORAGE_KEY } from '../lib/jdCapture'
import { AddJob } from './AddJob'

vi.mock('../lib/api', () => ({
  extractJob: vi.fn(),
  createJob: vi.fn(),
}))

const longJd =
  'Acme is hiring a Director of AI to own the platform, the CoE, and the 90-day plan for delivery.'

describe('AddJob', () => {
  beforeEach(() => {
    sessionStorage.clear()
    vi.mocked(extractJob).mockReset()
    vi.mocked(extractJob).mockResolvedValue({
      company: 'Acme',
      title: 'Director of AI',
      location: null,
      hybrid_policy: null,
      compensation: null,
      seniority: null,
      application_url: 'https://boards.example.com/jobs/1',
      posting_date: null,
      description: longJd,
      missing_fields: [],
      confidence_notes: 'ok',
    })
  })

  it('shows the bookmarklet and copy control', async () => {
    render(
      <MemoryRouter>
        <AddJob />
      </MemoryRouter>,
    )
    const link = screen.getByRole('link', { name: 'Add this JD' })
    await waitFor(() => {
      expect(link.getAttribute('href')).toMatch(/^javascript:/)
    })
    expect(link.getAttribute('href')).toContain('/add')
    expect(screen.getByRole('button', { name: 'Copy bookmarklet' })).toBeInTheDocument()
  })

  it('prefills from query params and auto-extracts', async () => {
    const url = 'https://boards.example.com/jobs/1'
    render(
      <MemoryRouter
        initialEntries={[`/add?url=${encodeURIComponent(url)}&text=${encodeURIComponent(longJd)}`]}
      >
        <AddJob />
      </MemoryRouter>,
    )
    expect(screen.getByPlaceholderText('Reference URL (optional)')).toHaveValue(url)
    await waitFor(() => {
      expect(extractJob).toHaveBeenCalledWith(longJd, url)
    })
    expect(await screen.findByDisplayValue('Acme')).toBeInTheDocument()
  })

  it('restores a stashed capture and auto-extracts', async () => {
    const url = 'https://boards.example.com/jobs/1'
    sessionStorage.setItem(JD_CAPTURE_STORAGE_KEY, JSON.stringify({ url, text: longJd }))
    render(
      <MemoryRouter>
        <AddJob />
      </MemoryRouter>,
    )
    await waitFor(() => {
      expect(extractJob).toHaveBeenCalledWith(longJd, url)
    })
    expect(sessionStorage.getItem(JD_CAPTURE_STORAGE_KEY)).toBeNull()
  })

  it('does not auto-extract short pasted text', () => {
    render(
      <MemoryRouter initialEntries={['/add?text=too-short']}>
        <AddJob />
      </MemoryRouter>,
    )
    expect(extractJob).not.toHaveBeenCalled()
  })

  it('still extracts when the operator clicks Extract on short paste', async () => {
    render(
      <MemoryRouter>
        <AddJob />
      </MemoryRouter>,
    )
    fireEvent.change(screen.getByPlaceholderText('Paste the job description…'), {
      target: { value: 'Acme — Head of AI. Remote UK.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Extract fields' }))
    await waitFor(() => {
      expect(extractJob).toHaveBeenCalled()
    })
  })
})
