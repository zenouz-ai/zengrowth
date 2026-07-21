import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { Layout } from './Layout'

vi.mock('../lib/api', () => ({
  getSettingsStatus: vi.fn(async () => ({ setup_complete: true })),
  logout: vi.fn(),
}))

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<div>home page</div>} />
          <Route path="/jobs/:id" element={<div>job page</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('Layout back navigation', () => {
  it('shows a back button on inner pages for an app-like mobile experience', () => {
    renderAt('/jobs/1')
    expect(screen.getByRole('button', { name: 'Go back' })).toBeInTheDocument()
  })

  it('hides the back button on the home dashboard', () => {
    renderAt('/')
    expect(screen.queryByRole('button', { name: 'Go back' })).not.toBeInTheDocument()
  })
})
