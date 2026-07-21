import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { AlertBanner } from '../components/AlertBanner'
import { login } from '../lib/api'

export function Login() {
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string>()
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = params.get('next') || '/'

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(undefined)
    try {
      await login(password)
      navigate(next, { replace: true })
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status
      setError(
        status === 503
          ? 'Operator auth is not configured.'
          : status === 429
            ? 'Too many attempts — wait a moment, then try again.'
            : 'Invalid credentials.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden safe-px safe-pb pt-6">
      {/* Ambient brand glow; purely decorative and pauses under reduced motion. */}
      <div aria-hidden className="pointer-events-none absolute inset-0">
        <div className="animate-aurora absolute -top-32 left-1/2 h-[28rem] w-[28rem] -translate-x-2/3 rounded-full bg-[rgba(99,50,255,0.22)] blur-[110px]" />
        <div
          className="animate-aurora absolute -bottom-40 right-0 h-[24rem] w-[24rem] rounded-full bg-[rgba(0,212,255,0.13)] blur-[110px]"
          style={{ animationDelay: '-7s' }}
        />
      </div>

      <div className="relative w-full max-w-sm">
        <div className="animate-rise mb-8 flex flex-col items-center gap-4">
          <img
            src="/favicon.svg"
            alt=""
            className="h-16 w-16 drop-shadow-[0_6px_24px_rgba(99,50,255,0.55)]"
          />
          <div className="text-center">
            <h1 className="font-heading text-3xl font-bold tracking-tight">ZenGrowth</h1>
            <p className="mt-1 text-sm text-muted">Career AI operating system</p>
          </div>
        </div>

        <section className="glass animate-rise-late p-6 sm:p-7">
          <p className="micro-label mb-5">Operator login</p>
          <form onSubmit={onSubmit} className="flex flex-col gap-4">
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                autoFocus
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Password"
                aria-label="Password"
                /* text-base keeps iOS Safari from auto-zooming on focus */
                className="w-full rounded-xl border border-border bg-black/30 px-4 py-3 pr-16 text-base outline-none transition-colors placeholder:text-muted/70 focus:border-cyan focus:ring-2 focus:ring-cyan/20"
              />
              {password && (
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  className="micro-label absolute right-3 top-1/2 -translate-y-1/2 rounded px-1 py-2 hover:text-text"
                >
                  {showPassword ? 'hide' : 'show'}
                </button>
              )}
            </div>
            {error && <AlertBanner tone="error">{error}</AlertBanner>}
            <button
              type="submit"
              disabled={busy || !password}
              className="rounded-xl bg-gradient-to-r from-violet to-[#00a8d4] px-4 py-3 text-sm font-semibold text-white shadow-[0_4px_24px_rgba(99,50,255,0.35)] transition-[opacity,transform] hover:opacity-90 active:scale-[0.99] disabled:opacity-40 disabled:shadow-none"
            >
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        </section>

        <p className="animate-rise-late mt-6 text-center">
          <Link to="/public" className="micro-label hover:text-text">
            view public dashboard →
          </Link>
        </p>
      </div>
    </div>
  )
}
