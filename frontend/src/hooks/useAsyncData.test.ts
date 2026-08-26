import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useAsyncData } from './useAsyncData'

describe('useAsyncData', () => {
  it('loads data', async () => {
    const { result } = renderHook(() => useAsyncData(() => Promise.resolve(42), []))
    await waitFor(() => expect(result.current.data).toBe(42))
    expect(result.current.error).toBeUndefined()
    expect(result.current.isStale).toBe(false)
  })

  it('preserves stale data and flags isStale on a failed refetch', async () => {
    let call = 0
    const fetcher = vi.fn(() => {
      call += 1
      return call === 1 ? Promise.resolve('good') : Promise.reject(new Error('boom'))
    })
    const { result } = renderHook(() => useAsyncData(fetcher, []))
    await waitFor(() => expect(result.current.data).toBe('good'))

    await act(async () => {
      result.current.refetch()
    })
    await waitFor(() => expect(result.current.isStale).toBe(true))
    expect(result.current.data).toBe('good') // preserved, not blanked
    expect(result.current.error).toBeInstanceOf(Error)
  })
})
