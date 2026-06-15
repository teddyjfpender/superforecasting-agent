import { Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text, useInput, useStdout } from '@hermes/ink'
import { type ReactNode, useEffect, useRef, useState } from 'react'

import { patchOverlayState } from '../app/overlayStore.js'
import type { GatewayClient } from '../gatewayClient.js'
import type { ObsidianNote, ObsidianNoteResponse, ObsidianStatusResponse } from '../gatewayTypes.js'
import { highlightMarkdownLine } from '../lib/markdownEditorHighlight.js'
import { asRpcResult } from '../lib/rpc.js'
import type { Theme } from '../theme.js'

import { OverlayScrollbar } from './agentsOverlay.js'
import { INLINE_RE, Md, wikiLinkLabel } from './markdown.js'

export const openObsidianView = () => patchOverlayState({ obsidian: true })
export const closeObsidianView = () => patchOverlayState({ obsidian: false })

const truncate = (value: string, max: number): string =>
  value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value

// Split YAML frontmatter off the body so the markdown renderer gets clean
// markdown (otherwise `---` renders as a rule and `tags:` as raw text). The
// tags line is surfaced separately. Math ($…$) is handled by the renderer.
const FRONTMATTER_RE = /^---\n([\s\S]*?)\n---\n?/

const splitFrontmatter = (text: string): { body: string; tags: string } => {
  const m = FRONTMATTER_RE.exec(text)

  if (!m) {
    return { body: text, tags: '' }
  }

  const tagMatch = /tags:\s*\[([^\]]*)\]/.exec(m[1])

  return { body: text.slice(m[0].length), tags: tagMatch ? tagMatch[1].trim() : '' }
}

type Section = { level: number; text: string; title: string }

// Split a markdown body into heading-delimited sections. Joining the sections'
// text with '\n' reproduces the body exactly (used for comment insertion).
const splitSections = (body: string): Section[] => {
  const out: Section[] = []
  let cur: Section = { level: 0, text: '', title: '' }
  let fenced = false

  for (const line of body.split('\n')) {
    if (/^\s*(```|~~~)/.test(line)) {
      fenced = !fenced
    }

    const h = fenced ? null : /^(#{1,6})\s+(.*)$/.exec(line)

    if (h) {
      if (cur.text.trim() || cur.title) {
        out.push(cur)
      }

      cur = { level: h[1].length, text: line, title: h[2].trim() }
    } else {
      cur.text += (cur.text ? '\n' : '') + line
    }
  }

  if (cur.text.trim() || cur.title) {
    out.push(cur)
  }

  return out
}

// Insert a comment block at the end of section `index` (before the next
// heading), so comments are anchored under the section they're about. Falls
// back to appending at the end when the section has no heading.
const insertCommentUnderSection = (fullContent: string, index: number, comment: string): string => {
  const block = `> 💬 ${comment}`
  const { body } = splitFrontmatter(fullContent)
  const fm = fullContent.slice(0, fullContent.length - body.length)
  const secs = splitSections(body)
  const target = secs[index]

  if (!target || !target.title) {
    return `${fullContent.replace(/\n+$/, '')}\n\n${block}\n`
  }

  secs[index] = { ...target, text: `${target.text.replace(/\n+$/, '')}\n\n${block}` }

  return fm + secs.map(s => s.text).join('\n')
}

type PromptMode = 'comment' | 'create'

interface ObsidianViewProps {
  gw: GatewayClient
  onClose: () => void
  onDraft?: (command: string) => void
  t: Theme
}

export function ObsidianView({ gw, onClose, onDraft, t }: ObsidianViewProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24

  const [data, setData] = useState<ObsidianStatusResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<null | string>(null)
  const [flash, setFlash] = useState('')
  const [now, setNow] = useState(0)
  const [selected, setSelected] = useState(0)
  const [doc, setDoc] = useState<ObsidianNoteResponse | null>(null)
  const [docLoading, setDocLoading] = useState(false)
  const [docError, setDocError] = useState<null | string>(null)
  const [prompt, setPrompt] = useState<null | { mode: PromptMode; value: string }>(null)
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState('')
  const [editCursor, setEditCursor] = useState(0)
  const [saveState, setSaveState] = useState<'error' | 'idle' | 'saved' | 'saving'>('idle')
  const [activeSection, setActiveSection] = useState(0)
  const [focusedLink, setFocusedLink] = useState(-1)
  const dirtyRef = useRef(false)
  const saveTimer = useRef<null | ReturnType<typeof setTimeout>>(null)
  const listScrollRef = useRef<null | ScrollBoxHandle>(null)
  const docScrollRef = useRef<null | ScrollBoxHandle>(null)
   
  const sectionRefs = useRef<any[]>([])

  const notes: ObsidianNote[] = data?.notes ?? []
  const hasVault = Boolean(data?.exists && data?.vault)
  const currentRel = notes[selected]?.rel_path

  // Resolve [[wikilink]] targets the way Obsidian does — by note basename
  // (or title), case-insensitive — so links and backlinks can be followed.
  const baseName = (rel: string) => (rel.split('/').pop() ?? rel).replace(/\.md$/i, '').toLowerCase()

  const resolve = (name: string): string | undefined => {
    const key = name.toLowerCase()

    for (const n of notes) {
      if (n.rel_path && (baseName(n.rel_path) === key || (n.title ?? '').toLowerCase() === key)) {
        return n.rel_path
      }
    }

    return undefined
  }

  // Resolve a raw [[target|alias#heading]] to a note path: drop the alias and
  // heading, then match by basename/title, or by full relative path.
  const resolveTarget = (raw: string): string | undefined => {
    const target = raw.split('|')[0]!.split('#')[0]!.trim()
    const byName = resolve(target)

    if (byName) {
      return byName
    }

    const key = target.replace(/\.md$/i, '').toLowerCase()

    return notes.find(n => n.rel_path?.replace(/\.md$/i, '').toLowerCase() === key)?.rel_path
  }

  const outgoing = (notes[selected]?.links ?? []).map(name => ({ name, rel: resolve(name) }))

  const backlinks = notes.filter(
    n => n.rel_path !== currentRel && (n.links ?? []).some(l => resolve(l) === currentRel)
  )

  const jumpTo = (rel: string | undefined) => {
    if (!rel) {
      return
    }

    const idx = notes.findIndex(n => n.rel_path === rel)

    if (idx >= 0) {
      setSelected(idx)
    }
  }

  const load = (announce = false) => {
    setLoading(true)
    gw.request<unknown>('obsidian.status', { limit: 200 })
      .then(raw => {
        const result = asRpcResult<ObsidianStatusResponse>(raw)

        if (!result) {
          setError('obsidian.status returned no data')
          setLoading(false)

          return
        }

        setData(result)
        setError(null)
        setLoading(false)

        if (announce) {
          setFlash('refreshed')
        }
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err))
        setLoading(false)
      })
  }

  const loadNote = (rel: string) => {
    setDocLoading(true)
    setDocError(null)
    gw.request<unknown>('obsidian.note', { rel_path: rel })
      .then(raw => {
        setDoc(asRpcResult<ObsidianNoteResponse>(raw) ?? null)
        setDocLoading(false)
      })
      .catch((err: unknown) => {
        setDocError(err instanceof Error ? err.message : String(err))
        setDocLoading(false)
      })
  }

  const runSetup = () => {
    setLoading(true)
    setFlash('setting up vault…')
    gw.request<unknown>('obsidian.setup', {})
      .then(() => load(true))
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err))
        setLoading(false)
      })
  }

  // Draft a chat prompt that targets the open note, then drop to the chat so
  // the user can refine/send it — the "co-write with the desk" move.
  const askAgent = () => {
    if (!onDraft || !currentRel) {
      return
    }

    onDraft(`Work on the Obsidian note "${currentRel}" — `)
    onClose()
  }

  // ── In-pane editor (multiline, debounced autosave) ──────────────────────
  const saveNow = (text: string) => {
    if (!currentRel) {
      return
    }

    setSaveState('saving')
    gw.request<unknown>('obsidian.write', { content: text, rel_path: currentRel })
      .then(() => {
        dirtyRef.current = false
        setSaveState('saved')
      })
      .catch((err: unknown) => {
        setSaveState('error')
        setFlash(`save failed: ${err instanceof Error ? err.message : String(err)}`)
      })
  }

  const enterEdit = () => {
    if (!doc || !currentRel) {
      return
    }

    const text = doc.content ?? ''
    setEditText(text)
    setEditCursor(text.length)
    dirtyRef.current = false
    setSaveState('idle')
    setEditing(true)
  }

  const exitEdit = () => {
    if (saveTimer.current) {
      clearTimeout(saveTimer.current)
      saveTimer.current = null
    }

    if (dirtyRef.current) {
      saveNow(editText)
    }

    setEditing(false)

    if (currentRel) {
      loadNote(currentRel)
    }
  }

  // Edit primitives operate on (editText, editCursor).
  const editInsert = (s: string) => {
    setEditText(text => text.slice(0, editCursor) + s + text.slice(editCursor))
    setEditCursor(c => c + s.length)
    dirtyRef.current = true
    setSaveState('idle')
  }

  const editBackspace = () => {
    if (editCursor <= 0) {
      return
    }

    setEditText(text => text.slice(0, editCursor - 1) + text.slice(editCursor))
    setEditCursor(c => Math.max(0, c - 1))
    dirtyRef.current = true
    setSaveState('idle')
  }

  const editMoveLine = (dir: -1 | 1) => {
    const before = editText.slice(0, editCursor)
    const row = before.split('\n').length - 1
    const col = before.length - (before.lastIndexOf('\n') + 1)
    const lines = editText.split('\n')
    const targetRow = Math.max(0, Math.min(lines.length - 1, row + dir))

    if (targetRow === row) {
      return
    }

    let idx = 0

    for (let i = 0; i < targetRow; i++) {
      idx += lines[i].length + 1
    }

    setEditCursor(idx + Math.min(col, lines[targetRow].length))
  }

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

    if (mode === 'create') {
      gw.request<unknown>('obsidian.create', { rel_path: value })
        .then(raw => {
          const created = (asRpcResult<{ rel_path?: string }>(raw) ?? {}).rel_path ?? value
          setFlash(`created ${created}`)
          load()
        })
        .catch((err: unknown) => setFlash(`create failed: ${err instanceof Error ? err.message : String(err)}`))

      return
    }

    // comment → anchor under the active outline section of the open note
    if (!currentRel || !doc?.content) {
      return
    }

    const next = insertCommentUnderSection(doc.content, activeSection, value)
    gw.request<unknown>('obsidian.write', { content: next, rel_path: currentRel })
      .then(() => {
        setFlash('comment added')
        loadNote(currentRel)
      })
      .catch((err: unknown) => setFlash(`comment failed: ${err instanceof Error ? err.message : String(err)}`))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gw])

  // No real text cursor in this view — park it so it doesn't sit in the corner.
  useEffect(() => {
    stdout?.write('\x1b[?25l')

    return () => {
      stdout?.write('\x1b[?25h')
    }
  }, [stdout])

  useEffect(() => {
    if (notes.length && selected > notes.length - 1) {
      setSelected(notes.length - 1)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  useEffect(() => {
    if (currentRel) {
      loadNote(currentRel)
    } else {
      setDoc(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentRel])

  // Each opened note starts at the top (after its content renders).
  useEffect(() => {
    docScrollRef.current?.scrollTo(0)
    setActiveSection(0)
    setFocusedLink(-1)
  }, [doc])

  // Debounced autosave while editing.
  useEffect(() => {
    if (!editing || !dirtyRef.current) {
      return
    }

    if (saveTimer.current) {
      clearTimeout(saveTimer.current)
    }

    saveTimer.current = setTimeout(() => saveNow(editText), 800)

    return () => {
      if (saveTimer.current) {
        clearTimeout(saveTimer.current)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editText, editing])

  // Keep the edit cursor's line in view.
  useEffect(() => {
    if (!editing) {
      return
    }

    const row = editText.slice(0, editCursor).split('\n').length - 1
    docScrollRef.current?.scrollTo(Math.max(0, row - 3))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editCursor, editing])

  useEffect(() => {
    listScrollRef.current?.scrollTo(Math.max(0, selected - 2))
  }, [selected])

  useEffect(() => {
    const id = setInterval(() => setNow(value => value + 1), 500)

    return () => clearInterval(id)
  }, [])

  const pageSize = Math.max(4, termRows - 12)
  const move = (delta: number) => setSelected(s => Math.max(0, Math.min(notes.length - 1, s + delta)))

  useInput((ch, key) => {
    // Inline prompt (new note / comment) captures input while open.
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

      if (ch && ch.length === 1 && !key.ctrl && !key.meta) {
        return setPrompt(p => (p ? { ...p, value: p.value + ch } : p))
      }

      return
    }

    // Edit mode captures input (Esc saves + exits; q is just a character here).
    if (editing) {
      if (key.escape) {
        return exitEdit()
      }

      if (key.ctrl && ch === 's') {
        return saveNow(editText)
      }

      if (key.return) {
        return editInsert('\n')
      }

      if (key.backspace || key.delete) {
        return editBackspace()
      }

      if (key.leftArrow) {
        return setEditCursor(c => Math.max(0, c - 1))
      }

      if (key.rightArrow) {
        return setEditCursor(c => Math.min(editText.length, c + 1))
      }

      if (key.upArrow) {
        return editMoveLine(-1)
      }

      if (key.downArrow) {
        return editMoveLine(1)
      }

      if (key.tab) {
        return editInsert('  ')
      }

      if (ch && !key.ctrl && !key.meta) {
        return editInsert(ch)
      }

      return
    }

    if (ch === 'q' || key.escape) {
      return onClose()
    }

    if (!hasVault) {
      if (ch === 's') {
        return runSetup()
      }

      if (ch === 'r') {
        return load(true)
      }

      return
    }

    if (ch === 'r') {
      return load(true)
    }

    if (ch === 'n') {
      return setPrompt({ mode: 'create', value: '' })
    }

    if (!notes.length) {
      return
    }

    if (ch === 'c') {
      return setPrompt({ mode: 'comment', value: '' })
    }

    if (ch === 'e') {
      return enterEdit()
    }

    if (ch === 'a') {
      return askAgent()
    }

    // Section navigation (middle outline): [ previous, ] next.
    if (ch === '[') {
      return stepSection(-1)
    }

    if (ch === ']') {
      return stepSection(1)
    }

    // Wikilink focus (in-document): Tab cycles links, Enter opens the focused
    // one. Clicking a link works too — each is its own hit-target.
    if (key.tab) {
      return focusLink(key.shift ? -1 : 1)
    }

    if (key.return) {
      return openFocusedLink()
    }

    // List navigation (left): arrows / jk.
    if (key.upArrow || ch === 'k') {
      return move(-1)
    }

    if (key.downArrow || ch === 'j') {
      return move(1)
    }

    // Document scroll (right): PgUp/PgDn, space, ctrl-u/d, wheel — no focus to switch.
    if (key.pageDown || ch === ' ' || (key.ctrl && ch === 'd') || key.wheelDown) {
      return docScrollRef.current?.scrollBy(pageSize)
    }

    if (key.pageUp || (key.ctrl && ch === 'u') || key.wheelUp) {
      return docScrollRef.current?.scrollBy(-pageSize)
    }

    if (ch === 'g') {
      return docScrollRef.current?.scrollTo(0)
    }

    if (ch === 'G') {
      return docScrollRef.current?.scrollToBottom?.()
    }
  })

  const { body: docBody, tags: docTags } = doc?.content ? splitFrontmatter(doc.content) : { body: '', tags: '' }
  const listW = Math.max(18, Math.min(34, Math.floor(cols * 0.22)))
  // The outline column only shows while reading (the editor takes the full pane).
  const outlineW = editing ? 0 : Math.max(16, Math.min(30, Math.floor(cols * 0.2)))
  const docWidth = Math.max(30, cols - listW - outlineW - (outlineW ? 10 : 6))

  // Editor render data: lines + a block cursor at (cursorRow, cursorCol).
  const editLines = editText.split('\n')
  const editBefore = editText.slice(0, editCursor)
  const cursorRow = editBefore.split('\n').length - 1
  const cursorCol = editBefore.length - (editBefore.lastIndexOf('\n') + 1)

  // Render one editor line with markdown syntax highlighting, splicing in the
  // block cursor at `col` (a single inverse cell) when this is the active row.
  const renderEditorLine = (line: string, col: number | null): ReactNode => {
    const segs = highlightMarkdownLine(line, t)
    const out: ReactNode[] = []
    let at = 0

    for (const s of segs) {
      const end = at + s.text.length

      if (col === null || col < at || col >= end) {
        out.push(
          <Text bold={s.bold} color={s.color} dimColor={s.dim} italic={s.italic} key={out.length} underline={s.underline}>
            {s.text}
          </Text>
        )
      } else {
        // The cursor falls inside this run — split it around the cursor cell.
        const rel = col - at
        const common = { bold: s.bold, color: s.color, dimColor: s.dim, italic: s.italic, underline: s.underline }

        if (rel > 0) {
          out.push(
            <Text {...common} key={out.length}>
              {s.text.slice(0, rel)}
            </Text>
          )
        }

        out.push(
          <Text inverse key={out.length}>
            {s.text.slice(rel, rel + 1)}
          </Text>
        )
        out.push(
          <Text {...common} key={out.length}>
            {s.text.slice(rel + 1)}
          </Text>
        )
      }

      at = end
    }

    // Cursor at end-of-line: trailing inverse space so it stays visible.
    if (col !== null && col >= line.length) {
      out.push(
        <Text inverse key={out.length}>
          {' '}
        </Text>
      )
    }

    return (
      <Text wrap="truncate-end">{out.length ? out : ' '}</Text>
    )
  }

  // Split the body into heading-delimited sections so the content renders as
  // per-section blocks (each ref'd for scroll-to) and the outline can navigate.
  const sections = splitSections(docBody)
  const headings = sections.map((s, i) => ({ ...s, i })).filter(s => s.title)
  const activeHeadingPos = headings.findIndex(h => h.i === activeSection)

  const scrollToSection = (sectionIndex: number) => {
    setActiveSection(sectionIndex)
    const el = sectionRefs.current[sectionIndex]

    if (el) {
      docScrollRef.current?.scrollToElement?.(el, 0)
    }
  }

  const stepSection = (dir: -1 | 1) => {
    if (!headings.length) {
      return
    }

    const pos = activeHeadingPos < 0 ? 0 : activeHeadingPos
    const next = headings[Math.max(0, Math.min(headings.length - 1, pos + dir))]

    if (next) {
      scrollToSection(next.i)
    }
  }

  // Ordered [[wikilinks]] in the body (document order), each tagged with its
  // section and whether it resolves — the model behind keyboard focus (Tab)
  // and the inline highlight. The same INLINE_RE the markdown renderer uses,
  // so indices line up with what Md highlights.
  const docLinks: { rel?: string; section: number; target: string }[] = []
  const sectionLinkBase: number[] = []

  sections.forEach((sec, si) => {
    sectionLinkBase[si] = docLinks.length

    for (const m of sec.text.matchAll(INLINE_RE)) {
      if (m[19]) {
        docLinks.push({ rel: resolveTarget(m[19]), section: si, target: m[19] })
      }
    }
  })

  const focusLink = (dir: -1 | 1) => {
    if (!docLinks.length) {
      return
    }

    const next =
      focusedLink < 0
        ? dir > 0
          ? 0
          : docLinks.length - 1
        : (focusedLink + dir + docLinks.length) % docLinks.length

    setFocusedLink(next)
    scrollToSection(docLinks[next]!.section)
  }

  const openFocusedLink = () => {
    const link = focusedLink >= 0 ? docLinks[focusedLink] : undefined

    if (link?.rel) {
      jumpTo(link.rel)
    } else if (link) {
      setFlash(`unresolved link: ${wikiLinkLabel(link.target)}`)
    }
  }

  let body

  if (loading && !data) {
    body = <Text color={t.color.muted}>Loading vault…</Text>
  } else if (error) {
    body = (
      <Box flexDirection="column">
        <Text color={t.color.error}>Failed to load vault: {error}</Text>
        <Text color={t.color.muted}>Press r to retry · q to close</Text>
      </Box>
    )
  } else if (!hasVault) {
    body = (
      <Box flexDirection="column">
        <Text color={t.color.warn} wrap="wrap">
          No Obsidian vault connected yet.
        </Text>
        <Box marginTop={1}>
          <Text color={t.color.text} wrap="wrap">
            Press{' '}
            <Text bold color={t.color.primary}>
              s
            </Text>{' '}
            to set one up. The desk will create a vault and seed it with a starter forecasting
            knowledge base — the art of superforecasting, a getting-started guide, the core methods,
            and a question-dossier template, all wikilinked into an index.
          </Text>
        </Box>
        <Box marginTop={1}>
          <Text color={t.color.muted} wrap="wrap">
            Created at ~/Documents/Obsidian Vault by default; set OBSIDIAN_VAULT_PATH first to choose
            a different location.
          </Text>
        </Box>
      </Box>
    )
  } else if (notes.length === 0) {
    body = (
      <Text color={t.color.muted} wrap="wrap">
        Vault is connected but has no notes yet — press n to create one, or ask the desk to sync
        learnings.
      </Text>
    )
  } else {
    body = (
      <Box flexDirection="row" flexGrow={1} flexShrink={1} minHeight={0}>
        {/* Left: note list */}
        <Box flexDirection="column" flexShrink={0} marginRight={2} width={listW}>
          <Text bold color={t.color.label} wrap="truncate-end">
            {`Notes (${notes.length})`}
          </Text>
          <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1} ref={listScrollRef}>
            {notes.map((note, i) => {
              const sel = i === selected

              return (
                <Box
                  key={note.rel_path ?? i}
                  onClick={(event: { cellIsBlank?: boolean; stopPropagation?: () => void }) => {
                    if (event.cellIsBlank || editing) {
                      return
                    }

                    event.stopPropagation?.()
                    setSelected(i)
                  }}
                >
                  <Text color={sel ? t.color.primary : t.color.muted}>{sel ? '▸ ' : '  '}</Text>
                  <Text bold={sel} color={sel ? t.color.text : t.color.muted} wrap="truncate-end">
                    {truncate(note.title || note.rel_path || '—', listW - 3)}
                  </Text>
                </Box>
              )
            })}
          </ScrollBox>
        </Box>

        {/* Middle: outline (markdown headings) */}
        {!editing && outlineW > 0 ? (
          <Box flexDirection="column" flexShrink={0} marginRight={2} width={outlineW}>
            <Text bold color={t.color.label} wrap="truncate-end">
              Outline
            </Text>
            <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1}>
              {headings.length > 0 ? (
                headings.map(h => {
                  const on = h.i === activeSection
                  const indent = '  '.repeat(Math.max(0, h.level - 1))

                  return (
                    <Box
                      key={h.i}
                      onClick={(event: { cellIsBlank?: boolean; stopPropagation?: () => void }) => {
                        if (event.cellIsBlank) {
                          return
                        }

                        event.stopPropagation?.()
                        scrollToSection(h.i)
                      }}
                    >
                      <Text color={on ? t.color.primary : t.color.muted}>{`${indent}${on ? '▸ ' : '  '}`}</Text>
                      <Text bold={on} color={on ? t.color.text : t.color.muted} wrap="truncate-end">
                        {truncate(h.title, outlineW - indent.length - 4)}
                      </Text>
                    </Box>
                  )
                })
              ) : (
                <Text color={t.color.muted}>no sections</Text>
              )}
            </ScrollBox>
          </Box>
        ) : null}

        {/* Right: selected note */}
        <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
          <Text bold color={t.color.label} wrap="truncate-end">
            {truncate(currentRel ?? 'no note', docWidth)}
          </Text>
          {docTags ? (
            <Text color={t.color.muted} wrap="truncate-end">
              {truncate(docTags, docWidth)}
            </Text>
          ) : null}
          <Box flexDirection="row" flexGrow={1} flexShrink={1} minHeight={0}>
            <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1} ref={docScrollRef}>
              <Box flexDirection="column" paddingBottom={3} paddingRight={1}>
                {editing ? (
                  <Box flexDirection="column">
                    {editLines.map((line, i) => (
                      <Box key={i}>{renderEditorLine(line, i === cursorRow ? cursorCol : null)}</Box>
                    ))}
                  </Box>
                ) : (
                  <>
                {docLoading ? (
                  <Text color={t.color.muted}>Loading…</Text>
                ) : docError ? (
                  <Text color={t.color.error} wrap="wrap">
                    {docError}
                  </Text>
                ) : docBody ? (
                  sections.map((sec, i) => (
                    <Box
                       
                      flexDirection="column"
                      key={i}
                      ref={(el: any) => {
                        sectionRefs.current[i] = el
                      }}
                    >
                      <Md
                        activeWikiLink={
                          focusedLink >= 0 && docLinks[focusedLink]?.section === i
                            ? focusedLink - sectionLinkBase[i]!
                            : undefined
                        }
                        cols={docWidth}
                        onWikiLink={(target: string) => jumpTo(resolveTarget(target))}
                        t={t}
                        text={sec.text}
                      />
                    </Box>
                  ))
                ) : (
                  <Text color={t.color.muted}>Select a note to read it.</Text>
                )}
                {doc?.truncated ? (
                  <Text color={t.color.muted}>{'\n… (truncated — open in Obsidian for the rest)'}</Text>
                ) : null}

                {outgoing.length > 0 ? (
                  <Box flexDirection="column" marginTop={1}>
                    <Text>
                      <Text bold color={t.color.accent}>
                        Links
                      </Text>
                      <Text color={t.color.muted}> · click to open</Text>
                    </Text>
                    {outgoing.map((link, i) => (
                      <Box
                        key={`${link.name}-${i}`}
                        onClick={(event: { cellIsBlank?: boolean; stopPropagation?: () => void }) => {
                          if (event.cellIsBlank || !link.rel) {
                            return
                          }

                          event.stopPropagation?.()
                          jumpTo(link.rel)
                        }}
                      >
                        <Text color={link.rel ? t.color.primary : t.color.muted}>{link.rel ? '↗ ' : '× '}</Text>
                        <Text color={link.rel ? t.color.primary : t.color.muted} underline={Boolean(link.rel)} wrap="truncate-end">
                          {truncate(link.name, docWidth - 6)}
                        </Text>
                        {!link.rel ? <Text color={t.color.muted}> (unresolved)</Text> : null}
                      </Box>
                    ))}
                  </Box>
                ) : null}

                {backlinks.length > 0 ? (
                  <Box flexDirection="column" marginTop={1}>
                    <Text bold color={t.color.accent}>
                      Backlinks
                    </Text>
                    {backlinks.map((note, i) => (
                      <Box
                        key={note.rel_path ?? i}
                        onClick={(event: { cellIsBlank?: boolean; stopPropagation?: () => void }) => {
                          if (event.cellIsBlank) {
                            return
                          }

                          event.stopPropagation?.()
                          jumpTo(note.rel_path)
                        }}
                      >
                        <Text color={t.color.primary}>↩ </Text>
                        <Text color={t.color.primary} underline wrap="truncate-end">
                          {truncate(note.title || note.rel_path || '—', docWidth - 6)}
                        </Text>
                      </Box>
                    ))}
                  </Box>
                ) : null}
                  </>
                )}
              </Box>
            </ScrollBox>
            <NoSelect flexShrink={0} marginLeft={1}>
              <OverlayScrollbar scrollRef={docScrollRef} t={t} tick={now} />
            </NoSelect>
          </Box>
        </Box>
      </Box>
    )
  }

  const header = (
    <Box flexDirection="column" flexShrink={0} marginBottom={1}>
      <Text wrap="truncate-end">
        <Text bold color={t.color.primary}>
          OBSIDIAN
        </Text>
        <Text color={t.color.muted}>{'   '}</Text>
        {hasVault ? (
          <>
            <Text color={t.color.text}>{data?.count ?? notes.length}</Text>
            <Text color={t.color.muted}> notes</Text>
          </>
        ) : (
          <Text color={t.color.muted}>not connected</Text>
        )}
      </Text>
      {hasVault && data?.vault ? (
        <Text color={t.color.muted} wrap="truncate-end">
          {truncate(data.vault, cols - 2)}
        </Text>
      ) : null}
    </Box>
  )

  // Clickable action bar — mirrors the hotkeys so it is obvious (and
  // mouse-reachable) what you can do. Contextual to the current state.
  type Action = { k: string; label: string; run: () => void }

  const actions: Action[] = !hasVault
    ? [{ k: 's', label: 'Set up vault', run: runSetup }]
    : notes.length === 0
      ? [{ k: 'n', label: 'New note', run: () => setPrompt({ mode: 'create', value: '' }) }]
      : [
          { k: 'e', label: 'Edit', run: enterEdit },
          { k: 'n', label: 'New', run: () => setPrompt({ mode: 'create', value: '' }) },
          { k: 'c', label: 'Comment', run: () => setPrompt({ mode: 'comment', value: '' }) },
          { k: 'a', label: 'Ask desk', run: askAgent },
          { k: 'r', label: 'Refresh', run: () => load(true) }
        ]

  actions.push({ k: 'q', label: 'Close', run: onClose })

  const onActionClick =
    (run: () => void) => (event: { cellIsBlank?: boolean; stopPropagation?: () => void }) => {
      if (event.cellIsBlank) {
        return
      }

      event.stopPropagation?.()
      run()
    }

  const saveLabel =
    saveState === 'saving'
      ? 'saving…'
      : saveState === 'saved'
        ? 'saved'
        : saveState === 'error'
          ? 'save failed'
          : dirtyRef.current
            ? 'modified'
            : ''

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      {editing ? (
        <>
          <Box>
            <Box marginRight={2} onClick={onActionClick(exitEdit)}>
              <Text color={t.color.muted}>[</Text>
              <Text bold color={t.color.accent}>
                {'⎋'}
              </Text>
              <Text color={t.color.label}>{' Save & exit'}</Text>
              <Text color={t.color.muted}>]</Text>
            </Box>
            {saveLabel ? (
              <Text color={saveState === 'error' ? t.color.error : t.color.muted}>{saveLabel}</Text>
            ) : null}
          </Box>
          <Text color={t.color.muted} wrap="truncate-end">
            editing · arrows move · ⏎ newline · ⌃S save now · autosaves
          </Text>
        </>
      ) : prompt ? (
        <Text wrap="truncate-end">
          <Text color={t.color.primary}>
            {prompt.mode === 'create'
              ? 'new note path (folders created, e.g. Topic/Note): '
              : `comment on “${sections[activeSection]?.title || 'note'}”: `}
          </Text>
          <Text color={t.color.text}>{prompt.value}</Text>
          <Text color={t.color.text} inverse>
            {' '}
          </Text>
          <Text color={t.color.muted}>{'  ⏎ submit · Esc cancel'}</Text>
        </Text>
      ) : (
        <>
          {flash ? <Text color={t.color.accent}>{flash}</Text> : null}
          <Box>
            {actions.map(action => (
              <Box key={action.k} marginRight={2} onClick={onActionClick(action.run)}>
                <Text color={t.color.muted}>[</Text>
                <Text bold color={t.color.accent}>
                  {action.k}
                </Text>
                <Text color={t.color.label}>{` ${action.label}`}</Text>
                <Text color={t.color.muted}>]</Text>
              </Box>
            ))}
          </Box>
          {hasVault && notes.length > 0 ? (
            <Text color={t.color.muted} wrap="truncate-end">
              ↑↓ select · [ ] section · Tab link · ⏎ open · click links/headings · Space scroll
            </Text>
          ) : null}
        </>
      )}
    </Box>
  )

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      {body}
      {footer}
    </Box>
  )
}
