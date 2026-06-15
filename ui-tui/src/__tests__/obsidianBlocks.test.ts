import { describe, expect, it } from 'vitest'

import { buildBlocks } from '../components/obsidianView.js'

const DOC = `# Title

First paragraph line one
line two of the same paragraph.

## Section

- bullet a
- bullet b

\`\`\`ts
const x = 1
\`\`\`
`

describe('buildBlocks (reading-cursor line model)', () => {
  it('splits into heading / paragraph / list / fenced blocks with 1-based line ranges', () => {
    const blocks = buildBlocks(DOC)

    const heading = blocks.find(b => b.title === 'Title')
    expect(heading).toMatchObject({ kind: 'heading', level: 1, start: 1, end: 1 })

    // The two-line paragraph is one block spanning its source lines.
    const para = blocks.find(b => b.text.startsWith('First paragraph'))
    expect(para).toMatchObject({ kind: 'block', start: 3, end: 4 })

    // The bullet run groups into a single block.
    const list = blocks.find(b => b.text.includes('bullet a'))
    expect(list?.text).toContain('bullet b')

    // The fenced code block is one unit including its fences.
    const fence = blocks.find(b => b.text.includes('const x = 1'))
    expect(fence?.text.startsWith('```')).toBe(true)
    expect(fence?.end).toBeGreaterThan(fence!.start)
  })

  it('marks blank lines as non-selectable spacers', () => {
    const blocks = buildBlocks(DOC)
    expect(blocks.some(b => b.kind === 'blank')).toBe(true)
  })

  it('reports two heading blocks for the two sections', () => {
    const headings = buildBlocks(DOC).filter(b => b.title)
    expect(headings.map(h => h.title)).toEqual(['Title', 'Section'])
  })
})
