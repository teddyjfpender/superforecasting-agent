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
  it('emits one block per source line (no skipping) but groups fenced code', () => {
    const blocks = buildBlocks(DOC)

    const heading = blocks.find(b => b.title === 'Title')
    expect(heading).toMatchObject({ kind: 'heading', level: 1, start: 1, end: 1 })

    // Each prose line is its own block so the cursor moves line-by-line.
    const l3 = blocks.find(b => b.text === 'First paragraph line one')
    const l4 = blocks.find(b => b.text === 'line two of the same paragraph.')
    expect(l3).toMatchObject({ start: 3, end: 3 })
    expect(l4).toMatchObject({ start: 4, end: 4 })

    // Each bullet is its own line/block too.
    const a = blocks.find(b => b.text === '- bullet a')
    const b = blocks.find(b => b.text === '- bullet b')
    expect(a?.start).toBe(8)
    expect(b?.start).toBe(9)

    // The fenced code block stays one unit including its fences.
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
