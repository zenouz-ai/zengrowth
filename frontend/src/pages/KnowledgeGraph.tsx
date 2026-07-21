import { useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { AlertBanner } from '../components/AlertBanner'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { Skeleton } from '../components/Skeleton'
import { SourceDetailPanel } from '../components/SourceDetailPanel'
import { useAsyncData } from '../hooks/useAsyncData'
import { getKnowledgeGraph } from '../lib/api'
import { NAV } from '../lib/navLabels'
import type { GraphEdge, GraphEdgeKind, GraphNode, KnowledgeGraph } from '../lib/types'

const NODE_W = 196
const NODE_H = 74
const COL_GAP = 56
const LANE_GAP = 64

const KIND_ORDER: Record<string, number> = { source: 0, claim: 1, entity: 2 }

const EDGE_STYLE: Record<GraphEdgeKind, { className: string; label: string; dash?: string }> = {
  supersedes: { className: 'text-cyan', label: 'version (supersedes)' },
  related_to: { className: 'text-violet', label: 'related topic', dash: '5 4' },
  has_claim: { className: 'text-emerald', label: 'has claim' },
  mentions: { className: 'text-muted', label: 'mentions', dash: '3 3' },
}

interface Positioned extends GraphNode {
  x: number
  y: number
}

function layout(nodes: GraphNode[]): { positioned: Positioned[]; width: number; height: number } {
  const lanes = new Map<string, GraphNode[]>()
  for (const node of nodes) {
    const key = node.group || node.kind
    const lane = lanes.get(key) ?? []
    lane.push(node)
    lanes.set(key, lane)
  }
  const laneKeys = [...lanes.keys()].sort((a, b) => {
    const ka = lanes.get(a)![0]
    const kb = lanes.get(b)![0]
    const ko = (KIND_ORDER[ka.kind] ?? 9) - (KIND_ORDER[kb.kind] ?? 9)
    return ko !== 0 ? ko : a.localeCompare(b)
  })

  const positioned: Positioned[] = []
  let maxCols = 0
  laneKeys.forEach((key, laneIndex) => {
    const lane = lanes.get(key)!.slice().sort((a, b) => {
      const la = (a.meta?.lineage_id as string) ?? ''
      const lb = (b.meta?.lineage_id as string) ?? ''
      if (la !== lb) return la.localeCompare(lb)
      const va = (a.meta?.version as number) ?? 0
      const vb = (b.meta?.version as number) ?? 0
      if (va !== vb) return va - vb
      return a.label.localeCompare(b.label)
    })
    lane.forEach((node, col) => {
      positioned.push({
        ...node,
        x: col * (NODE_W + COL_GAP),
        y: laneIndex * (NODE_H + LANE_GAP),
      })
    })
    maxCols = Math.max(maxCols, lane.length)
  })
  return {
    positioned,
    width: Math.max(1, maxCols) * (NODE_W + COL_GAP),
    height: Math.max(1, laneKeys.length) * (NODE_H + LANE_GAP),
  }
}

function nodeBorder(node: GraphNode): string {
  if (node.kind === 'claim') return 'border-emerald/60'
  if (node.kind === 'entity') return 'border-violet/60'
  if (node.meta?.template_role === 'cv_style' && node.meta?.is_current) return 'border-emerald'
  if (node.meta?.is_current === false) return 'border-border/50'
  return 'border-cyan/60'
}

export function KnowledgeGraph() {
  const [includeClaims, setIncludeClaims] = useState(false)
  const [includeEntities, setIncludeEntities] = useState(false)
  const [includeLineage, setIncludeLineage] = useState(false)
  const graph = useAsyncData<KnowledgeGraph>(
    () => getKnowledgeGraph({ includeClaims, includeEntities, includeLineage }),
    [includeClaims, includeEntities, includeLineage],
  )
  const [searchParams, setSearchParams] = useSearchParams()
  const initialSource = searchParams.get('source')
  const [selectedSourceId, setSelectedSourceId] = useState<number | null>(
    initialSource ? Number(initialSource) : null,
  )

  const { positioned, width, height } = useMemo(
    () => layout(graph.data?.nodes ?? []),
    [graph.data],
  )
  const centerById = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>()
    for (const node of positioned) {
      map.set(node.id, { x: node.x + NODE_W / 2, y: node.y + NODE_H / 2 })
    }
    return map
  }, [positioned])

  // Pan + zoom transform.
  const [scale, setScale] = useState(0.8)
  const [offset, setOffset] = useState({ x: 40, y: 40 })
  const dragRef = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null)

  function onPointerDown(e: React.PointerEvent) {
    if ((e.target as HTMLElement).closest('[data-node]')) return
    dragRef.current = { x: e.clientX, y: e.clientY, ox: offset.x, oy: offset.y }
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }
  function onPointerMove(e: React.PointerEvent) {
    const drag = dragRef.current
    if (!drag) return
    setOffset({ x: drag.ox + (e.clientX - drag.x), y: drag.oy + (e.clientY - drag.y) })
  }
  function onPointerUp() {
    dragRef.current = null
  }
  function onWheel(e: React.WheelEvent) {
    const next = Math.min(2, Math.max(0.3, scale - e.deltaY * 0.001))
    setScale(next)
  }

  const usedEdgeKinds = useMemo(() => {
    const kinds = new Set<GraphEdgeKind>()
    for (const edge of graph.data?.edges ?? []) kinds.add(edge.kind)
    return kinds
  }, [graph.data])

  function selectNode(node: GraphNode) {
    if (node.kind !== 'source' || !node.ref_id) return
    const id = Number(node.ref_id)
    setSelectedSourceId(id)
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('source', String(id))
      return next
    })
  }

  function closePanel() {
    setSelectedSourceId(null)
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.delete('source')
      return next
    })
  }

  const isEmpty = !graph.loading && (graph.data?.nodes.length ?? 0) === 0

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title={NAV.documentGraph.label}
        description="Visual map of your documents, versions, and how extracted facts relate. Click a source node to preview the file and approve facts from that document."
        actions={
          <Link to={NAV.documents.to} className="micro-label hover:text-text">
            back to documents
          </Link>
        }
      />

      {graph.error && !graph.data && <AlertBanner tone="error">Failed to load graph.</AlertBanner>}

      <div className="flex flex-wrap items-center gap-4 text-sm">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={includeClaims} onChange={(e) => setIncludeClaims(e.target.checked)} />
          facts
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={includeEntities} onChange={(e) => setIncludeEntities(e.target.checked)} />
          entities
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={includeLineage} onChange={(e) => setIncludeLineage(e.target.checked)} />
          full lineage (chunks + materials)
        </label>
        <div className="flex flex-wrap items-center gap-3">
          {[...usedEdgeKinds].map((kind) => (
            <span key={kind} className="flex items-center gap-1 text-xs text-muted">
              <span className={`inline-block h-0.5 w-5 ${EDGE_STYLE[kind].className}`} style={{ backgroundColor: 'currentColor' }} />
              {EDGE_STYLE[kind].label}
            </span>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
        <Panel className="!p-0">
          {graph.loading && !graph.data ? (
            <Skeleton className="h-[70vh]" />
          ) : isEmpty ? (
            <div className="flex h-[70vh] items-center justify-center text-sm text-muted">
              No sources yet. Upload or paste knowledge to build the graph.
            </div>
          ) : (
            <div
              className="relative h-[70vh] cursor-grab overflow-hidden rounded-2xl"
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerLeave={onPointerUp}
              onWheel={onWheel}
            >
              <div
                className="absolute left-0 top-0 origin-top-left"
                style={{ transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})` }}
              >
                <svg
                  width={width + NODE_W}
                  height={height + NODE_H}
                  className="absolute left-0 top-0 overflow-visible"
                >
                  {(graph.data?.edges ?? []).map((edge: GraphEdge) => {
                    const a = centerById.get(edge.source)
                    const b = centerById.get(edge.target)
                    if (!a || !b) return null
                    const style = EDGE_STYLE[edge.kind]
                    return (
                      <line
                        key={edge.id}
                        x1={a.x}
                        y1={a.y}
                        x2={b.x}
                        y2={b.y}
                        stroke="currentColor"
                        strokeWidth={1.5}
                        strokeDasharray={style.dash}
                        className={`${style.className} opacity-70`}
                      />
                    )
                  })}
                </svg>
                {positioned.map((node) => (
                  <button
                    key={node.id}
                    data-node
                    onClick={() => selectNode(node)}
                    style={{ left: node.x, top: node.y, width: NODE_W, height: NODE_H }}
                    className={`absolute flex flex-col justify-center rounded-xl border bg-black/40 px-3 py-2 text-left backdrop-blur transition hover:bg-black/60 ${nodeBorder(node)} ${
                      selectedSourceId != null && node.ref_id === String(selectedSourceId)
                        ? 'ring-2 ring-cyan'
                        : ''
                    }`}
                  >
                    <span className="truncate text-sm font-medium">{node.label}</span>
                    {node.detail && (
                      <span className="truncate text-xs text-muted">{node.detail}</span>
                    )}
                    <span className="mt-0.5 micro-label">
                      {node.group}
                      {node.kind === 'source' && node.meta?.version ? ` · v${node.meta.version}` : ''}
                    </span>
                  </button>
                ))}
              </div>
              <div className="pointer-events-none absolute bottom-3 right-3 rounded-lg bg-black/50 px-2 py-1 text-xs text-muted">
                drag to pan · scroll to zoom
              </div>
            </div>
          )}
        </Panel>

        <div className="h-[70vh]">
          <SourceDetailPanel
            sourceId={selectedSourceId}
            onClose={closePanel}
            onChanged={() => graph.refetch()}
          />
        </div>
      </div>
    </div>
  )
}
