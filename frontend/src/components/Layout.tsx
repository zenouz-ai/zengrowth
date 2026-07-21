import { Suspense, useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { getSettingsStatus, logout } from '../lib/api'
import { FLAT_NAV_LINKS, NAV, PRIMARY_NAV } from '../lib/navLabels'
import { ErrorBoundary } from './ErrorBoundary'

export function Layout() {
  const navigate = useNavigate()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const [setupIncomplete, setSetupIncomplete] = useState(false)

  // A quiet "finish setup" nudge while the engine isn't fully wired (PS-P1/P4).
  useEffect(() => {
    let active = true
    getSettingsStatus()
      .then((s) => active && setSetupIncomplete(!s.setup_complete))
      .catch(() => undefined)
    return () => {
      active = false
    }
  }, [location.pathname])

  async function onLogout() {
    await logout().catch(() => undefined)
    navigate('/login')
  }

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    isActive ? 'text-text' : 'text-muted hover:text-text'

  // App-like back navigation on every page except Home: pop in-app history
  // when there is any, otherwise land on the dashboard (e.g. a deep link
  // opened fresh from a phone's home screen).
  const isHome = location.pathname === '/'
  function goBack() {
    const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0
    if (idx > 0) navigate(-1)
    else navigate('/')
  }

  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-40 border-b border-border bg-bg/80 backdrop-blur-md safe-px">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-0 py-3 sm:px-2 sm:py-4">
          <div className="flex items-center gap-3 sm:gap-4">
            {!isHome && (
              <button
                onClick={goBack}
                aria-label="Go back"
                className="-ml-1 flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-muted transition-colors hover:bg-white/5 hover:text-text"
              >
                <svg
                  aria-hidden
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.25"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M15 18l-6-6 6-6" />
                </svg>
              </button>
            )}
            <NavLink to="/" className="flex items-center gap-2.5">
              <img src="/favicon.svg" alt="" className="h-6 w-6" />
              <span className="font-heading text-lg font-bold tracking-tight">ZenGrowth</span>
            </NavLink>
            <nav className="hidden items-center gap-6 text-sm lg:ml-4 lg:flex">
              {PRIMARY_NAV.map((l) => (
                <NavLink key={l.to} to={l.to} end={l.to === '/'} className={linkClass}>
                  {l.label}
                </NavLink>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-3">
            {setupIncomplete && (
              <NavLink
                to={NAV.setup.to}
                className="hidden rounded-full border border-cyan/50 bg-cyan/10 px-3 py-1 micro-label text-cyan hover:bg-cyan/15 sm:inline-block"
              >
                Finish setup
              </NavLink>
            )}
            <NavLink to={NAV.setup.to} className="hidden micro-label hover:text-text sm:inline">
              setup
            </NavLink>
            <button onClick={onLogout} className="hidden micro-label hover:text-text sm:inline">
              log out
            </button>
            <button
              onClick={() => setMenuOpen((v) => !v)}
              className="min-h-[44px] rounded-lg border border-border px-4 text-sm lg:hidden"
              aria-expanded={menuOpen}
              aria-label="Toggle navigation"
            >
              {menuOpen ? 'Close' : 'Menu'}
            </button>
          </div>
        </div>

        {menuOpen && (
          <nav className="max-h-[calc(100dvh-4rem)] overflow-y-auto border-t border-border px-0 py-3 lg:hidden">
            <ul className="flex flex-col gap-1">
              {[...FLAT_NAV_LINKS, NAV.setup].map((l) => (
                <li key={l.to}>
                  <NavLink
                    to={l.to}
                    end={l.to === '/'}
                    onClick={() => setMenuOpen(false)}
                    className={({ isActive }) =>
                      `block rounded-lg px-3 py-2.5 text-sm ${
                        isActive ? 'bg-white/5 text-text' : 'text-muted hover:bg-white/5'
                      }`
                    }
                  >
                    {l.label}
                  </NavLink>
                </li>
              ))}
              <li>
                <button
                  onClick={onLogout}
                  className="block w-full rounded-lg px-3 py-2.5 text-left text-sm text-muted hover:bg-white/5"
                >
                  Log out
                </button>
              </li>
            </ul>
          </nav>
        )}
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6 safe-pb sm:px-6 sm:py-8">
        {/* A page crash stays contained here; the nav/chrome above survive and
            the boundary auto-resets when the route changes (EA-05). */}
        <ErrorBoundary resetKey={location.pathname}>
          {/* Pages are code-split; this keeps the header chrome in place while
              a page chunk loads instead of falling back to the app-level shell. */}
          <Suspense fallback={<div className="p-8 micro-label">loading…</div>}>
            <Outlet />
          </Suspense>
        </ErrorBoundary>
      </main>
    </div>
  )
}
