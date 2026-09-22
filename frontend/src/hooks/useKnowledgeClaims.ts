import { useCallback, useEffect, useState } from 'react'
import {
  filterClaims,
  getCachedKnowledgeClaims,
  loadKnowledgeClaims,
  refetchKnowledgeClaims,
  subscribeKnowledgeClaims,
} from '../lib/knowledgeClaimsCache'
import type { ClaimVerificationState, EvidenceClaim } from '../lib/types'

// Shared, cached claim list so EvidencePanel and other surfaces do not each
// refetch the full bank on every expand.
export function useKnowledgeClaims(state?: ClaimVerificationState) {
  const [data, setData] = useState<EvidenceClaim[] | undefined>(() => {
    const cached = getCachedKnowledgeClaims()
    return cached ? filterClaims(cached, state) : undefined
  })
  const [loading, setLoading] = useState(!getCachedKnowledgeClaims())
  const [error, setError] = useState<Error>()

  const sync = useCallback(() => {
    const cached = getCachedKnowledgeClaims()
    if (cached) {
      setData(filterClaims(cached, state))
      return
    }
    loadKnowledgeClaims()
      .then((claims) => {
        setData(filterClaims(claims, state))
        setError(undefined)
      })
      .catch((err) => setError(err as Error))
  }, [state])

  useEffect(() => subscribeKnowledgeClaims(sync), [sync])

  useEffect(() => {
    let cancelled = false
    // Fetch-on-mount: load() sets loading state; this external-data sync is the
    // intended use here, so the set-state-in-effect heuristic is suppressed.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!getCachedKnowledgeClaims()) setLoading(true)
    loadKnowledgeClaims()
      .then((claims) => {
        if (!cancelled) {
          setData(filterClaims(claims, state))
          setError(undefined)
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err as Error)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [state])

  const refetch = useCallback(async () => {
    setLoading(true)
    try {
      const claims = await refetchKnowledgeClaims()
      setData(filterClaims(claims, state))
      setError(undefined)
    } catch (err) {
      setError(err as Error)
    } finally {
      setLoading(false)
    }
  }, [state])

  return { data, loading, error, refetch }
}
