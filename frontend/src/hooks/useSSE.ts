import { useEffect, useRef, useState } from 'react'
import { authBridge } from '../lib/authBridge'

export interface SSEState<T> {
  events: T[]
  connected: boolean
  disconnected: boolean // surfaced only after a grace period
}

interface Options {
  maxEvents?: number
  // Test seam: inject a fetch and disable real timers.
  fetchImpl?: typeof fetch
}

const BASE_DELAY = 1_000
const MAX_DELAY = 30_000
const DISCONNECT_GRACE = 8_000

// Exponential backoff with jitter, capped. Exported for tests.
export function backoff(attempt: number): number {
  const capped = Math.min(MAX_DELAY, BASE_DELAY * 2 ** attempt)
  return capped / 2 + Math.random() * (capped / 2)
}

export interface ParsedFrame {
  id?: string
  data?: string
  keepalive: boolean
}

// Parse one SSE frame (lines up to a blank-line separator). Exported for tests.
export function parseSSEFrame(frame: string): ParsedFrame {
  const result: ParsedFrame = { keepalive: false }
  for (const line of frame.split('\n')) {
    if (line.startsWith(':')) {
      result.keepalive = true
      continue
    }
    if (line.startsWith('id:')) result.id = line.slice(3).trim()
    if (line.startsWith('data:')) result.data = (result.data ?? '') + line.slice(5).trim()
  }
  return result
}

// Consumes an SSE endpoint with fetch + ReadableStream (credentialed), drains
// partial frames from a buffer, reconnects with exponential backoff + jitter,
// and stops cleanly on 401/403 (flipping the auth bridge). Surfaces a
// disconnected flag only after a grace period so brief blips stay quiet.
export function useSSE<T = unknown>(url: string, options: Options = {}): SSEState<T> {
  const { maxEvents = 100, fetchImpl } = options
  const [events, setEvents] = useState<T[]>([])
  const [connected, setConnected] = useState(false)
  const [disconnected, setDisconnected] = useState(false)

  const lastEventId = useRef<string | null>(null)
  const stopped = useRef(false)

  useEffect(() => {
    stopped.current = false
    const doFetch = fetchImpl ?? window.fetch.bind(window)
    let attempt = 0
    let graceTimer: number | undefined
    let reconnectTimer: number | undefined

    const scheduleDisconnect = () => {
      graceTimer = window.setTimeout(() => setDisconnected(true), DISCONNECT_GRACE)
    }
    const clearDisconnect = () => {
      if (graceTimer) window.clearTimeout(graceTimer)
      setDisconnected(false)
    }

    async function connect(): Promise<void> {
      if (stopped.current) return
      try {
        const headers: Record<string, string> = { Accept: 'text/event-stream' }
        if (lastEventId.current) headers['Last-Event-ID'] = lastEventId.current
        const res = await doFetch(url, { headers, credentials: 'include' })

        if (res.status === 401 || res.status === 403) {
          authBridge.setUnauthed()
          stopped.current = true
          return
        }
        if (!res.ok || !res.body) throw new Error(`SSE ${res.status}`)

        setConnected(true)
        clearDisconnect()
        attempt = 0

        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        for (;;) {
          const { value, done } = await reader.read()
          if (done || stopped.current) break
          buffer += decoder.decode(value, { stream: true })
          let sep: number
          while ((sep = buffer.indexOf('\n\n')) !== -1) {
            const frame = buffer.slice(0, sep)
            buffer = buffer.slice(sep + 2)
            handleFrame(frame)
          }
        }
      } catch {
        // fall through to reconnect
      }
      if (stopped.current) return
      setConnected(false)
      scheduleDisconnect()
      const delay = backoff(attempt++)
      reconnectTimer = window.setTimeout(() => void connect(), delay)
    }

    function handleFrame(frame: string): void {
      const parsed = parseSSEFrame(frame)
      if (parsed.id) lastEventId.current = parsed.id
      if (parsed.keepalive || !parsed.data) return
      try {
        const event = JSON.parse(parsed.data) as T
        setEvents((prev) => [event, ...prev].slice(0, maxEvents))
      } catch {
        // ignore malformed frame
      }
    }

    void connect()
    return () => {
      stopped.current = true
      if (graceTimer) window.clearTimeout(graceTimer)
      if (reconnectTimer) window.clearTimeout(reconnectTimer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url])

  return { events, connected, disconnected }
}
