import { type Dirent, existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { basename, dirname, join, relative } from 'node:path'

import { forecastHomeDir } from './forecastHome.js'

// The single docs workspace: ~/.superforecasting-agent/docs — one directory we
// initialise as a git repo so everything (LaTeX, and eventually the Markdown
// vault) lives under one remote / GitHub account. Override with LATEX_DOCS_PATH
// or OVERLEAF_DIR. The LaTeX view browses .tex files anywhere under it.

export const docsDir = (env: NodeJS.ProcessEnv = process.env, _home = homedir()): string => {
  const override = env.LATEX_DOCS_PATH?.trim() || env.OVERLEAF_DIR?.trim()

  return override || join(forecastHomeDir(), 'docs')
}

// Starter document for a brand-new .tex file.
export const newTexTemplate = (title: string): string =>
  `\\documentclass{article}\n\\title{${title}}\n\\author{}\n\\date{\\today}\n\n\\begin{document}\n\\maketitle\n\n\\section{Introduction}\n\n\\end{document}\n`

// Create a new .tex file (folders in the path are created). rel may be
// "paper" or "papers/intro.tex"; ".tex" is appended if missing.
export const createTexFile = (dir: string, rel: string): { error: null | string; rel: string } => {
  let path = rel.trim()

  if (!path) {
    return { error: 'name required', rel: '' }
  }

  if (path.includes('..')) {
    return { error: 'invalid path', rel: '' }
  }

  if (!/\.tex$/i.test(path)) {
    path += '.tex'
  }

  const full = join(dir, path)

  try {
    mkdirSync(dirname(full), { recursive: true })

    if (existsSync(full)) {
      return { error: 'already exists', rel: path }
    }

    const title = basename(path)
      .replace(/\.tex$/i, '')
      .replace(/[-_]+/g, ' ')

    writeFileSync(full, newTexTemplate(title))

    return { error: null, rel: path }
  } catch (e) {
    return { error: e instanceof Error ? e.message : 'write failed', rel: '' }
  }
}

export interface TexFile {
  mtime: number
  rel: string
  size: number
}

// Recursively list .tex files (newest first), skipping dotfiles + node_modules.
export const listTexFiles = (dir: string, max = 500): TexFile[] => {
  const out: TexFile[] = []

  const walk = (d: string): void => {
    if (out.length >= max) {
      return
    }

    let entries: Dirent[]

    try {
      entries = readdirSync(d, { encoding: 'utf8', withFileTypes: true })
    } catch {
      return
    }

    for (const e of entries) {
      if (e.name.startsWith('.') || e.name === 'node_modules') {
        continue
      }

      const full = join(d, e.name)

      if (e.isDirectory()) {
        walk(full)
      } else if (e.isFile() && e.name.toLowerCase().endsWith('.tex')) {
        try {
          const s = statSync(full)
          out.push({ mtime: s.mtimeMs, rel: relative(dir, full), size: s.size })
        } catch {
          /* skip unreadable */
        }
      }
    }
  }

  walk(dir)
  out.sort((a, b) => b.mtime - a.mtime || a.rel.localeCompare(b.rel))

  return out
}

export const readTexFile = (dir: string, rel: string): string => {
  if (rel.includes('..')) {
    return '' // no traversal out of the docs dir
  }

  try {
    return readFileSync(join(dir, rel), 'utf8')
  } catch {
    return ''
  }
}

export const ensureLatexDir = (dir: string): boolean => {
  try {
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true })
    }

    return true
  } catch {
    return false
  }
}

export const latexDirExists = (dir: string): boolean => {
  try {
    return existsSync(dir)
  } catch {
    return false
  }
}
