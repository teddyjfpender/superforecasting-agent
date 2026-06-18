import { Box, Text, useInput, useStdout } from '@hermes/ink'
import { useEffect, useMemo, useRef, useState } from 'react'

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
import { statusGlyph } from '../lib/icons.js'
import { createTexFile, docsDir, ensureLatexDir, latexSubdir, listTexFiles, readTexFile, type TexFile } from '../lib/latexDocs.js'
import { seedLatexExamples } from '../lib/latexExamples.js'
import { type LatexBlock, renderLatex } from '../lib/latexRender.js'
import { semantics } from '../lib/visualSemantics.js'
import type { Theme } from '../theme.js'

import { type FooterChip, FooterChips } from './footerChips.js'

// LaTeX side of Docs: browse local .tex files, render them readably, and sync
// the directory with git (commit/push/pull — Overleaf projects are git-backed)
// or Overleaf's olcli. Two panes split by a vertical rule, like News/Markets.

const truncate = (value: string, max: number): string =>
  value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value

interface LatexDocsViewProps {
  docKind?: 'latex' | 'markdown'
  onClose: () => void
  onSelectKind?: (kind: 'latex' | 'markdown') => void
  t: Theme
}

export function LatexDocsView({ docKind, onClose, onSelectKind, t }: LatexDocsViewProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24
  const sem = semantics(t)

  const dirRef = useRef(docsDir())
  const dir = dirRef.current

  const [files, setFiles] = useState<TexFile[]>([])
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
  const aliveRef = useRef(true)

  useEffect(() => {
    aliveRef.current = true
    const id = setInterval(() => setTick(v => v + 1), 600)

    return () => {
      aliveRef.current = false
      clearInterval(id)
    }
  }, [])

  useEffect(() => {
    stdout?.write('\x1b[?25l')

    return () => {
      stdout?.write('\x1b[?25h')
    }
  }, [stdout])

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

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()

    return q ? files.filter(f => f.rel.toLowerCase().includes(q)) : files
     
  }, [files, query])

  const clampedSel = Math.min(sel, Math.max(0, filtered.length - 1))
  const activeFile = filtered[clampedSel]

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

  const width = Math.max(48, cols - 4)
  const contentHeight = Math.max(8, termRows - 8)
  const listW = Math.min(40, Math.max(24, Math.floor(width * 0.32)))
  const readerW = Math.max(20, width - listW - 2)
  const listRows = Math.max(3, contentHeight - 2)
  const readerRows = Math.max(3, contentHeight - 1)

  useInput((ch, key) => {
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

    if (ch === 'O' && tools.git) {
      return setPrompt({ mode: 'remote', value: '' })
    }

    if (ch === '/') {
      return setSearching(true)
    }

    if (ch === 'r') {
      reload()
      void refreshGit()
      setFlash('refreshed')

      return
    }

    if (tools.git && ch === 'p') {
      return runSync('pull', () => gitPull(dir))
    }

    if (tools.git && ch === 'P') {
      return runSync('commit + push', () => gitCommitPush(dir, 'LaTeX docs sync from Outrider'))
    }

    if (tools.olcli && ch === 'o') {
      return runSync('overleaf pull', () => overleaf(dir, ['pull']))
    }

    if (focus === 'reader') {
      if (key.escape || key.leftArrow || ch === 'h') {
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
  })

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
    <Box flexDirection="column" flexShrink={0} marginBottom={1}>
      <Text wrap="truncate-end">
        <Text bold color={t.color.primary}>
          LATEX
        </Text>
        <Text color={t.color.muted}>{'   '}</Text>
        <Text color={busy ? sem.star : repo ? sem.up : sem.subtle}>{statusGlyph(statusKind, tick)}</Text>
        <Text color={t.color.muted}> {statusWord} · </Text>
        <Text color={t.color.text}>{`${files.length} docs`}</Text>
        <Text color={t.color.muted} wrap="truncate-end">{`  ${dir}`}</Text>
      </Text>
    </Box>
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

  // DOCS kind tabs — shown in every footer (onboarding + populated) so it's
  // always clear how to switch back to Markdown.
  const kindTabs = onSelectKind ? (
    <Box marginBottom={1}>
      <Text color={t.color.muted}>DOCS </Text>
      <Box onClick={() => onSelectKind('markdown')}>
        <Text bold={docKind !== 'latex'} color={docKind !== 'latex' ? t.color.accent : t.color.muted}>
          {docKind !== 'latex' ? '▸ 1 Markdown' : '  1 Markdown'}
        </Text>
      </Box>
      <Text color={t.color.border}>{'   ·   '}</Text>
      <Box onClick={() => onSelectKind('latex')}>
        <Text bold={docKind === 'latex'} color={docKind === 'latex' ? t.color.accent : t.color.muted}>
          {docKind === 'latex' ? '▸ 2 LaTeX' : '  2 LaTeX'}
        </Text>
      </Box>
    </Box>
  ) : null

  const onboardChips: FooterChip[] = [
    { k: 'n', label: 'New doc', run: () => setPrompt({ mode: 'newdoc', value: '' }) },
    ...(tools.git ? [{ k: 'g', label: 'Init git', run: () => runSync('git init', () => gitInit(dir)) }] : []),
    ...(tools.gh ? [{ k: 'G', label: 'GitHub repo', run: () => setPrompt({ mode: 'github', value: dir.split('/').filter(Boolean).pop() || 'docs' }) }] : []),
    ...(tools.git ? [{ k: 'O', label: 'Connect remote', run: () => setPrompt({ mode: 'remote', value: '' }) }] : []),
    { k: 'r', label: 'Refresh', run: () => { reload(); void refreshGit(); setFlash('refreshed') } },
    { k: 'q', label: 'Close', run: onClose }
  ]

  // Onboarding (no documents yet): suggest creating one + setting up sync.
  if (files.length === 0 && !searching) {
    return (
      <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
        {header}
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
                <Text bold color={t.color.accent}>O</Text> connect an existing remote (Overleaf or GitHub git URL)
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
          {kindTabs}
          {prompt ? promptLine : <FooterChips chips={onboardChips} t={t} />}
          <Text color={t.color.muted} wrap="truncate-end">
            {flash ? <Text color={t.color.accent}>{flash} · </Text> : null}
            {prompt ? '⏎ confirm · Esc cancel' : `1/2 switch · n new doc${tools.git ? ' · g init git' : ''}${tools.gh ? ' · G GitHub repo' : ''} · O connect · r refresh · q close`}
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
      {searching ? (
        <Text wrap="truncate-end">
          <Text bold color={sem.cursor}>{'⌕ '}</Text>
          <Text color={t.color.text}>{query}</Text>
          <Text color={t.color.text} inverse>
            {' '}
          </Text>
        </Text>
      ) : (
        <Text bold color={listFocused ? t.color.accent : t.color.label} wrap="truncate-end">
          DOCS{query ? <Text color={t.color.muted}>{`  /${query}`}</Text> : null}
        </Text>
      )}
      <Box flexDirection="column" marginTop={1}>
        {filtered.length === 0 ? (
          <Text color={t.color.muted} wrap="wrap">
            No match for “{query}”.
          </Text>
        ) : (
          windowed.map((f, i) => {
            const idx = listStart + i
            const on = idx === clampedSel
            const name = f.rel.replace(/\.tex$/i, '')

            return (
              <Box key={f.rel} onClick={() => { setSel(idx); setScroll(0); setFocus('reader') }} width="100%">
                <Text wrap="truncate-end">
                  <Text color={on ? t.color.accent : t.color.border}>{on ? '▸ ' : '  '}</Text>
                  <Text bold={on} color={on ? t.color.text : t.color.label}>
                    {truncate(name, listW - 4)}
                  </Text>
                </Text>
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

  const reader = (
    <Box flexDirection="column" flexShrink={0} height={contentHeight} marginLeft={1} minWidth={0} overflow="hidden" width={readerW}>
      <Text bold color={readerFocused ? t.color.accent : t.color.label} wrap="truncate-end">
        {readerFocused ? '▸ ' : ''}
        {activeFile ? activeFile.rel : 'READER'}
        {blocks.length && scroll > 0 ? <Text color={t.color.muted}>{`  ↑ ${readStart}`}</Text> : null}
      </Text>
      <Box flexDirection="column" marginTop={1} minHeight={0} overflow="hidden">
        {windowBlocks.length === 0 ? (
          <Text color={t.color.muted} wrap="wrap">
            {activeFile ? 'Empty document.' : 'Select a .tex file to read it here.'}
          </Text>
        ) : (
          windowBlocks.map((b, i) => renderBlock(b, i))
        )}
      </Box>
    </Box>
  )

  const chips: FooterChip[] = [
    { k: '↑↓', label: readerFocused ? 'Scroll' : 'Docs' },
    { k: '⏎', label: 'Read', run: () => activeFile && setFocus('reader') },
    { k: 'n', label: 'New', run: () => setPrompt({ mode: 'newdoc', value: '' }) },
    { k: '/', label: 'Search', run: () => setSearching(true) },
    ...(tools.git ? [{ k: 'p', label: 'Pull', run: () => runSync('pull', () => gitPull(dir)) }] : []),
    ...(tools.git ? [{ k: 'P', label: 'Push', run: () => runSync('commit + push', () => gitCommitPush(dir, 'LaTeX docs sync from Outrider')) }] : []),
    ...(tools.olcli ? [{ k: 'o', label: 'Overleaf', run: () => runSync('overleaf pull', () => overleaf(dir, ['pull'])) }] : []),
    { k: 'q', label: 'Close', run: onClose }
  ]

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      <Box flexDirection="row" flexShrink={0} height={contentHeight}>
        {list}
        {reader}
      </Box>
      <Box flexDirection="column" flexShrink={0} marginTop={1}>
        {kindTabs}
        {prompt ? promptLine : <FooterChips chips={chips} t={t} />}
        <Text color={t.color.muted} wrap="truncate-end">
          {flash ? <Text color={t.color.accent}>{flash} · </Text> : null}
          {prompt
            ? '⏎ confirm · Esc cancel'
            : searching
              ? 'type to filter · ⏎/Esc done'
              : readerFocused
                ? '↑↓ scroll · Esc/← back · / search · q close'
                : `↑↓ docs · ⏎/→ read · n new · O Overleaf/GitHub · /${tools.git ? ' · p pull · P push' : ''}${tools.olcli ? ' · o overleaf' : ''} · r refresh · q`}
        </Text>
      </Box>
    </Box>
  )
}
