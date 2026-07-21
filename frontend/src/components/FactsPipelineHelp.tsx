import { Link } from 'react-router-dom'
import { NAV } from '../lib/navLabels'

// Explains where facts in "Approve facts" come from — facts are extracted from
// documents on ingest, not entered manually on the approval screen.
export function FactsPipelineHelp({ compact = false }: { compact?: boolean }) {
  const steps = [
    {
      title: 'Add documents',
      body: 'Upload a CV, paste LaTeX/Markdown, or import files from the server inbox (data/knowledge/inbox/). Supported: PDF, DOCX, MD, TXT, TEX.',
      to: NAV.documents.to,
      link: NAV.documents.label,
    },
    {
      title: 'Automatic extraction',
      body: 'ZenGrowth reads each file, splits it into chunks, and pulls out short factual statements — each paired with a source excerpt from that file.',
      to: null,
      link: null,
    },
    {
      title: 'Auto-approve',
      body: 'Facts with ≥75% confidence and a clear source excerpt are approved automatically and skip this queue.',
      to: null,
      link: null,
    },
    {
      title: 'You approve the rest',
      body: 'Everything else lands on Approve facts. Compare each fact to its source excerpt, then approve or reject. Only approved facts can back generated CVs and cover letters.',
      to: NAV.approveFacts.to,
      link: NAV.approveFacts.label,
    },
  ]

  if (compact) {
    return (
      <p className="text-sm leading-6 text-muted">
        Facts come from your{' '}
        <Link to={NAV.documents.to} className="text-cyan hover:underline">
          {NAV.documents.label}
        </Link>
        , not from this page. Upload or paste a CV there first — extraction runs automatically, then
        lower-confidence facts appear here for approval.
      </p>
    )
  }

  return (
    <section className="rounded-xl border border-cyan/30 bg-cyan/5 px-4 py-4">
      <h2 className="text-sm font-semibold">Where do these facts come from?</h2>
      <p className="mt-1 text-xs text-muted">
        Nothing is typed in manually on this screen. Facts are extracted when you add documents.
      </p>
      <ol className="mt-4 flex flex-col gap-3">
        {steps.map((step, i) => (
          <li key={step.title} className="flex gap-3 text-sm">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border bg-black/20 font-mono text-xs text-muted">
              {i + 1}
            </span>
            <div>
              <p className="font-medium">{step.title}</p>
              <p className="mt-0.5 leading-6 text-muted">{step.body}</p>
              {step.to && step.link && (
                <Link to={step.to} className="mt-1 inline-block text-xs text-cyan hover:underline">
                  Open {step.link} →
                </Link>
              )}
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}
