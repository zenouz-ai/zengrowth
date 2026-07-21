import { useState } from 'react'
import { Link } from 'react-router-dom'
import { NAV } from '../lib/navLabels'

const STORAGE_KEY = 'zengrowth_operator_guide_dismissed'

// A one-line welcome, not a manual (PS-P3). The four-destination nav and the
// first-run wizard now carry the explaining; this just points at the next step
// and gets out of the way once dismissed.
export function OperatorGuide() {
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === '1'
    } catch {
      return false
    }
  })

  function dismiss() {
    setDismissed(true)
    try {
      localStorage.setItem(STORAGE_KEY, '1')
    } catch {
      // ignore
    }
  }

  if (dismissed) return null

  return (
    <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border/70 bg-white/[0.02] px-4 py-3 text-sm">
      <p className="text-muted">
        New here? Add your CV on{' '}
        <Link to={NAV.library.to} className="text-cyan hover:underline">
          {NAV.library.label}
        </Link>
        , then paste a job on{' '}
        <Link to={NAV.jobs.to} className="text-cyan hover:underline">
          {NAV.jobs.label}
        </Link>{' '}
        to score it and generate a tailored application.
      </p>
      <button onClick={dismiss} className="micro-label shrink-0 text-muted hover:text-text">
        dismiss
      </button>
    </section>
  )
}
