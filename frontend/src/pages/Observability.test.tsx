import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Observability } from './Observability'

vi.mock('../hooks/useAsyncData', () => ({
  useAsyncData: () => ({
    data: {
      today: { total_cost_usd: 0.01, total_tokens: 100, avg_latency_ms: 200, call_count: 1, error_rate: 0 },
      '7d': { total_cost_usd: 0.05, total_tokens: 500, avg_latency_ms: 180, call_count: 5, error_rate: 0 },
      '30d': { total_cost_usd: 0.1, total_tokens: 1000, avg_latency_ms: 170, call_count: 10, error_rate: 0 },
    },
    loading: false,
    isStale: false,
    error: undefined,
    refetch: vi.fn(),
  }),
}))

vi.mock('../hooks/useSSE', () => ({
  useSSE: () => ({ events: [], connected: true, disconnected: false }),
}))

describe('Observability page', () => {
  it('renders KPI headings', () => {
    render(<Observability />)
    expect(screen.getByText('Usage')).toBeInTheDocument()
    expect(screen.getByText('Cost today')).toBeInTheDocument()
  })
})
