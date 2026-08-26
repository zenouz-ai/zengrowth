import { describe, expect, it, vi, beforeEach } from 'vitest'
import {
  filterClaims,
  getCachedKnowledgeClaims,
  invalidateKnowledgeClaimsCache,
  loadKnowledgeClaims,
} from './knowledgeClaimsCache'
import { listKnowledgeClaims } from './api'
import type { EvidenceClaim } from './types'

vi.mock('./api', () => ({
  listKnowledgeClaims: vi.fn(),
}))

const sample: EvidenceClaim[] = [
  {
    id: 'c1',
    source_document_id: 1,
    source_chunk_id: 1,
    claim_text: 'A',
    category: 'skill',
    confidence: 0.5,
    verification_state: 'draft',
    source_span: 'span',
    tags: null,
    created_at: '',
    updated_at: '',
  },
  {
    id: 'c2',
    source_document_id: 1,
    source_chunk_id: 1,
    claim_text: 'B',
    category: 'skill',
    confidence: 0.9,
    verification_state: 'verified',
    source_span: 'span',
    tags: null,
    created_at: '',
    updated_at: '',
  },
]

describe('knowledgeClaimsCache', () => {
  beforeEach(() => {
    invalidateKnowledgeClaimsCache()
    vi.mocked(listKnowledgeClaims).mockReset()
  })

  it('deduplicates concurrent loads', async () => {
    vi.mocked(listKnowledgeClaims).mockResolvedValue(sample)
    const [a, b] = await Promise.all([loadKnowledgeClaims(), loadKnowledgeClaims()])
    expect(a).toEqual(sample)
    expect(b).toEqual(sample)
    expect(listKnowledgeClaims).toHaveBeenCalledTimes(1)
    expect(getCachedKnowledgeClaims()).toEqual(sample)
  })

  it('filters by verification state', async () => {
    vi.mocked(listKnowledgeClaims).mockResolvedValue(sample)
    const all = await loadKnowledgeClaims()
    expect(filterClaims(all, 'draft')).toHaveLength(1)
    expect(filterClaims(all, 'verified')).toHaveLength(1)
  })

  it('returns empty list when claims is not an array', () => {
    expect(filterClaims(null as unknown as EvidenceClaim[], 'draft')).toEqual([])
  })
})
