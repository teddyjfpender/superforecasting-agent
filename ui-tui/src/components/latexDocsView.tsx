import { Box, Text, useInput, useStdout } from '@hermes/ink'
import { useStore } from '@nanostores/react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { $globalModal, openHelpOverlay } from '../app/overlayStore.js'
import {
  commandExists,
  ghAuthStatus,
  ghCreateRepo,
  gitClone,
  gitCommitPush,
  gitInit,
  gitPull,
  gitSetRemote,
  type GitStatus,
  gitStatus,
  isGitRepo,
  overleaf
} from '../lib/docsCli.js'
import { type FieldSpec, filterRanked } from '../lib/fuzzyRank.js'
import { statusGlyph } from '../lib/icons.js'
import { createTexFile, docsDir, ensureLatexDir, latexSubdir, listTexFiles, readTexFile, type TexFile, writeTexFile } from '../lib/latexDocs.js'
import { seedLatexExamples } from '../lib/latexExamples.js'
import { type LatexBlock, renderLatex } from '../lib/latexRender.js'
import { sortIndicator, sortRows, useTableSort } from '../lib/tableSort.js'
import { semantics } from '../lib/visualSemantics.js'
import type { Theme } from '../theme.js'

import { DocsHeader, DocsKindTabs, docAge, sizeChip, titlePath } from './docsShell.js'
import { type FooterChip, FooterChips } from './footerChips.js'

// LaTeX side of Docs: browse local .tex files, render them readably, and sync
// the directory with git (commit/push/pull — Overleaf projects are git-backed)
// or Overleaf's olcli. Two panes split by a vertical rule, like News/Markets.

const truncate = (value: string, max: number): string =>
  value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value

// Only the relative path is searchable on a TexFile.
const LATEX_SEARCH_FIELDS: FieldSpec<TexFile>[] = [{ get: f => f.rel, weight: 1 }]

// Sortable columns (o cycles, O toggles) — mirrors the Desk/Markets sort verbs.
// Referentially stable so useTableSort's callbacks stay stable across renders.
const LATEX_SORT_KEYS = ['name', 'modified'] as const
const latexSortValue = (f: TexFile, key: string): null | number | string =>
  key === 'modified' ? f.mtime : f.rel.toLowerCase()

interface LatexDocsViewProps {
  docKind?: 'latex' | 'markdown'
  onClose: () => void
  onDraft?: (command: string) => void
  onSelectKind?: (kind: 'latex' | 'markdown') => void
  t: Theme
}

export function LatexDocsView({ docKind, onClose, onDraft, onSelectKind, t }: LatexDocsViewProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24
  const sem = semantics(t)
  // Go inert while the Ctrl+K palette / `?` cheat-sheet stacks above the view.
  const globalModal = useStore($globalModal)

  const dirRef = useRef(docsDir())
  const dir = dirRef.current

  const [files, setFiles] = useState<TexFile[]>([])
  const sort = useTableSort(LATEX_SORT_KEYS)
  const [sel, setSel] = useState(0)
  const [focus, setFocus] = useState<'list' | 'reader'>('list')
  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [content, setContent] = useState('')
  const [scroll, setScroll] = useState(0)
  const [git, setGit] = useState<GitStatus | null>(null)
  const [repo, setRepo] = useState(false)
  const [tools, setTools] = useState({ gh: false, git: false, olcli: false })
  const [busy, setBusy] = useState(false)
  const [flash, setFlash] = useState('')
  const [tick, setTick] = useState(0)
  // Inline prompt for onboarding actions: name a new doc, or paste a remote URL.
  const [prompt, setPrompt] = useState<null | { mode: 'github' | 'newdoc' | 'remote'; value: string }>(null)
  // Edit mode: a plain-text editor over the .tex source.
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState('')
  const [editCursor, setEditCursor] = useState(0)
  const [dirty, setDirty] = useState(false)
  const aliveRef = useRef(true)

  useEffect(() => {
    aliveRef.current = true
    const id = setInterval(() => setTick(v => v + 1), 600)

    return () => {
      aliveRef.current = false
      clearInterval(id)
    }
  }, [])

  const refreshGit = async () => {
    const isRepo = await isGitRepo(dir)

    if (!aliveRef.current) {
      return
    }

    setRepo(isRepo)
    setGit(isRepo ? await gitStatus(dir) : null)
  }

  const reload = () => {
    ensureLatexDir(dir)
    setFiles(listTexFiles(dir))
  }

  useEffect(() => {
    seedLatexExamples(latexSubdir()) // one-time: populate examples/ + templates/
    reload()
    setTools({ gh: commandExists('gh'), git: commandExists('git'), olcli: commandExists('olcli') })
    void refreshGit()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Ranked fuzzy filter over the file paths (same engine as news/markets/desk):
  // best matches float up, non-matches drop out, empty query shows all. When an
  // explicit sort is chosen (o/O) it takes over the ordering; otherwise the rank
  // order stands (relevance while filtering, freshest-first when unfiltered).
  const ranked = useMemo(() => filterRanked(files, query, LATEX_SEARCH_FIELDS), [files, query])
  const filtered = useMemo(
    () => (sort.state.key ? sortRows(ranked, sort.state.key, sort.state.dir, latexSortValue) : ranked),
    [ranked, sort.state.key, sort.state.dir]
  )

  const clampedSel = Math.min(sel, Math.max(0, filtered.length - 1))
  const activeFile = filtered[clampedSel]

  // Keep the SAME document selected across a re-sort (track by rel-path, not
  // index) — so sorting the list never swaps the doc out of the reader pane. A
  // sort action stashes the active file's rel; once the re-sorted order lands, the
  // cursor jumps to where that file now sits. Only sort arms this, so a filter
  // change / reload leaves it null and the index-based cursor logic is untouched.
  const pendingReselect = useRef<null | string>(null)
  useEffect(() => {
    const rel = pendingReselect.current

    if (rel == null) {
      return
    }

    pendingReselect.current = null
    const idx = filtered.findIndex(f => f.rel === rel)

    if (idx >= 0) {
      setSel(idx)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtered])

  const armReselect = () => {
    pendingReselect.current = activeFile?.rel ?? null
  }

  // Read the selected file's source.
  useEffect(() => {
    setContent(activeFile ? readTexFile(dir, activeFile.rel) : '')
    setScroll(0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeFile?.rel])

  const blocks = useMemo<LatexBlock[]>(() => (content ? renderLatex(content) : []), [content])

  const runSync = (label: string, op: () => Promise<{ error: null | string }>) => {
    if (busy) {
      return
    }

    setBusy(true)
    setFlash(`${label}…`)

    void (async () => {
      const { error } = await op()

      if (!aliveRef.current) {
        return
      }

      setBusy(false)
      setFlash(error ? `${label} failed: ${truncate(error, 60)}` : `${label} done`)
      reload() // a clone/pull may have added or changed files
      await refreshGit()
    })()
  }

  // Onboarding actions: create a doc (folders in the path are made), init the
  // git repo, or connect/clone a remote (GitHub or an Overleaf git URL).
  const submitPrompt = () => {
    if (!prompt) {
      return
    }

    const value = prompt.value.trim()
    const mode = prompt.mode
    setPrompt(null)

    if (!value) {
      return
    }

    if (mode === 'newdoc') {
      ensureLatexDir(dir)
      const { error, rel } = createTexFile(dir, value)

      if (error) {
        setFlash(`new doc: ${error}`)

        return
      }

      const next = listTexFiles(dir)
      setFiles(next)
      const idx = next.findIndex(f => f.rel === rel)

      if (idx >= 0) {
        setSel(idx)
        setScroll(0)
        setFocus('reader')
      }

      setFlash(`created ${rel}`)

      return
    }

    if (mode === 'github') {
      // Create a private GitHub repo from this workspace and push it.
      ensureLatexDir(dir)
      runSync('GitHub repo', async () => {
        if (!(await ghAuthStatus())) {
          return { error: 'gh not signed in — run:  ! gh auth login' }
        }

        const init = await gitInit(dir) // ensures a repo + a commit to push

        if (init.error && !repo) {
          return init
        }

        return ghCreateRepo(dir, value, true)
      })

      return
    }

    // remote: clone into an empty workspace, else init (if needed) + set origin
    ensureLatexDir(dir)
    runSync('connect', async () => {
      if (!repo && files.length === 0) {
        return gitClone(value, dir)
      }

      if (!repo) {
        await gitInit(dir)
      }

      return gitSetRemote(dir, value)
    })
  }

  // ── editing the .tex source ─────────────────────────────────────────────
  const enterEdit = () => {
    if (!activeFile) {
      return
    }

    setEditText(content)
    setEditCursor(content.length)
    setDirty(false)
    setEditing(true)
    setFocus('reader')
  }

  const saveEdit = (exit: boolean) => {
    if (activeFile) {
      const { error } = writeTexFile(dir, activeFile.rel, editText)

      if (error) {
        setFlash(`save failed: ${truncate(error, 50)}`)

        return
      }

      setContent(editText)
      setDirty(false)
      setFlash('saved')
      reload()
    }

    if (exit) {
      setEditing(false)
    }
  }

  const insertAtCursor = (s: string) => {
    setEditText(t => t.slice(0, editCursor) + s + t.slice(editCursor))
    setEditCursor(c => c + s.length)
    setDirty(true)
  }

  const backspaceEdit = () => {
    if (editCursor === 0) {
      return
    }

    setEditText(t => t.slice(0, editCursor - 1) + t.slice(editCursor))
    setEditCursor(c => Math.max(0, c - 1))
    setDirty(true)
  }

  // Move the edit cursor up/down a line, keeping the column where possible.
  const moveCursorVertical = (delta: -1 | 1) => {
    const before = editText.slice(0, editCursor)
    const lineStart = before.lastIndexOf('\n') + 1
    const col = editCursor - lineStart

    if (delta === -1) {
      if (lineStart === 0) {
        return setEditCursor(0)
      }

      const prevStart = editText.lastIndexOf('\n', lineStart - 2) + 1
      const prevLen = lineStart - 1 - prevStart

      return setEditCursor(prevStart + Math.min(col, prevLen))
    }

    const lineEnd = editText.indexOf('\n', editCursor)

    if (lineEnd === -1) {
      return setEditCursor(editText.length)
    }

    const nextStart = lineEnd + 1
    const nextEndIdx = editText.indexOf('\n', nextStart)
    const nextLen = (nextEndIdx === -1 ? editText.length : nextEndIdx) - nextStart

    return setEditCursor(nextStart + Math.min(col, nextLen))
  }

  // Hand the current document to the agent (drafts a starter into the composer).
  const askAgent = () => {
    if (!activeFile) {
      return
    }

    if (!onDraft) {
      setFlash('agent unavailable here')

      return
    }

    onDraft(`About my LaTeX document "${activeFile.rel}": `)
    onClose()
  }

  const width = Math.max(48, cols - 4)
  const contentHeight = Math.max(8, termRows - 8)
  const listW = Math.min(40, Math.max(24, Math.floor(width * 0.32)))
  const readerW = Math.max(20, width - listW - 2)
  const listRows = Math.max(3, contentHeight - 2)
  const readerRows = Math.max(3, contentHeight - 1)

  useInput((ch, key) => {
    if (editing) {
      if (key.escape) {
        return saveEdit(true)
      }

      if (key.ctrl && (ch === 's' || ch === 'S')) {
        return saveEdit(false)
      }

      if (key.leftArrow) {
        return setEditCursor(c => Math.max(0, c - 1))
      }

      if (key.rightArrow) {
        return setEditCursor(c => Math.min(editText.length, c + 1))
      }

      if (key.upArrow) {
        return moveCursorVertical(-1)
      }

      if (key.downArrow) {
        return moveCursorVertical(1)
      }

      if (key.return) {
        return insertAtCursor('\n')
      }

      if (key.backspace || key.delete) {
        return backspaceEdit()
      }

      if (ch && !key.ctrl && !key.meta) {
        const printable = [...ch].filter(c => c >= ' ').join('')

        if (printable) {
          insertAtCursor(printable)
        }
      }

      return
    }

    if (prompt) {
      if (key.escape) {
        return setPrompt(null)
      }

      if (key.return) {
        return submitPrompt()
      }

      if (key.backspace || key.delete) {
        return setPrompt(p => (p ? { ...p, value: p.value.slice(0, -1) } : p))
      }

      if (ch && !key.ctrl && !key.meta) {
        const printable = [...ch].filter(c => c >= ' ').join('')

        if (printable) {
          setPrompt(p => (p ? { ...p, value: p.value + printable } : p))
        }
      }

      return
    }

    if (searching) {
      if (key.escape || key.return) {
        return setSearching(false)
      }

      if (key.backspace || key.delete) {
        return setQuery(s => s.slice(0, -1))
      }

      if (ch && !key.ctrl && !key.meta) {
        const printable = [...ch].filter(c => c >= ' ').join('')

        if (printable) {
          setSel(0)
          setQuery(s => s + printable)
        }
      }

      return
    }

    if (ch === 'q') {
      return onClose()
    }

    // `h` opens the unified Help modal — consistent on every view. Nav mode only
    // (the new-doc / git prompt guards above already returned).
    if (ch === 'h') {
      return openHelpOverlay()
    }

    // Docs kind tabs: 1 Markdown · 2 LaTeX (this view).
    if (onSelectKind && (ch === '1' || ch === '2')) {
      return onSelectKind(ch === '2' ? 'latex' : 'markdown')
    }

    // Onboarding / authoring: new doc, init git repo, connect Overleaf/GitHub.
    if (ch === 'n') {
      return setPrompt({ mode: 'newdoc', value: '' })
    }

    if (ch === 'g' && tools.git) {
      return runSync('git init', () => gitInit(dir))
    }

    if (ch === 'G' && tools.gh) {
      return setPrompt({ mode: 'github', value: dir.split('/').filter(Boolean).pop() || 'docs' })
    }

    // Connect an existing remote (Overleaf / GitHub git URL). Moved off `O` so
    // o/O carry the house-standard sort verbs (Desk/Markets/Docs all agree).
    if (ch === 'c' && tools.git) {
      return setPrompt({ mode: 'remote', value: '' })
    }

    if (ch === '/') {
      return setSearching(true)
    }

    // o cycles the sort column (name ↔ modified ↔ default); O flips direction.
    // Keep the open document selected across the re-sort so reading is never
    // interrupted (armReselect stashes the active file by rel-path).
    if (ch === 'o') {
      armReselect()

      return sort.cycle()
    }

    if (ch === 'O') {
      armReselect()

      return sort.toggle()
    }

    if (ch === 'r') {
      reload()
      void refreshGit()
      setFlash('refreshed')

      return
    }

    if (ch === 'e' && activeFile) {
      return enterEdit()
    }

    if (ch === 'a') {
      return askAgent()
    }

    if (tools.git && ch === 'p') {
      return runSync('pull', () => gitPull(dir))
    }

    if (tools.git && ch === 'P') {
      return runSync('commit + push', () => gitCommitPush(dir, 'LaTeX docs sync from Outrider'))
    }

    if (tools.olcli && ch === 'u') {
      return runSync('overleaf pull', () => overleaf(dir, ['pull']))
    }

    if (focus === 'reader') {
      // ← / Esc return to the list; `h` is now Help (handled above).
      if (key.escape || key.leftArrow) {
        return setFocus('list')
      }

      if (key.upArrow || ch === 'k' || key.wheelUp) {
        return setScroll(s => Math.max(0, s - 1))
      }

      if (key.downArrow || ch === 'j' || key.wheelDown) {
        return setScroll(s => Math.min(Math.max(0, blocks.length - 1), s + 1))
      }

      return
    }

    // list focus
    if (key.escape) {
      return onClose()
    }

    if (key.upArrow || ch === 'k' || key.wheelUp) {
      return setSel(i => Math.max(0, i - 1))
    }

    if (key.downArrow || ch === 'j' || key.wheelDown) {
      return setSel(i => Math.min(Math.max(0, filtered.length - 1), i + 1))
    }

    if ((key.return || key.rightArrow || ch === 'l') && activeFile) {
      setScroll(0)

      return setFocus('reader')
    }
  }, { isActive: !globalModal })

  // ── status ────────────────────────────────────────────────────────────────
  const statusKind = busy ? 'busy' : repo ? 'live' : 'idle'

  const statusWord = busy
    ? 'syncing…'
    : !tools.git
      ? 'git not found'
      : !repo
        ? 'not a git repo'
        : git
          ? `${git.branch}${git.dirty ? ` · ${git.dirty} changed` : ' · clean'}${git.behind ? ` · ↓${git.behind}` : ''}${git.ahead ? ` · ↑${git.ahead}` : ''}`
          : 'git ready'

  const header = (
    <DocsHeader
      cols={cols}
      filter={searching || query ? { live: searching, query } : null}
      path={dir}
      segments={
        <>
          <Text color={busy ? sem.star : repo ? sem.up : sem.subtle}>{statusGlyph(statusKind, tick)}</Text>
          <Text color={t.color.muted}>{` ${statusWord} · `}</Text>
          <Text color={t.color.text}>{`${files.length} doc${files.length === 1 ? '' : 's'}`}</Text>
        </>
      }
      t={t}
      title="LATEX"
    />
  )

  // Inline prompt (shared by both states): name a doc, paste a remote URL, or
  // name a new GitHub repo.
  const promptLabel = prompt?.mode === 'newdoc' ? 'New doc  ' : prompt?.mode === 'github' ? 'GH repo  ' : 'Remote   '

  const promptHint =
    prompt?.mode === 'newdoc'
      ? ' name, e.g. latex/intro.tex'
      : prompt?.mode === 'github'
        ? ' repo name (created private + pushed)'
        : ' git URL — GitHub or https://git.overleaf.com/…'

  const promptLine = prompt ? (
    <Box flexShrink={0}>
      <Text bold color={t.color.accent}>{promptLabel}</Text>
      <Text color={t.color.muted}>{'› '}</Text>
      <Text color={t.color.text}>{prompt.value}</Text>
      <Text color={t.color.text} inverse>
        {' '}
      </Text>
      {!prompt.value ? <Text color={t.color.muted}>{promptHint}</Text> : null}
    </Box>
  ) : null

  // DOCS kind tabs — the lens strip lives at the TOP under the header now (house
  // pattern), so it's always clear how to switch collections.
  const kindTabs = onSelectKind ? (
    <DocsKindTabs disabled={globalModal} kind={docKind ?? 'latex'} onSelect={onSelectKind} t={t} />
  ) : null

  const onboardChips: FooterChip[] = [
    { k: 'n', label: 'New doc', run: () => setPrompt({ mode: 'newdoc', value: '' }) },
    ...(tools.git ? [{ k: 'g', label: 'Init git', run: () => runSync('git init', () => gitInit(dir)) }] : []),
    ...(tools.gh ? [{ k: 'G', label: 'GitHub repo', run: () => setPrompt({ mode: 'github', value: dir.split('/').filter(Boolean).pop() || 'docs' }) }] : []),
    ...(tools.git ? [{ k: 'c', label: 'Connect remote', run: () => setPrompt({ mode: 'remote', value: '' }) }] : []),
    { k: 'r', label: 'Refresh', run: () => { reload(); void refreshGit(); setFlash('refreshed') } },
    { k: 'h', label: 'Help', run: openHelpOverlay },
    { k: 'q', label: 'Close', run: onClose }
  ]

  // Onboarding (no documents yet): suggest creating one + setting up sync.
  if (files.length === 0 && !searching) {
    return (
      <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
        {header}
        {kindTabs}
        <Box alignItems="center" flexGrow={1} justifyContent="center">
          <Box flexDirection="column" width={Math.min(78, width)}>
            <Text bold color={t.color.text}>
              Start your LaTeX workspace.
            </Text>
            <Box marginTop={1}>
              <Text color={t.color.muted} wrap="wrap">
                One git-backed docs folder lives at <Text color={t.color.accent}>{dir}</Text> — everything syncs to a
                single remote. Create a document, initialise the repo, then connect Overleaf or GitHub.
              </Text>
            </Box>
            <Box flexDirection="column" marginTop={1}>
              <Text color={t.color.text}>
                <Text bold color={t.color.accent}>n</Text> new .tex document (folders in the path are created)
              </Text>
              <Text color={t.color.text}>
                <Text bold color={t.color.accent}>g</Text> initialise the git repo {tools.git ? '' : '— install git first'}
              </Text>
              <Text color={t.color.text}>
                <Text bold color={t.color.accent}>G</Text> create a private GitHub repo + push {tools.gh ? '' : '— install gh first'}
              </Text>
              <Text color={t.color.text}>
                <Text bold color={t.color.accent}>c</Text> connect an existing remote (Overleaf or GitHub git URL)
              </Text>
            </Box>
            <Box marginTop={1}>
              <Text color={t.color.muted} wrap="truncate-end">
                {`git ${tools.git ? '✓' : '✗'}  ·  gh ${tools.gh ? '✓' : '✗ (GitHub CLI)'}  ·  olcli ${tools.olcli ? '✓' : '✗ optional — git URL works without it'}`}
              </Text>
            </Box>
          </Box>
        </Box>
        <Box flexDirection="column" flexShrink={0} marginTop={1}>
          {prompt ? promptLine : <FooterChips chips={onboardChips} disabled={globalModal} t={t} />}
          <Text color={t.color.muted} wrap="truncate-end">
            {flash ? <Text color={t.color.accent}>{flash} · </Text> : null}
            {prompt ? '⏎ confirm · Esc cancel' : `1/2 switch · n new doc${tools.git ? ' · g init git' : ''}${tools.gh ? ' · G GitHub repo' : ''} · c connect · r refresh · q close`}
          </Text>
        </Box>
      </Box>
    )
  }

  // ── file list (left) ───────────────────────────────────────────────────────
  const listStart = Math.max(0, Math.min(clampedSel - Math.floor(listRows / 2), filtered.length - listRows))
  const windowed = filtered.slice(Math.max(0, listStart), Math.max(0, listStart) + listRows)
  const listFocused = focus === 'list'

  const list = (
    <Box
      borderBottom={false}
      borderColor={listFocused ? t.color.accent : t.color.border}
      borderLeft={false}
      borderStyle="single"
      borderTop={false}
      flexDirection="column"
      flexShrink={0}
      height={contentHeight}
      overflow="hidden"
      paddingRight={1}
      width={listW}
    >
      <Text bold color={listFocused ? t.color.accent : t.color.label} wrap="truncate-end">
        DOCS
        <Text color={t.color.muted}>{`  ${filtered.length}`}</Text>
        {sort.state.key ? (
          <Text color={t.color.muted}>{`  ${sort.state.key === 'modified' ? 'modified' : 'name'} ${sortIndicator(sort.state, sort.state.key)}`}</Text>
        ) : null}
      </Text>
      <Box flexDirection="column" marginTop={1}>
        {filtered.length === 0 ? (
          <Text color={t.color.muted} wrap="wrap">
            {query ? `No .tex file matches “${query}”. / to refine · Esc clears.` : 'No documents.'}
          </Text>
        ) : (
          windowed.map((f, i) => {
            const idx = listStart + i
            const on = idx === clampedSel
            const name = f.rel.replace(/\.tex$/i, '')
            // Right-aligned dim meta: relative age (+ a size chip on wider lists).
            const meta = [docAge(f.mtime), listW >= 34 ? sizeChip(f.size) : ''].filter(Boolean).join(' ')
            const nameW = Math.max(6, listW - 4 - (meta ? meta.length + 1 : 0))
            const { base, dir } = titlePath(name, nameW)

            return (
              <Box key={f.rel} onClick={() => { if (globalModal) return; setSel(idx); setScroll(0); setFocus('reader') }} width="100%">
                <Text color={on ? t.color.accent : t.color.border}>{on ? '▸ ' : '  '}</Text>
                <Box flexGrow={1} minWidth={0}>
                  <Text wrap="truncate-end">
                    {dir ? <Text color={on ? t.color.muted : t.color.border}>{dir}</Text> : null}
                    <Text bold={on} color={on ? t.color.text : t.color.label}>
                      {base}
                    </Text>
                  </Text>
                </Box>
                {meta ? <Text color={t.color.muted}>{` ${meta}`}</Text> : null}
              </Box>
            )
          })
        )}
      </Box>
    </Box>
  )

  // ── reader (right) ───────────────────────────────────────────────────────
  const readerFocused = focus === 'reader'
  const readStart = Math.min(scroll, Math.max(0, blocks.length - 1))
  const windowBlocks = blocks.slice(readStart, readStart + readerRows)

  const renderBlock = (b: LatexBlock, i: number) => {
    const key = `${readStart + i}`

    if (b.kind === 'blank') {
      return <Text key={key}> </Text>
    }

    if (b.kind === 'rule') {
      return <Text color={sem.rule} key={key}>{'─'.repeat(Math.max(4, readerW - 2))}</Text>
    }

    if (b.kind === 'heading') {
      const lvl = b.level ?? 1
      const color = lvl === 0 ? t.color.primary : lvl === 1 ? t.color.accent : t.color.label

      return (
        <Text bold color={color} key={key} wrap="truncate-end">
          {lvl >= 2 ? `${'  '.repeat(lvl - 1)}` : ''}
          {b.text}
        </Text>
      )
    }

    if (b.kind === 'item') {
      return (
        <Text color={t.color.text} key={key} wrap="wrap">
          {`${'  '.repeat(b.level ?? 1)}• `}
          {b.text}
        </Text>
      )
    }

    if (b.kind === 'math') {
      return (
        <Text color={sem.badge} key={key} wrap="wrap">
          {'    '}
          {b.text}
        </Text>
      )
    }

    if (b.kind === 'verbatim') {
      return (
        <Text color={t.color.muted} key={key} wrap="truncate-end">
          {`  ${b.text}`}
        </Text>
      )
    }

    return (
      <Text color={t.color.text} key={key} wrap="wrap">
        {b.text}
      </Text>
    )
  }

  // Edit-mode source editor: window the lines around the cursor, draw a block
  // caret on the cursor line.
  const editLines = editText.split('\n')
  const before = editText.slice(0, editCursor)
  const curLine = before.split('\n').length - 1
  const curCol = editCursor - (before.lastIndexOf('\n') + 1)
  const editStart = Math.max(0, Math.min(curLine - Math.floor(readerRows / 2), editLines.length - readerRows))
  const editWindow = editLines.slice(editStart, editStart + readerRows)

  const reader = (
    <Box flexDirection="column" flexShrink={0} height={contentHeight} marginLeft={1} minWidth={0} overflow="hidden" width={readerW}>
      <Text bold color={readerFocused || editing ? t.color.accent : t.color.label} wrap="truncate-end">
        {editing ? '✎ ' : readerFocused ? '▸ ' : ''}
        {activeFile ? activeFile.rel : 'READER'}
        {editing ? <Text color={dirty ? sem.star : t.color.muted}>{dirty ? '  ● editing' : '  editing'}</Text> : null}
        {!editing && blocks.length && scroll > 0 ? <Text color={t.color.muted}>{`  ↑ ${readStart}`}</Text> : null}
      </Text>
      <Box flexDirection="column" marginTop={1} minHeight={0} overflow="hidden">
        {editing ? (
          editWindow.map((line, i) => {
            const gi = editStart + i

            if (gi !== curLine) {
              return (
                <Text color={t.color.text} key={`e${gi}`} wrap="truncate-end">
                  {line || ' '}
                </Text>
              )
            }

            return (
              <Text key={`e${gi}`} wrap="truncate-end">
                <Text color={t.color.text}>{line.slice(0, curCol)}</Text>
                <Text color={t.color.text} inverse>
                  {line[curCol] ?? ' '}
                </Text>
                <Text color={t.color.text}>{line.slice(curCol + 1)}</Text>
              </Text>
            )
          })
        ) : windowBlocks.length === 0 ? (
          <Text color={t.color.muted} wrap="wrap">
            {activeFile ? 'Empty document — press e to edit.' : 'Select a .tex file to read it here.'}
          </Text>
        ) : (
          windowBlocks.map((b, i) => renderBlock(b, i))
        )}
      </Box>
    </Box>
  )

  // The footer chips are windowed to the width: at narrow terminals we show the
  // core verbs only (every chip shown is still a LIVE key; the `?` cheat-sheet
  // carries the rest) so the row never overflows and corrupts.
  const narrow = cols < 100
  const chips: FooterChip[] = editing
    ? [
        { k: '⎋', label: dirty ? 'Save & exit' : 'Exit' },
        { k: '^S', label: 'Save' }
      ]
    : [
        { k: '↑↓', label: readerFocused ? 'Scroll' : 'Docs' },
        { k: '⏎', label: 'Read', run: () => activeFile && setFocus('reader') },
        { k: 'e', label: 'Edit', run: () => activeFile && enterEdit() },
        { k: '/', label: 'Filter', run: () => setSearching(true) },
        { k: 'o', label: 'Sort', run: () => { armReselect(); sort.cycle() } },
        ...(narrow
          ? []
          : [
              { k: 'a', label: 'Ask agent', run: askAgent },
              { k: 'n', label: 'New', run: () => setPrompt({ mode: 'newdoc', value: '' }) },
              ...(tools.git ? [{ k: 'P', label: 'Push', run: () => runSync('commit + push', () => gitCommitPush(dir, 'LaTeX docs sync from Outrider')) }] : [])
            ]),
        { k: 'h', label: 'Help', run: openHelpOverlay },
        { k: 'q', label: 'Close', run: onClose }
      ]

  // The FooterChips above are the ONE shortcuts row (house pattern — Desk/Markets/
  // News all dropped their prose duplicate). This second line is contextual STATUS
  // only: a transient flash, the instructions for a transient mode (edit/prompt/
  // filter), or the reader's back-hint (the only key there that is NOT a chip). It
  // never restates the chips, and it only paints when there is something to say.
  const statusHint = editing
    ? 'type to edit · arrows move · ⏎ newline · ⌃S save · Esc save & exit'
    : prompt
      ? '⏎ confirm · Esc cancel'
      : searching
        ? 'type to filter · ⏎/Esc done'
        : readerFocused
          ? 'Esc/← back to list'
          : null

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      {editing ? null : kindTabs}
      <Box flexDirection="row" flexShrink={0} height={contentHeight}>
        {list}
        {reader}
      </Box>
      <Box flexDirection="column" flexShrink={0} marginTop={1}>
        {prompt ? promptLine : <FooterChips chips={chips} disabled={globalModal} t={t} />}
        {flash || statusHint ? (
          <Text color={t.color.muted} wrap="truncate-end">
            {flash ? <Text color={t.color.accent}>{flash}{statusHint ? ' · ' : ''}</Text> : null}
            {statusHint}
          </Text>
        ) : null}
      </Box>
    </Box>
  )
}
