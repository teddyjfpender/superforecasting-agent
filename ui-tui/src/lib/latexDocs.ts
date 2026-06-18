import { cpSync, type Dirent, existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
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

// Subdirectories of the workspace: the Markdown (Obsidian) vault and LaTeX.
export const vaultDir = (env: NodeJS.ProcessEnv = process.env): string => join(docsDir(env), 'vault')
export const latexSubdir = (env: NodeJS.ProcessEnv = process.env): string => join(docsDir(env), 'latex')

// signal-cli era's default Obsidian vault location, before the unified docs/.
export const legacyVaultDir = (home = homedir()): string => join(home, 'Documents', 'Obsidian Vault')

const visibleEntries = (dir: string): Dirent[] => {
  try {
    return readdirSync(dir, { encoding: 'utf8', withFileTypes: true }).filter(e => !e.name.startsWith('.'))
  } catch {
    return []
  }
}

// One-time migration: if the unified vault is empty but the legacy default vault
// has notes, copy them in (never overwrites a populated vault). Returns the
// number of top-level items copied. This recovers notes orphaned when the vault
// path was relocated into docs/.
export const migrateLegacyVault = (newVaultDir: string, home = homedir()): number => {
  try {
    if (visibleEntries(newVaultDir).length > 0) {
      return 0 // already has content — don't touch it
    }

    const legacy = legacyVaultDir(home)

    if (!existsSync(legacy) || legacy === newVaultDir) {
      return 0
    }

    const items = visibleEntries(legacy)

    if (items.length === 0) {
      return 0
    }

    mkdirSync(newVaultDir, { recursive: true })
    let copied = 0

    for (const e of items) {
      cpSync(join(legacy, e.name), join(newVaultDir, e.name), { errorOnExist: false, recursive: true })
      copied += 1
    }

    return copied
  } catch {
    return 0
  }
}

export const docsRootExists = (env: NodeJS.ProcessEnv = process.env): boolean => {
  try {
    return existsSync(docsDir(env))
  } catch {
    return false
  }
}

const README = `# Docs workspace

One git repository for everything, synced to a single remote.

- \`vault/\`  — Markdown notes (the Obsidian vault).
- \`latex/\`  — LaTeX documents (.tex), Overleaf/GitHub-synced.

Managed by the Outrider TUI's Docs view.
`

const GITIGNORE = `# LaTeX build artifacts
*.aux
*.log
*.out
*.toc
*.synctex.gz
*.fdb_latexmk
*.fls
*.bbl
*.blg
.DS_Store
`

// Create the unified workspace: docs/ + docs/vault/ + docs/latex/, plus a
// README and .gitignore so the first commit isn't empty. Idempotent.
export const ensureWorkspaceDirs = (
  env: NodeJS.ProcessEnv = process.env
): { latex: string; root: string; vault: string } => {
  const root = docsDir(env)
  const vault = vaultDir(env)
  const latex = latexSubdir(env)

  for (const d of [root, vault, latex]) {
    if (!existsSync(d)) {
      mkdirSync(d, { recursive: true })
    }
  }

  const readme = join(root, 'README.md')

  if (!existsSync(readme)) {
    writeFileSync(readme, README)
  }

  const gitignore = join(root, '.gitignore')

  if (!existsSync(gitignore)) {
    writeFileSync(gitignore, GITIGNORE)
  }

  return { latex, root, vault }
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

export const writeTexFile = (dir: string, rel: string, content: string): { error: null | string } => {
  if (rel.includes('..')) {
    return { error: 'invalid path' }
  }

  try {
    writeFileSync(join(dir, rel), content)

    return { error: null }
  } catch (e) {
    return { error: e instanceof Error ? e.message : 'write failed' }
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
