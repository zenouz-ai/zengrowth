import { listKnowledgeClaims } from './api'
import type { ClaimVerificationState, EvidenceClaim } from './types'

let cache: EvidenceClaim[] | null = null
let inflight: Promise<EvidenceClaim[]> | null = null
const subscribers = new Set<() => void>()

function notify() {
  subscribers.forEach((fn) => fn())
}

export function subscribeKnowledgeClaims(listener: () => void): () => void {
  subscribers.add(listener)
  return () => subscribers.delete(listener)
}

export function getCachedKnowledgeClaims(): EvidenceClaim[] | null {
  return cache
}

export function invalidateKnowledgeClaimsCache(): void {
  cache = null
  inflight = null
  notify()
}

export async function loadKnowledgeClaims(): Promise<EvidenceClaim[]> {
  if (cache) return cache
  if (!inflight) {
    inflight = listKnowledgeClaims()
      .then((data) => {
        cache = data
        inflight = null
        notify()
        return data
      })
      .catch((err) => {
        inflight = null
        throw err
      })
  }
  return inflight
}

export async function refetchKnowledgeClaims(): Promise<EvidenceClaim[]> {
  invalidateKnowledgeClaimsCache()
  return loadKnowledgeClaims()
}

export function filterClaims(
  claims: EvidenceClaim[],
  state?: ClaimVerificationState,
): EvidenceClaim[] {
  if (!Array.isArray(claims)) return []
  if (!state) return claims
  return claims.filter((c) => c.verification_state === state)
}
