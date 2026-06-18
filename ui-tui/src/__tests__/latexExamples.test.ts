import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterAll, describe, expect, it } from 'vitest'

import { listTexFiles, readTexFile } from '../lib/latexDocs.js'
import { seedLatexExamples } from '../lib/latexExamples.js'
import { renderLatex } from '../lib/latexRender.js'

const tmp = mkdtempSync(join(tmpdir(), 'tex-ex-'))

afterAll(() => rmSync(tmp, { force: true, recursive: true }))

describe('seedLatexExamples', () => {
  it('writes example docs across examples/ and templates/', () => {
    const created = seedLatexExamples(tmp)
    expect(created).toEqual([
      'examples/symbols.tex',
      'examples/math.tex',
      'examples/article.tex',
      'templates/report.tex',
      'templates/letter.tex'
    ])

    for (const rel of created) {
      expect(existsSync(join(tmp, rel))).toBe(true)
    }

    // and they're discoverable by the docs lister
    expect(listTexFiles(tmp)).toHaveLength(5)
  })

  it('is one-time (skips once examples/ exists)', () => {
    expect(seedLatexExamples(tmp)).toEqual([])
  })

  it('seeds COMPILABLE-shaped docs the TUI renderer can read', () => {
    const symbols = renderLatex(readTexFile(tmp, 'examples/symbols.tex'))
    // title + section headings render, and symbols map to Unicode
    expect(symbols.some(b => b.kind === 'heading' && b.text === 'Greek letters')).toBe(true)
    expect(symbols.some(b => b.text.includes('α') || b.text.includes('∑'))).toBe(true)
  })
})
