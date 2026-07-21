interface PanelProps {
  title?: string
  actions?: React.ReactNode
  children: React.ReactNode
  className?: string
}

// Glass surface used as the base container for every section.
export function Panel({ title, actions, children, className = '' }: PanelProps) {
  return (
    <section className={`glass p-5 ${className}`}>
      {(title || actions) && (
        <header className="mb-4 flex items-center justify-between gap-3">
          {title && <h2 className="text-lg font-semibold">{title}</h2>}
          {actions}
        </header>
      )}
      {children}
    </section>
  )
}
