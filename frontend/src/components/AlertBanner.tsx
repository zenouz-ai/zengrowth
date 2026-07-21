type Tone = 'info' | 'warning' | 'error' | 'success'

const TONES: Record<Tone, string> = {
  info: 'var(--color-cyan)',
  warning: 'var(--color-warning)',
  error: 'var(--color-loss)',
  success: 'var(--color-emerald)',
}

export function AlertBanner({ tone = 'info', children }: { tone?: Tone; children: React.ReactNode }) {
  const color = TONES[tone]
  return (
    <div
      className="rounded-lg px-4 py-2 text-sm"
      style={{ color, border: `1px solid ${color}`, background: `${color}14` }}
    >
      {children}
    </div>
  )
}
