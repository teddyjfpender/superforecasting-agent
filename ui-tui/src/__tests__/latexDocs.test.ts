import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterAll, describe, expect, it } from 'vitest'

import { createTexFile, docsDir, ensureWorkspaceDirs, listTexFiles, readTexFile } from '../lib/latexDocs.js'

const dirs: string[] = []

const freshDir = () => {
  const d = mkdtempSync(join(tmpdir(), 'latex-'))
  dirs.push(d)

  return d
}

afterAll(() => dirs.forEach(d => rmSync(d, { force: true, recursive: true })))

describe('docsDir', () => {
  it('honours LATEX_DOCS_PATH / OVERLEAF_DIR overrides, else <home>/docs', () => {
    expect(docsDir({ LATEX_DOCS_PATH: '/p' })).toBe('/p')
    expect(docsDir({ OVERLEAF_DIR: '/o' })).toBe('/o')
    const prev = process.env.SUPERFORECASTING_AGENT_HOME
    process.env.SUPERFORECASTING_AGENT_HOME = '/h'
    expect(docsDir({})).toBe(join('/h', 'docs'))

    if (prev === undefined) {
      delete process.env.SUPERFORECASTING_AGENT_HOME
    } else {
      process.env.SUPERFORECASTING_AGENT_HOME = prev
    }
  })
})

describe('listTexFiles / readTexFile', () => {
  it('lists .tex recursively (skipping dotfiles/node_modules) and reads them', () => {
    const tmp = freshDir()
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
    expect(readTexFile(freshDir(), '../secret')).toBe('')
  })
})

describe('createTexFile', () => {
  it('creates a .tex (adding the extension + folders) with a starter template', () => {
    const tmp = freshDir()
    const r = createTexFile(tmp, 'papers/intro')
    expect(r.error).toBeNull()
    expect(r.rel).toBe(join('papers', 'intro.tex'))
    expect(readTexFile(tmp, r.rel)).toContain('\\documentclass{article}')
  })

  it('refuses duplicates and path traversal', () => {
    const tmp = freshDir()
    createTexFile(tmp, 'dup.tex')
    expect(createTexFile(tmp, 'dup.tex').error).toBe('already exists')
    expect(createTexFile(tmp, '../escape.tex').error).toBe('invalid path')
  })
})

describe('ensureWorkspaceDirs', () => {
  it('creates docs/vault/latex + README + .gitignore (idempotently)', async () => {
    const { existsSync } = await import('node:fs')
    const root = freshDir() // acts as the docs root via the override below
    const env = { LATEX_DOCS_PATH: root }
    const dirs = ensureWorkspaceDirs(env)
    expect(dirs.root).toBe(root)
    expect(existsSync(join(root, 'vault'))).toBe(true)
    expect(existsSync(join(root, 'latex'))).toBe(true)
    expect(existsSync(join(root, 'README.md'))).toBe(true)
    expect(existsSync(join(root, '.gitignore'))).toBe(true)
    expect(() => ensureWorkspaceDirs(env)).not.toThrow() // idempotent
  })
})

describe('migrateLegacyVault', () => {
  it('copies legacy vault notes into an empty docs vault, but never overwrites', async () => {
    const { mkdirSync, writeFileSync, existsSync } = await import('node:fs')
    const fakeHome = freshDir()
    const legacy = join(fakeHome, 'Documents', 'Obsidian Vault')
    mkdirSync(legacy, { recursive: true })
    writeFileSync(join(legacy, 'note.md'), '# hi')
    mkdirSync(join(legacy, 'sub'), { recursive: true })
    writeFileSync(join(legacy, 'sub', 'b.md'), 'x')

    const newVault = freshDir()
    const { migrateLegacyVault } = await import('../lib/latexDocs.js')
    expect(migrateLegacyVault(newVault, fakeHome)).toBe(2)
    expect(existsSync(join(newVault, 'note.md'))).toBe(true)
    expect(existsSync(join(newVault, 'sub', 'b.md'))).toBe(true)

    // a populated vault is left alone
    expect(migrateLegacyVault(newVault, fakeHome)).toBe(0)
  })
})
