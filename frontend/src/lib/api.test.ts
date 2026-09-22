import { describe, expect, it } from 'vitest'
import { AxiosError, AxiosHeaders } from 'axios'
import { apiErrorMessage } from './api'

describe('apiErrorMessage', () => {
  it('returns string detail from API responses', () => {
    const error = new AxiosError('fail', 'ERR', undefined, undefined, {
      status: 503,
      data: { detail: 'Claude rate limit hit — wait a moment and try again.' },
      statusText: 'Service Unavailable',
      headers: {},
      config: { headers: new AxiosHeaders() },
    })
    expect(apiErrorMessage(error, 'fallback')).toBe(
      'Claude rate limit hit — wait a moment and try again.',
    )
  })

  it('maps request timeouts to a clear message', () => {
    const error = new AxiosError('timeout', 'ECONNABORTED')
    expect(apiErrorMessage(error, 'fallback')).toBe('Generation timed out — try again.')
  })

  it('maps network failures without a response', () => {
    const error = new AxiosError('Network Error')
    expect(apiErrorMessage(error, 'fallback')).toBe(
      'Could not reach the server — check your connection and try again.',
    )
  })
})
