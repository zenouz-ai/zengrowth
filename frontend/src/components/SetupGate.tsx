import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { getSettingsStatus } from '../lib/api'

// Hard first-run gate (PS-P1): the operator surface needs an LLM key to do
// anything useful, so an unconfigured app is redirected to the setup wizard.
// Only the *missing key* blocks — CV upload and template steps stay skippable.
export function SetupGate({ children }: { children: React.ReactNode }) {
  const [resolved, setResolved] = useState(false)
  const [needsKey, setNeedsKey] = useState(false)

  useEffect(() => {
    let active = true
    getSettingsStatus()
      .then((s) => active && setNeedsKey(!s.anthropic_configured))
      .catch(() => active && setNeedsKey(false)) // never trap the user on a fetch error
      .finally(() => active && setResolved(true))
    return () => {
      active = false
    }
  }, [])

  if (!resolved) return <div className="p-8 micro-label">loading…</div>
  if (needsKey) return <Navigate to="/setup" replace />
  return <>{children}</>
}
