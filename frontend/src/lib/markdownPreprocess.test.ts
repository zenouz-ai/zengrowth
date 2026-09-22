import { describe, expect, it } from 'vitest'
import { parseFrontmatter, preprocessMarkdown } from '../lib/markdownPreprocess'

describe('markdownPreprocess', () => {
  it('parses YAML frontmatter and strips it from body', () => {
    const raw = `---
title: "Northwind Research"
tags: [interview-prep, northwind]
updated: 2026-05-24
---

# Northwind Research

## Who They Are
Body text.`
    const { frontmatter, body } = parseFrontmatter(raw)
    expect(frontmatter?.title).toBe('Northwind Research')
    expect(frontmatter?.tags).toEqual(['interview-prep', 'northwind'])
    expect(frontmatter?.updated).toBe('2026-05-24')
    expect(body.trim().startsWith('# Northwind Research')).toBe(true)
    expect(body).not.toContain('---\ntitle:')
  })

  it('preserves Obsidian callouts in preprocessed body', () => {
    const { body } = preprocessMarkdown('> [!tip] Key takeaway\n\n## Section\nText.')
    expect(body).toContain('[!tip]')
  })
})
