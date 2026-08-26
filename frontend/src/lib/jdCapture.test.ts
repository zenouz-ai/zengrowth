import { describe, expect, it } from 'vitest'
import {
  JD_CAPTURE_TYPE,
  buildBookmarklet,
  parseJdCapture,
  receiveJdCaptureMessage,
  takeJdCapture,
} from './jdCapture'

describe('parseJdCapture', () => {
  it('accepts url plus body text', () => {
    const parsed = parseJdCapture({
      type: JD_CAPTURE_TYPE,
      url: 'https://boards.greenhouse.io/acme/jobs/1',
      text: 'Acme is hiring a Director of AI to lead the platform. '.repeat(3),
    })
    expect(parsed?.url).toContain('greenhouse')
    expect(parsed?.text.length).toBeGreaterThan(40)
  })

  it('rejects other message types and empty payloads', () => {
    expect(parseJdCapture({ type: 'other', url: 'https://example.com', text: 'x'.repeat(50) })).toBeNull()
    expect(parseJdCapture({ type: JD_CAPTURE_TYPE, url: '', text: 'short' })).toBeNull()
  })

  it('caps oversized text', () => {
    const parsed = parseJdCapture({ type: JD_CAPTURE_TYPE, url: 'https://x.test/j', text: 'a'.repeat(80_000) })
    expect(parsed?.text).toHaveLength(50_000)
  })
})

describe('buildBookmarklet', () => {
  it('targets this origin and the capture message type', () => {
    const src = buildBookmarklet('https://growth.example.com')
    expect(src.startsWith('javascript:')).toBe(true)
    expect(src).toContain('https://growth.example.com')
    expect(src).toContain(JD_CAPTURE_TYPE)
    expect(src).toContain('/add')
  })
})

describe('receiveJdCaptureMessage', () => {
  it('stashes and can be taken once', () => {
    sessionStorage.clear()
    const text = 'Director of AI. Own the platform and the 90-day plan for the CoE.'
    receiveJdCaptureMessage({ type: JD_CAPTURE_TYPE, url: 'https://x.test/j', text })
    const first = takeJdCapture()
    expect(first?.text).toBe(text)
    expect(takeJdCapture()).toBeNull()
  })
})
