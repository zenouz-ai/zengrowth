/** Parse Obsidian-style markdown for dashboard preview. */

export type ObsidianCalloutKind = 'tip' | 'warning' | 'note' | 'info'

export interface ParsedFrontmatter {
  title?: string
  tags?: string[]
  updated?: string
  raw: Record<string, string | string[]>
}

export interface PreprocessedMarkdown {
  frontmatter: ParsedFrontmatter | null
  body: string
}

const FRONTMATTER_RE = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/
const CALLOUT_LINE_RE = /^>\s*\[!(\w+)\]\s*(.*)$/

function parseSimpleYaml(block: string): Record<string, string | string[]> {
  const out: Record<string, string | string[]> = {}
  let currentKey: string | null = null
  for (const line of block.split('\n')) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    if (trimmed.startsWith('- ') && currentKey) {
      const item = trimmed.slice(2).replace(/^["']|["']$/g, '')
      const existing = out[currentKey]
      if (Array.isArray(existing)) {
        existing.push(item)
      } else {
        out[currentKey] = [item]
      }
      continue
    }
    const match = trimmed.match(/^([\w-]+):\s*(.*)$/)
    if (!match) continue
    currentKey = match[1]
    const value = match[2].trim()
    if (value.startsWith('[') && value.endsWith(']')) {
      out[currentKey] = value
        .slice(1, -1)
        .split(',')
        .map((part) => part.trim().replace(/^["']|["']$/g, ''))
        .filter(Boolean)
    } else {
      out[currentKey] = value.replace(/^["']|["']$/g, '')
    }
  }
  return out
}

export function parseFrontmatter(content: string): PreprocessedMarkdown {
  const match = content.match(FRONTMATTER_RE)
  if (!match) return { frontmatter: null, body: content }
  const raw = parseSimpleYaml(match[1])
  const tags = raw.tags
  const frontmatter: ParsedFrontmatter = {
    title: typeof raw.title === 'string' ? raw.title : undefined,
    tags: Array.isArray(tags) ? tags : typeof tags === 'string' ? [tags] : undefined,
    updated: typeof raw.updated === 'string' ? raw.updated : undefined,
    raw,
  }
  return { frontmatter, body: content.slice(match[0].length) }
}

/** Normalize Obsidian callouts so blockquote renderer can style them. */
export function normalizeObsidianCallouts(body: string): string {
  const lines = body.split('\n')
  const out: string[] = []
  let i = 0
  while (i < lines.length) {
    const callout = lines[i].match(CALLOUT_LINE_RE)
    if (!callout) {
      out.push(lines[i])
      i += 1
      continue
    }
    const kind = callout[1].toLowerCase()
    const firstLine = callout[2].trim()
    out.push(`> [!${kind}] ${firstLine}`)
    i += 1
    while (i < lines.length && (lines[i].startsWith('>') || lines[i].trim() === '')) {
      if (lines[i].trim() === '') {
        out.push('')
        i += 1
        break
      }
      const cont = lines[i].replace(/^>\s?/, '').trim()
      if (cont.startsWith('[!')) {
        break
      }
      out.push(`> ${cont}`)
      i += 1
    }
  }
  return out.join('\n')
}

export function preprocessMarkdown(content: string): PreprocessedMarkdown {
  const parsed = parseFrontmatter(content)
  return {
    frontmatter: parsed.frontmatter,
    body: normalizeObsidianCallouts(parsed.body.trimStart()),
  }
}

export function calloutTone(kind: string): ObsidianCalloutKind {
  if (kind === 'tip' || kind === 'warning' || kind === 'note' || kind === 'info') {
    return kind
  }
  return 'note'
}

export function isObsidianCallout(text: string): { kind: ObsidianCalloutKind; title: string } | null {
  const first = text.split('\n')[0]?.trim() ?? ''
  const match = first.match(/^>\s*\[!(\w+)\]\s*(.*)$/) ?? first.match(/^\[!(\w+)\]\s*(.*)$/)
  if (!match) return null
  return { kind: calloutTone(match[1]), title: match[2].trim() }
}
