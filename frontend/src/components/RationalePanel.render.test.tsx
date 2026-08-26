import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RationalePanel } from './RationalePanel'

describe('RationalePanel', () => {
  it('surfaces the recommendation and each dimension reason', () => {
    render(
      <RationalePanel
        expectedValue={7.2}
        rationale={{
          summary: 'Strong fit on title and tech.',
          match_quality: { score: 72, reason: 'Strong overall alignment.' },
          compensation_fit: { score: 60, reason: 'Band overlaps target minimum.' },
        }}
      />,
    )
    expect(screen.getByText('Strong fit on title and tech.')).toBeInTheDocument()
    expect(screen.getByText('Strong overall alignment.')).toBeInTheDocument()
    expect(screen.getByText('Band overlaps target minimum.')).toBeInTheDocument()
    expect(screen.getByText('Compensation Fit')).toBeInTheDocument()
  })

  it('prompts to score when no rationale exists', () => {
    render(<RationalePanel expectedValue={null} rationale={null} />)
    expect(screen.getByText(/Not scored yet/i)).toBeInTheDocument()
  })
})
