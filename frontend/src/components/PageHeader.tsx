import type { ReactNode } from 'react'

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description: string
  actions?: ReactNode
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="max-w-2xl">
        <h1 className="font-heading text-2xl font-bold">{title}</h1>
        <p className="mt-1 text-sm leading-6 text-muted">{description}</p>
      </div>
      {actions}
    </header>
  )
}
