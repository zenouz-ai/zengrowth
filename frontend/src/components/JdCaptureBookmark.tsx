import { useEffect, useRef, useState } from 'react'
import { buildBookmarklet } from '../lib/jdCapture'

export function JdCaptureBookmark() {
  const href = buildBookmarklet(window.location.origin)
  const [copied, setCopied] = useState(false)
  const linkRef = useRef<HTMLAnchorElement>(null)

  useEffect(() => {
    /* React 19 strips javascript: from JSX href; set it on the DOM so the
     * link can still be dragged onto the bookmarks bar. */
    linkRef.current?.setAttribute('href', href)
  }, [href])

  return (
    <div className="rounded-lg border border-border/70 bg-white/[0.02] p-3">
      <p className="text-sm text-text">Add this JD</p>
      <p className="mt-1 text-xs text-muted">
        Drag the link to your bookmarks bar. On a posting, tap it (select the JD first for a
        cleaner extract). The URL is stored only — ZenGrowth never fetches the page. On iPhone:
        copy, add a Safari favorite, paste as the URL.
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <a
          ref={linkRef}
          href="/add"
          onClick={(e) => e.preventDefault()}
          className="rounded-lg border border-cyan px-3 py-2 text-sm text-cyan"
        >
          Add this JD
        </a>
        <button
          type="button"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(href)
              setCopied(true)
            } catch {
              setCopied(false)
            }
          }}
          className="rounded-lg border border-border px-3 py-2 text-xs text-muted hover:text-text"
        >
          {copied ? 'Copied' : 'Copy bookmarklet'}
        </button>
      </div>
    </div>
  )
}
