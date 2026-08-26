import { knowledgeSourceFileUrl } from '../lib/api'
import { useAsyncData } from '../hooks/useAsyncData'
import { MarkdownPreview } from './MarkdownPreview'
import { Skeleton } from './Skeleton'

const MD_EXT = /\.md$/i
const TEX_EXT = /\.tex$/i

async function fetchSourceText(url: string): Promise<string> {
  const response = await fetch(url, { credentials: 'include' })
  if (!response.ok) throw new Error(`Failed to load file (${response.status})`)
  return response.text()
}

export function SourceFilePreview({ sourceId, filename }: { sourceId: number; filename: string }) {
  const isMarkdown = MD_EXT.test(filename)
  const isTex = TEX_EXT.test(filename)
  const kind = isMarkdown || isTex ? 'original' : 'processed'
  const url = knowledgeSourceFileUrl(sourceId, kind)

  const text = useAsyncData(() => fetchSourceText(url), [sourceId, kind])

  if (text.loading && !text.data) {
    return <Skeleton className="h-72" />
  }
  if (text.error) {
    return (
      <p className="rounded-lg border border-loss/40 bg-loss/5 px-3 py-2 text-xs text-loss">
        Could not load file preview.
      </p>
    )
  }

  const content = text.data ?? ''

  if (isMarkdown) {
    return <MarkdownPreview content={content} className="max-h-72 overflow-y-auto" />
  }

  return (
    <pre className="max-h-72 overflow-auto rounded-lg border border-border bg-black/30 p-3 font-mono text-xs leading-5 text-text/90">
      {content}
    </pre>
  )
}
