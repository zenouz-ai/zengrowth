import { useCallback, useEffect, useRef, useState } from 'react'

export interface AsyncData<T> {
  data: T | undefined
  error: Error | undefined
  loading: boolean
  isStale: boolean
  refetch: () => void
}

interface Options {
  refreshInterval?: number
}

// Loads one section independently. On failure it PRESERVES the last good data and
// raises an `isStale` flag instead of blanking the UI, so one flaky endpoint never
// cascades into an empty dashboard.
export function useAsyncData<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
  options: Options = {},
): AsyncData<T> {
  const { refreshInterval } = options
  const [data, setData] = useState<T>()
  const [error, setError] = useState<Error>()
  const [loading, setLoading] = useState(true)
  const [isStale, setIsStale] = useState(false)

  const mounted = useRef(true)
  const hasData = useRef(false)
  const fetcherRef = useRef(fetcher)

  // Keep the latest fetcher without making it an effect dependency.
  useEffect(() => {
    fetcherRef.current = fetcher
  })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await fetcherRef.current()
      if (!mounted.current) return
      hasData.current = true
      setData(result)
      setError(undefined)
      setIsStale(false)
    } catch (err) {
      if (!mounted.current) return
      setError(err as Error)
      setIsStale(hasData.current) // stale only if we have prior data to show
    } finally {
      if (mounted.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    mounted.current = true
    // Fetch-on-mount: load() sets loading state; this external-data sync is the
    // intended use here, so the set-state-in-effect heuristic is suppressed.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
    let timer: number | undefined
    if (refreshInterval) {
      timer = window.setInterval(() => void load(), refreshInterval)
    }
    return () => {
      mounted.current = false
      if (timer) window.clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { data, error, loading, isStale, refetch: () => void load() }
}
