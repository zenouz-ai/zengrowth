import { useEffect, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { checkSession } from '../lib/api'
import { useAuthed } from './useAuth'

// Renders a loading state until auth resolves, then redirects unauthenticated
// visitors to /login?next=... so they return to where they were headed.
export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const authed = useAuthed()
  const location = useLocation()
  const [resolved, setResolved] = useState(false)

  useEffect(() => {
    void checkSession().finally(() => setResolved(true))
  }, [])

  if (!resolved) {
    return <div className="p-8 micro-label">checking session…</div>
  }
  if (!authed) {
    const next = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }
  return <>{children}</>
}
