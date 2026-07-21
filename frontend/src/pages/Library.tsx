import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Coverage } from './Coverage'
import { Knowledge } from './Knowledge'
import { ReviewQueue } from './ReviewQueue'

// Library merges the halves of the knowledge bank into one destination
// (PS-P3/P4): the documents you add, the facts pulled from them awaiting
// approval, and the coverage map of what all that evidence adds up to (KG-02).
// Each tab renders the existing page so deep links and inner flows keep
// working; the nav just stops being separate top-level items.
type Tab = 'documents' | 'review' | 'coverage'

export function Library() {
  const [params, setParams] = useSearchParams()
  const tabParam = params.get('tab')
  const initial: Tab = tabParam === 'review' ? 'review' : tabParam === 'coverage' ? 'coverage' : 'documents'
  const [tab, setTab] = useState<Tab>(initial)

  function select(next: Tab) {
    setTab(next)
    setParams(next === 'documents' ? {} : { tab: next }, { replace: true })
  }

  const tabClass = (active: boolean) =>
    `rounded-lg px-3 py-1.5 text-sm ${
      active ? 'bg-white/5 text-text' : 'text-muted hover:text-text'
    }`

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border/70 bg-white/[0.02] p-1.5">
        <button onClick={() => select('documents')} className={tabClass(tab === 'documents')}>
          Documents
        </button>
        <button onClick={() => select('review')} className={tabClass(tab === 'review')}>
          Facts to review
        </button>
        <button onClick={() => select('coverage')} className={tabClass(tab === 'coverage')}>
          Coverage
        </button>
      </div>
      {tab === 'documents' ? <Knowledge /> : tab === 'review' ? <ReviewQueue /> : <Coverage />}
    </div>
  )
}
