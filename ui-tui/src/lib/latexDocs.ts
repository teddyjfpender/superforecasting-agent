import { type Dirent, existsSync, mkdirSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { join, relative } from 'node:path'

import { forecastHomeDir } from './forecastHome.js'

// Local LaTeX workspace: a directory of .tex files (often a git clone of an
// Overleaf or GitHub project). Default ~/.superforecasting-agent/latex; override
// with LATEX_DOCS_PATH or OVERLEAF_DIR.

export const latexDocsDir = (env: NodeJS.ProcessEnv = process.env, _home = homedir()): string => {
  const override = env.LATEX_DOCS_PATH?.trim() || env.OVERLEAF_DIR?.trim()

  return override || join(forecastHomeDir(), 'latex')
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
