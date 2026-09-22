import type { InternalMaterialType } from './types'

const TITLE_RULES: [InternalMaterialType, string[]][] = [
  ['rejection_reflection', ['rejection reflection', 'rejection feedback', 'what the feedback']],
  ['culture_comparison', ['culture comparison', 'culture vs', 'culture versus', 'culture notes']],
  ['session_prep', ['claude code', 'practice brief', 'session prompt', 'runnable prompt', 'session prep', 'take-home']],
  ['journey_summary', ['journey summary']],
]

const SECTION_RULES: [InternalMaterialType, string[]][] = [
  ['rejection_reflection', ['gaps versus the bar', 'skills and knowledge to deepen']],
  ['journey_summary', ['reusable learnings', 'timeline of rounds']],
  ['culture_comparison', ['headline comparison table', 'target company culture']],
  ['session_prep', ['runnable prompt', 'session goal']],
]

function headingsOf(content: string): Set<string> {
  const found = new Set<string>()
  for (const line of content.split('\n')) {
    const match = /^##\s+(.+?)\s*$/.exec(line)
    if (match) found.add(match[1].trim().toLowerCase())
  }
  return found
}

/** Best-effort import type from title + markdown. Hint only — the API may also
 * reclassify leftover briefing/tech-pack defaults. */
export function suggestInternalMaterialType(
  title: string,
  content = '',
): InternalMaterialType | null {
  const titleBlob = title.toLowerCase()
  for (const [materialType, needles] of TITLE_RULES) {
    if (needles.some((needle) => titleBlob.includes(needle))) return materialType
  }
  const headings = headingsOf(content)
  for (const [materialType, required] of SECTION_RULES) {
    if (required.every((heading) => headings.has(heading))) return materialType
  }
  return null
}
