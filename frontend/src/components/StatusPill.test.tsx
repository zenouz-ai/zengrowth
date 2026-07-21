import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { STATE_COLORS } from '../lib/stateColors'
import { LIFECYCLE_STATES } from '../lib/types'
import { StatusPill } from './StatusPill'

describe('StatusPill', () => {
  it('has a colour for every lifecycle state', () => {
    for (const state of LIFECYCLE_STATES) {
      expect(STATE_COLORS[state]).toMatch(/^#/)
    }
  })

  it('renders the humanized state label', () => {
    render(<StatusPill state="awaiting_approval" />)
    expect(screen.getByText('awaiting approval')).toBeInTheDocument()
  })
})
