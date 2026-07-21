import { describe, expect, it } from 'vitest'
import { parseFrontmatter, preprocessMarkdown } from '../lib/markdownPreprocess'

describe('markdownPreprocess', () => {
  it('parses YAML frontmatter and strips it from body', () => {
    const raw = `---
title: "Intact Research"
tags: [interview-prep, intact]
updated: 2026-05-24
---

# Intact Research

## Who They Are
Body text.`
    const { frontmatter, body } = parseFrontmatter(raw)
    expect(frontmatter?.title).toBe('Intact Research')
    expect(frontmatter?.tags).toEqual(['interview-prep', 'intact'])
    expect(frontmatter?.updated).toBe('2026-05-24')
    expect(body.trim().startsWith('# Intact Research')).toBe(true)
    expect(body).not.toContain('---\ntitle:')
  })

  it('preserves Obsidian callouts in preprocessed body', () => {
    const { body } = preprocessMarkdown('> [!tip] Key takeaway\n\n## Section\nText.')
    expect(body).toContain('[!tip]')
  })
})
