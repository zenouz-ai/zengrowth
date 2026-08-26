interface MetricCardProps {
  label: string
  value: React.ReactNode
  hint?: string
}

export function MetricCard({ label, value, hint }: MetricCardProps) {
  return (
    <div className="glass px-4 py-3">
      <div className="micro-label">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-text">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  )
}
