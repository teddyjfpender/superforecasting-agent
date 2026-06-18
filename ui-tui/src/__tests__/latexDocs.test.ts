import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterAll, describe, expect, it } from 'vitest'

import { latexDocsDir, listTexFiles, readTexFile } from '../lib/latexDocs.js'

const tmp = mkdtempSync(join(tmpdir(), 'latex-'))

afterAll(() => rmSync(tmp, { force: true, recursive: true }))

describe('latexDocsDir', () => {
  it('honours LATEX_DOCS_PATH / OVERLEAF_DIR overrides', () => {
    expect(latexDocsDir({ LATEX_DOCS_PATH: '/p' })).toBe('/p')
    expect(latexDocsDir({ OVERLEAF_DIR: '/o' })).toBe('/o')
  })
})

describe('listTexFiles / readTexFile', () => {
  it('lists .tex recursively (skipping dotfiles/node_modules) and reads them', () => {
    writeFileSync(join(tmp, 'main.tex'), '\\section{Hi}')
    writeFileSync(join(tmp, 'notes.md'), 'not tex')
    mkdirSync(join(tmp, 'sub'))
    writeFileSync(join(tmp, 'sub', 'chapter.tex'), 'x')
    mkdirSync(join(tmp, 'node_modules'))
    writeFileSync(join(tmp, 'node_modules', 'pkg.tex'), 'ignored')

    const rels = listTexFiles(tmp).map(f => f.rel).sort()
    expect(rels).toEqual(['main.tex', join('sub', 'chapter.tex')])

    expect(readTexFile(tmp, 'main.tex')).toBe('\\section{Hi}')
  })

  it('refuses path traversal', () => {
    expect(readTexFile(tmp, '../secret')).toBe('')
  })
})
