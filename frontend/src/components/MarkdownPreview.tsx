import { isValidElement, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'
import {
  isObsidianCallout,
  preprocessMarkdown,
  type ObsidianCalloutKind,
} from '../lib/markdownPreprocess'

const CALLOUT_STYLES: Record<ObsidianCalloutKind, string> = {
  tip: 'border-cyan/60 bg-cyan/10 text-text',
  warning: 'border-warning/60 bg-warning/10 text-text',
  note: 'border-border bg-white/[0.04] text-text/90',
  info: 'border-violet/60 bg-violet/10 text-text',
}

function CalloutPanel({ kind, children }: { kind: ObsidianCalloutKind; children: ReactNode }) {
  const label = kind.charAt(0).toUpperCase() + kind.slice(1)
  return (
    <aside
      className={`mb-4 rounded-lg border px-4 py-3 text-sm leading-6 ${CALLOUT_STYLES[kind]}`}
    >
      <p className="mb-1 text-xs font-semibold uppercase tracking-wide opacity-80">{label}</p>
      <div className="space-y-2 [&>p:last-child]:mb-0">{children}</div>
    </aside>
  )
}

function blockquoteFromChildren(children: ReactNode): string {
  const parts: string[] = []
  const walk = (node: ReactNode) => {
    if (typeof node === 'string') parts.push(node)
    else if (Array.isArray(node)) node.forEach(walk)
    else if (isValidElement<{ children?: ReactNode }>(node)) {
      walk(node.props.children)
    }
  }
  walk(children)
  return parts.join('\n').trim()
}

const components: Components = {
  h1: ({ children }) => (
    <h1 className="mb-4 mt-1 font-heading text-2xl font-bold text-text">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="mb-3 mt-6 border-b border-border/50 pb-1 font-heading text-lg font-semibold text-text first:mt-2">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="mb-2 mt-4 font-heading text-base font-semibold text-text">{children}</h3>
  ),
  p: ({ children }) => <p className="mb-3 leading-7 text-text/90">{children}</p>,
  ul: ({ children }) => <ul className="mb-4 list-disc space-y-1.5 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="mb-4 list-decimal space-y-1.5 pl-5">{children}</ol>,
  li: ({ children }) => <li className="leading-7">{children}</li>,
  blockquote: ({ children }) => {
    const text = blockquoteFromChildren(children)
    const callout = isObsidianCallout(text.startsWith('>') ? text : `> ${text}`)
    if (callout) {
      const body = text
        .split('\n')
        .slice(1)
        .map((line) => line.replace(/^>\s?/, ''))
        .join('\n')
        .trim()
      return (
        <CalloutPanel kind={callout.kind}>
          {callout.title && <p className="font-medium">{callout.title}</p>}
          {body ? <p>{body}</p> : null}
          {!body && !callout.title ? children : null}
        </CalloutPanel>
      )
    }
    return (
      <blockquote className="mb-4 border-l-2 border-cyan/50 pl-4 italic text-muted">{children}</blockquote>
    )
  },
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noreferrer" className="text-cyan underline-offset-2 hover:underline">
      {children}
    </a>
  ),
  code: ({ className, children }) => {
    const inline = !className
    if (inline) {
      return (
        <code className="rounded bg-black/40 px-1 py-0.5 font-mono text-[0.85em] text-cyan">{children}</code>
      )
    }
    return (
      <code className="block overflow-x-auto rounded-lg bg-black/40 p-3 font-mono text-xs leading-5">
        {children}
      </code>
    )
  },
  pre: ({ children }) => <pre className="mb-4 overflow-x-auto rounded-lg bg-black/40">{children}</pre>,
  table: ({ children }) => (
    <div className="mb-4 overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border border-border/70 bg-white/[0.04] px-3 py-2 font-medium">{children}</th>
  ),
  td: ({ children }) => <td className="border border-border/70 px-3 py-2">{children}</td>,
  hr: () => <hr className="my-6 border-border/70" />,
  strong: ({ children }) => <strong className="font-semibold text-text">{children}</strong>,
  em: ({ children }) => <em className="italic text-muted">{children}</em>,
}

function FrontmatterBar({ title, tags, updated }: { title?: string; tags?: string[]; updated?: string }) {
  if (!title && !tags?.length && !updated) return null
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 border-b border-border/60 pb-3 text-xs text-muted">
      {title && <span className="font-medium text-text/80">{title}</span>}
      {updated && <span>Updated {updated}</span>}
      {tags?.slice(0, 6).map((tag) => (
        <span key={tag} className="rounded-full border border-border/70 px-2 py-0.5">
          {tag}
        </span>
      ))}
    </div>
  )
}

export function MarkdownPreview({
  content,
  className = '',
}: {
  content: string
  className?: string
}) {
  const { frontmatter, body } = preprocessMarkdown(content)
  return (
    <div className={`rounded-lg border border-border bg-black/30 px-5 py-4 ${className}`}>
      {frontmatter && (
        <FrontmatterBar
          title={frontmatter.title}
          tags={frontmatter.tags}
          updated={frontmatter.updated}
        />
      )}
      <div className="max-w-none text-sm">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {body}
        </ReactMarkdown>
      </div>
    </div>
  )
}
