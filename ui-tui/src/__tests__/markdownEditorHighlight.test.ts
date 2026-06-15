import { describe, expect, it } from 'vitest'

import { highlightMarkdownLine } from '../lib/markdownEditorHighlight.js'
import { DEFAULT_THEME as t } from '../theme.js'

// Reassemble the segment text to prove highlighting never drops/duplicates
// characters (the editor must stay faithful to the source).
const text = (line: string) => highlightMarkdownLine(line, t).map(s => s.text).join('')

describe('highlightMarkdownLine', () => {
  it('is lossless — segments rejoin to the exact source line', () => {
    for (const line of [
      '# Heading',
      '## A **bold** and _em_ mix',
      '- a [[Wikilink]] in a bullet',
      '> a quote with `code`',
      'plain text $E=mc^2$ end',
      '```ts',
      ''
    ]) {
      expect(text(line)).toBe(line)
    }
  })

  it('styles a heading: dim marker + bold accent title', () => {
    const segs = highlightMarkdownLine('## Methods', t)
    expect(segs[0]!.text).toBe('## ')
    expect(segs[0]!.color).toBe(t.color.muted)
    expect(segs[1]).toMatchObject({ bold: true, color: t.color.accent, text: 'Methods' })
  })

  it('dims the markers around a wikilink and links the target', () => {
    const segs = highlightMarkdownLine('see [[Getting Started]] now', t)
    const wikiOpen = segs.find(s => s.text === '[[')
    const target = segs.find(s => s.text === 'Getting Started')
    expect(wikiOpen).toMatchObject({ dim: true })
    expect(target).toMatchObject({ color: t.color.primary, underline: true })
  })

  it('treats a list marker as syntax and styles the content', () => {
    const segs = highlightMarkdownLine('- a **b**', t)
    expect(segs[0]).toMatchObject({ color: t.color.accent, text: '- ' })
    expect(segs.some(s => s.bold && s.text === 'b')).toBe(true)
  })
})
