import { Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text, useInput, useStdout } from '@hermes/ink'
import { type ReactNode, useEffect, useRef, useState } from 'react'

import { patchOverlayState } from '../app/overlayStore.js'
import type { GatewayClient } from '../gatewayClient.js'
import type {
  ObsidianNote,
  ObsidianNoteResponse,
  ObsidianSearchResponse,
  ObsidianSearchResult,
  ObsidianStatusResponse
} from '../gatewayTypes.js'
import { highlightMarkdownLine } from '../lib/markdownEditorHighlight.js'
import { getOverlayCache, setOverlayCache } from '../lib/overlayCache.js'
import { asRpcResult } from '../lib/rpc.js'
import type { Theme } from '../theme.js'

import { OverlayScrollbar } from './agentsOverlay.js'
import { INLINE_RE, Md, stripInlineMarkup, wikiLinkLabel } from './markdown.js'

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

// A renderable unit of the document with its source line range (1-based,
// inclusive). Headings and fenced code are their own blocks; runs of prose /
// list lines group together; blank lines are non-selectable spacers. The
// reading cursor moves over the non-blank blocks and comments cite their lines.
interface DocBlock {
  end: number
  kind: 'blank' | 'block' | 'heading'
  level: number
  start: number
  text: string
  title: string
}

export const buildBlocks = (body: string): DocBlock[] => {
  const lines = body.split('\n')
  const out: DocBlock[] = []
  let i = 0

  const push = (start: number, end: number, text: string, kind: DocBlock['kind'] = 'block', level = 0, title = '') =>
    out.push({ end, kind, level, start, text, title })

  const isFence = (l: string) => /^\s*(```|~~~)/.test(l)
  // A table is a row containing a pipe immediately followed by a divider row.
  const isDivider = (l: string) => l.includes('-') && /^\s*\|?[\s:|-]+\|?\s*$/.test(l)

  while (i < lines.length) {
    const line = lines[i]!
    const ln = i + 1

    // Fenced code — one block (so the fence renders as a unit).
    if (isFence(line)) {
      const buf = [line]
      i++

      while (i < lines.length) {
        buf.push(lines[i]!)
        const closed = isFence(lines[i]!)
        i++

        if (closed) {
          break
        }
      }

      push(ln, ln + buf.length - 1, buf.join('\n'))

      continue
    }

    // Display math block ($$ … $$ / \[ … \]) — one block.
    if (/^\s*(\$\$|\\\[)/.test(line)) {
      const buf = [line]
      const closesHere = /(\$\$|\\\])\s*$/.test(line.replace(/^\s*(\$\$|\\\[)/, ''))
      i++

      if (!closesHere) {
        while (i < lines.length) {
          buf.push(lines[i]!)
          const closed = /(\$\$|\\\])\s*$/.test(lines[i]!)
          i++

          if (closed) {
            break
          }
        }
      }

      push(ln, ln + buf.length - 1, buf.join('\n'))

      continue
    }

    // Table — one block so Md sees the header + divider together.
    if (line.includes('|') && i + 1 < lines.length && isDivider(lines[i + 1]!)) {
      const buf = [line]
      i++

      while (i < lines.length && lines[i]!.includes('|') && lines[i]!.trim()) {
        buf.push(lines[i]!)
        i++
      }

      push(ln, ln + buf.length - 1, buf.join('\n'))

      continue
    }

    if (!line.trim()) {
      push(ln, ln, '', 'blank')
      i++

      continue
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line)

    if (heading) {
      push(ln, ln, line, 'heading', heading[1]!.length, heading[2]!.trim())
      i++

      continue
    }

    // Everything else: ONE block per source line, so the reading cursor moves
    // and comments anchor line-by-line (no skipping over a paragraph).
    push(ln, ln, line)
    i++
  }

  return out
}

// ── Notes directory tree ─────────────────────────────────────────────────
// The note list is grouped by folder so the vault reads as a directory tree
// you can drill into. Folders collapse/expand (a folder is expanded unless its
// path is in the `collapsed` set, so newly-synced folders show by default).
interface TreeRow {
  depth: number
  expanded: boolean
  kind: 'folder' | 'note'
  name: string
  noteIndex: number
  path: string
}

interface TreeNode {
  children: Map<string, TreeNode>
  name: string
  noteIndex: number
  path: string
}

export const buildNoteRows = (notes: ObsidianNote[], collapsed: Set<string>): TreeRow[] => {
  const root: TreeNode = { children: new Map(), name: '', noteIndex: -1, path: '' }

  notes.forEach((note, idx) => {
    const rel = note.rel_path ?? ''
    const parts = rel.split('/').filter(Boolean)

    if (!parts.length) {
      return
    }

    let cur = root
    let acc = ''

    for (let d = 0; d < parts.length - 1; d++) {
      acc = acc ? `${acc}/${parts[d]}` : parts[d]!
      let child = cur.children.get(parts[d]!)

      if (!child) {
        child = { children: new Map(), name: parts[d]!, noteIndex: -1, path: acc }
        cur.children.set(parts[d]!, child)
      }

      cur = child
    }

    const leaf = parts[parts.length - 1]!
    cur.children.set(`note:${idx}`, {
      children: new Map(),
      name: note.title || leaf.replace(/\.md$/i, ''),
      noteIndex: idx,
      path: rel
    })
  })

  const rows: TreeRow[] = []

  const walk = (node: TreeNode, depth: number) => {
    const entries = [...node.children.values()]
    const folders = entries.filter(e => e.noteIndex < 0).sort((a, b) => a.name.localeCompare(b.name))
    const leaves = entries.filter(e => e.noteIndex >= 0).sort((a, b) => a.name.localeCompare(b.name))

    for (const f of folders) {
      const expanded = !collapsed.has(f.path)
      rows.push({ depth, expanded, kind: 'folder', name: f.name, noteIndex: -1, path: f.path })

      if (expanded) {
        walk(f, depth + 1)
      }
    }

    for (const l of leaves) {
      rows.push({ depth, expanded: false, kind: 'note', name: l.name, noteIndex: l.noteIndex, path: l.path })
    }
  }

  walk(root, 0)

  return rows
}

// Every folder path in the vault (each directory prefix of a note's rel_path).
// Used to start the tree fully collapsed so the vault is easy to navigate.
export const allFolderPaths = (notes: ObsidianNote[]): string[] => {
  const set = new Set<string>()

  for (const note of notes) {
    const parts = (note.rel_path ?? '').split('/').filter(Boolean)
    let acc = ''

    for (let d = 0; d < parts.length - 1; d++) {
      acc = acc ? `${acc}/${parts[d]}` : parts[d]!
      set.add(acc)
    }
  }

  return [...set]
}

// Comments live in a managed block at the foot of the note (kept out of the
// prose) and are shown in a right-hand rail, each anchored to a section so it
// reads like a margin note linked to that part of the doc.
interface DocComment {
  anchor: string
  text: string
}

const COMMENTS_RE = /\n*<!-- comments:begin -->\n([\s\S]*?)\n<!-- comments:end -->\s*$/

// Strip the managed comments block off the body and parse its entries. The
// returned body is what gets rendered/sectioned; the comments feed the rail.
export const splitComments = (body: string): { body: string; comments: DocComment[] } => {
  const m = COMMENTS_RE.exec(body)

  if (!m) {
    return { body, comments: [] }
  }

  const comments: DocComment[] = []
  let cur: DocComment | null = null

  for (const line of m[1]!.split('\n')) {
    const a = /^@@ (.*)$/.exec(line)

    if (a) {
      if (cur) {
        comments.push(cur)
      }

      cur = { anchor: a[1]!.trim(), text: '' }
    } else if (cur) {
      cur.text += (cur.text ? '\n' : '') + line
    }
  }

  if (cur) {
    comments.push(cur)
  }

  return {
    body: body.slice(0, m.index).replace(/\n+$/, ''),
    comments: comments.map(c => ({ ...c, text: c.text.trim() })).filter(c => c.text)
  }
}

const serializeComments = (comments: DocComment[]): string =>
  comments.length
    ? `<!-- comments:begin -->\n${comments.map(c => `@@ ${c.anchor}\n${c.text}`).join('\n')}\n<!-- comments:end -->`
    : ''

// Append a comment anchored to `anchor`, rewriting the managed block.
export const addComment = (fullContent: string, anchor: string, text: string): string => {
  const { body } = splitFrontmatter(fullContent)
  const fm = fullContent.slice(0, fullContent.length - body.length)
  const { body: clean, comments } = splitComments(body)

  comments.push({ anchor, text })

  return `${fm}${clean.replace(/\n+$/, '')}\n\n${serializeComments(comments)}\n`
}

type PromptMode = 'comment' | 'create'

interface ObsidianViewProps {
  docKind?: 'latex' | 'markdown' // when inside the Docs view: which kind tab is active
  gw: GatewayClient
  onClose: () => void
  onDraft?: (command: string) => void
  onSelectKind?: (kind: 'latex' | 'markdown') => void // switch Docs kind (Markdown↔LaTeX)
  sid?: null | string
  t: Theme
}

interface ChatTurn {
  role: 'assistant' | 'system' | 'user'
  text: string
}

interface ChatTodo {
  done: boolean
  text: string
}

interface ChatState {
  busy: boolean
  confirmSave: boolean
  input: string
  status: string
  stream: string
  todos: ChatTodo[]
  turns: ChatTurn[]
}

// Playful words for the "agent is working" status, cycled by the tick so it
// reads as alive even before the first concrete event arrives.
const THINKING_WORDS = ['thinking', 'pondering', 'reasoning', 'mulling', 'cooking', 'scheming', 'noodling']
const SPINNER = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

export function ObsidianView({ docKind, gw, onClose, onDraft, onSelectKind, sid, t }: ObsidianViewProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24

  // Render the last known vault immediately on reopen, then refresh in the
  // background — reopening should feel instant, not flash a loading screen.
  const [data, setData] = useState<ObsidianStatusResponse | null>(
    () => getOverlayCache<ObsidianStatusResponse>('obsidian.status') ?? null
  )

  const [loading, setLoading] = useState(!data)
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
  const [cursor, setCursor] = useState(0)
  const [selAnchor, setSelAnchor] = useState(-1)
  const [focusedLink, setFocusedLink] = useState(-1)
  // Which pane the arrow keys drive: ←/→ move focus between notes ↔ outline ↔
  // doc; ↑/↓ then navigate within the focused pane.
  const [focus, setFocus] = useState<'doc' | 'list' | 'outline'>('doc')
  // Collapsed folder paths in the notes tree, and the tree cursor row.
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [listIdx, setListIdx] = useState(0)
  // Start the tree fully collapsed (once, on first load) so the vault is easy
  // to navigate; later user expansions persist.
  const collapsedInit = useRef(false)
  // Debounce list-cursor previews: arrowing through Notes shouldn't reload +
  // repaint the doc on every step (that flashes) — only after the cursor settles.
  const previewTimer = useRef<null | ReturnType<typeof setTimeout>>(null)

  const [search, setSearch] = useState<null | {
    loading: boolean
    query: string
    results: ObsidianSearchResult[]
    sel: number
  }>(null)

  const [chat, setChat] = useState<ChatState | null>(null)
  const [spin, setSpin] = useState(0)

  const dirtyRef = useRef(false)
  // Cursor source-of-truth for the editor. State (editCursor) drives the
  // render; the ref stays synchronously correct so rapid inserts (e.g. holding
  // Enter) splice at the right position even when React batches the updates.
  const editCursorRef = useRef(0)
  const saveTimer = useRef<null | ReturnType<typeof setTimeout>>(null)
  const listScrollRef = useRef<null | ScrollBoxHandle>(null)
  const docScrollRef = useRef<null | ScrollBoxHandle>(null)
   
  const blockRefs = useRef<any[]>([])

  const notes: ObsidianNote[] = data?.notes ?? []
  const hasVault = Boolean(data?.exists && data?.vault)
  const currentRel = notes[selected]?.rel_path

  // Collapse every folder on the first load so the vault opens as a tidy list
  // of top-level directories to drill into, not a fully-expanded dump.
  useEffect(() => {
    if (!collapsedInit.current && notes.length) {
      collapsedInit.current = true
      setCollapsed(new Set(allFolderPaths(notes)))
    }
  }, [notes])

  // Clear any pending preview load when the view unmounts.
  useEffect(() => () => {
    if (previewTimer.current) {
      clearTimeout(previewTimer.current)
    }
  }, [])

  // The notes pane as a directory tree (folders collapse/expand).
  const noteRows = buildNoteRows(notes, collapsed)

  const toggleFolder = (path: string) =>
    setCollapsed(s => {
      const next = new Set(s)
      next.has(path) ? next.delete(path) : next.add(path)

      return next
    })

  // Move the tree cursor (list focus). Folders just highlight; Enter toggles
  // them, Enter on a note opens it. Moving onto a note also live-previews it so
  // the doc viewer AND the Outline pane follow the cursor — but the load is
  // debounced (only after the cursor settles) so holding ↓ doesn't reload and
  // repaint the doc on every step, which flashes.
  const listMove = (dir: -1 | 1) => {
    if (!noteRows.length) {
      return
    }

    const next = Math.max(0, Math.min(noteRows.length - 1, listIdx + dir))

    setListIdx(next)

    const row = noteRows[next]

    if (previewTimer.current) {
      clearTimeout(previewTimer.current)
      previewTimer.current = null
    }

    if (row && row.kind !== 'folder') {
      previewTimer.current = setTimeout(() => {
        previewTimer.current = null
        setSelected(row.noteIndex)
      }, 120)
    }
  }

  const listActivate = () => {
    const row = noteRows[listIdx]

    if (!row) {
      return
    }

    // Cancel a pending debounced preview — Enter is an explicit, immediate open.
    if (previewTimer.current) {
      clearTimeout(previewTimer.current)
      previewTimer.current = null
    }

    if (row.kind === 'folder') {
      toggleFolder(row.path)
    } else {
      setSelected(row.noteIndex)
      setFocus('doc')
    }
  }

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

  const runSearch = (query: string) => {
    gw.request<unknown>('obsidian.search', { limit: 30, query })
      .then(raw => {
        const res = asRpcResult<ObsidianSearchResponse>(raw)
        setSearch(s => (s && s.query === query ? { ...s, loading: false, results: res?.results ?? [], sel: 0 } : s))
      })
      .catch(() => setSearch(s => (s ? { ...s, loading: false } : s)))
  }

  const openSearchResult = (rel?: string) => {
    if (rel) {
      jumpTo(rel)
    }

    setSearch(null)
  }

  const load = (announce = false) => {
    // Only show the loading screen when we have nothing cached to show.
    setLoading(!data)
    gw.request<unknown>('obsidian.status', { limit: 200 })
      .then(raw => {
        const result = asRpcResult<ObsidianStatusResponse>(raw)

        if (!result) {
          setError('obsidian.status returned no data')
          setLoading(false)

          return
        }

        setOverlayCache('obsidian.status', result)
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

  // Open the in-Obsidian chat modal — talk to the desk without leaving the
  // vault. The agent shares the main session, so the exchange also lands in
  // the main transcript.
  const askAgent = () => {
    setChat({ busy: false, confirmSave: false, input: '', status: '', stream: '', todos: [], turns: [] })
  }

  const sendChat = (raw: string) => {
    const text = raw.trim()

    if (!text) {
      return
    }

    const context = currentRel ? `(About the Obsidian note "${currentRel}".)\n\n` : ''

    setChat(c =>
      c ? { ...c, busy: true, input: '', status: 'sending', stream: '', todos: [], turns: [...c.turns, { role: 'user', text }] } : c
    )
    gw.request<unknown>('prompt.submit', { session_id: sid ?? 'default', text: `${context}${text}` }).catch(
      (err: unknown) => {
        setChat(c =>
          c
            ? {
                ...c,
                busy: false,
                status: '',
                turns: [...c.turns, { role: 'system', text: `couldn't reach the desk: ${String(err)}` }]
              }
            : c
        )
      }
    )
  }

  // Esc out of chat: if the open note has unsaved edits, confirm first.
  // Otherwise just close the modal and return the reader to exactly where they
  // were — no reload (that would reset scroll/cursor to the top). Press r to
  // pull in any edits the desk made on disk.
  const closeChat = () => {
    if (dirtyRef.current && editing) {
      setChat(c => (c ? { ...c, confirmSave: true } : c))

      return
    }

    setChat(null)
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
    editCursorRef.current = text.length
    setEditCursor(text.length)
    dirtyRef.current = false
    setSaveState('idle')
    setEditing(true)
  }

  // Move the editor cursor to an absolute position (keeps ref + state in sync).
  const setCur = (next: number) => {
    editCursorRef.current = Math.max(0, next)
    setEditCursor(editCursorRef.current)
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

  // Edit primitives splice at editCursorRef (synchronously correct) so batched
  // keystrokes don't all splice at the same stale position.
  const editInsert = (s: string) => {
    const at = editCursorRef.current
    editCursorRef.current = at + s.length
    setEditText(text => text.slice(0, at) + s + text.slice(at))
    setEditCursor(editCursorRef.current)
    dirtyRef.current = true
    setSaveState('idle')
  }

  const editBackspace = () => {
    const at = editCursorRef.current

    if (at <= 0) {
      return
    }

    editCursorRef.current = at - 1
    setEditText(text => text.slice(0, at - 1) + text.slice(at))
    setEditCursor(editCursorRef.current)
    dirtyRef.current = true
    setSaveState('idle')
  }

  const editMoveLine = (dir: -1 | 1) => {
    const at = editCursorRef.current
    const before = editText.slice(0, at)
    const row = before.split('\n').length - 1
    const col = before.length - (before.lastIndexOf('\n') + 1)
    const lines = editText.split('\n')
    const targetRow = Math.max(0, Math.min(lines.length - 1, row + dir))

    if (targetRow === row) {
      return
    }

    let idx = 0

    for (let i = 0; i < targetRow; i++) {
      idx += lines[i]!.length + 1
    }

    setCur(idx + Math.min(col, lines[targetRow]!.length))
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

    // comment → anchored to the active section, stored in the managed block
    // and shown in the right-hand rail (kept out of the prose).
    if (!currentRel || !doc?.content) {
      return
    }

    const anchor = selSnippet ? `${lineRef} ¦ ${selSnippet}` : lineRef
    const next = addComment(doc.content, anchor, value)
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
    setCursor(0)
    setSelAnchor(-1)
    setFocusedLink(-1)
  }, [doc])

  // Live search: debounce the query so we don't hit the gateway per keystroke.
  const searchQuery = search?.query ?? ''
  const searchOpen = search !== null
  useEffect(() => {
    if (!searchOpen || !searchQuery.trim()) {
      return
    }

    const id = setTimeout(() => runSearch(searchQuery), 200)

    return () => clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQuery, searchOpen])

  // While the chat modal is open, mirror the agent's reply into it. The desk
  // shares the main session, so we listen to the same gateway event stream and
  // pick up the final assistant text (and errors) for our session.
  const chatOpen = chat !== null
  useEffect(() => {
    if (!chatOpen) {
      return
    }

     
    const parseTodos = (raw: any): ChatTodo[] | undefined =>
      Array.isArray(raw)
        ?  
          raw.map((td: any) => ({
            done: td?.status === 'completed',
            text: String(td?.content ?? td?.text ?? td?.subject ?? '').trim()
          }))
        : undefined

     
    const handler = (ev: any) => {
      if (ev.session_id && sid && ev.session_id !== sid) {
        return
      }

      const p = ev.payload ?? {}

      switch (ev.type as string) {
        case 'error':
          setChat(c =>
            c
              ? { ...c, busy: false, status: '', turns: [...c.turns, { role: 'system', text: `error: ${p.message ?? 'unknown error'}` }] }
              : c
          )

          return

        case 'message.complete':
          setChat(c => {
            if (!c) {
              return c
            }

            const text = String(p.text ?? p.rendered ?? c.stream ?? '').trim()

            return {
              ...c,
              busy: false,
              status: '',
              stream: '',
              todos: [],
              turns: text ? [...c.turns, { role: 'assistant', text }] : c.turns
            }
          })

          return

        case 'message.delta':
          setChat(c => (c ? { ...c, status: 'writing', stream: c.stream + String(p.text ?? '') } : c))

          return

        case 'message.start':
          setChat(c => (c ? { ...c, status: 'writing', stream: '' } : c))

          return

        case 'reasoning.available':

        case 'reasoning.delta':
          setChat(c => (c ? { ...c, status: 'reasoning' } : c))

          return

        case 'status.update':
          setChat(c => (c ? { ...c, status: String(p.text || p.kind || c.status) } : c))

          return

        case 'thinking.delta':
          setChat(c => (c ? { ...c, status: 'thinking' } : c))

          return

        case 'tool.complete':
          setChat(c => (c ? { ...c, status: `${p.name ?? 'tool'} ✓`, todos: parseTodos(p.todos) ?? c.todos } : c))

          return

        case 'tool.generating':
          setChat(c => (c ? { ...c, status: `drafting ${p.name ?? 'tool'}` } : c))

          return

        case 'tool.start':
          setChat(c => (c ? { ...c, status: `running ${p.name ?? 'tool'}`, todos: parseTodos(p.todos) ?? c.todos } : c))

          return
      }
    }

    gw.on('event', handler)

    return () => {
      gw.off('event', handler)
    }

  }, [chatOpen, sid, gw])

  // Animate the spinner / thinking word while the desk is working.
  const chatBusy = chat?.busy ?? false
  useEffect(() => {
    if (!chatBusy) {
      return
    }

    const id = setInterval(() => setSpin(s => s + 1), 110)

    return () => clearInterval(id)
  }, [chatBusy])

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
    listScrollRef.current?.scrollTo(Math.max(0, listIdx - 2))
  }, [listIdx])

  useEffect(() => {
    const id = setInterval(() => setNow(value => value + 1), 500)

    return () => clearInterval(id)
  }, [])

  const pageSize = Math.max(4, termRows - 12)
  const move = (delta: number) => setSelected(s => Math.max(0, Math.min(notes.length - 1, s + delta)))

  useInput((ch, key) => {
    // Chat modal captures input while open.
    if (chat) {
      if (chat.confirmSave) {
        if (ch === 'y') {
          saveNow(editText)
          setChat(null)

          return
        }

        if (ch === 'n') {
          dirtyRef.current = false
          setChat(null)

          return
        }

        if (key.escape) {
          return setChat(c => (c ? { ...c, confirmSave: false } : c))
        }

        return
      }

      if (key.escape) {
        return closeChat()
      }

      if (key.return) {
        return sendChat(chat.input)
      }

      if (key.backspace || key.delete) {
        return setChat(c => (c ? { ...c, input: c.input.slice(0, -1) } : c))
      }

      if (ch && ch.length === 1 && !key.ctrl && !key.meta) {
        return setChat(c => (c ? { ...c, input: c.input + ch } : c))
      }

      return
    }

    // Search modal captures input while open.
    if (search) {
      if (key.escape) {
        return setSearch(null)
      }

      if (key.return) {
        return openSearchResult(search.results[search.sel]?.rel_path)
      }

      if (key.upArrow) {
        return setSearch(s => (s ? { ...s, sel: Math.max(0, s.sel - 1) } : s))
      }

      if (key.downArrow) {
        return setSearch(s => (s ? { ...s, sel: Math.min(s.results.length - 1, s.sel + 1) } : s))
      }

      if (key.backspace || key.delete) {
        return setSearch(s => (s ? { ...s, query: s.query.slice(0, -1) } : s))
      }

      if (ch && ch.length === 1 && !key.ctrl && !key.meta) {
        return setSearch(s => (s ? { ...s, loading: true, query: s.query + ch } : s))
      }

      return
    }

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
        return setCur(editCursorRef.current - 1)
      }

      if (key.rightArrow) {
        return setCur(Math.min(editText.length, editCursorRef.current + 1))
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

    // Esc clears an active selection first, then closes the view.
    if (key.escape && selAnchor >= 0) {
      return setSelAnchor(-1)
    }

    if (ch === 'q' || key.escape) {
      return onClose()
    }

    // Docs kind tabs: 1 Markdown (this view) · 2 LaTeX. Only in nav mode (the
    // edit/chat/search/prompt guards above already returned).
    if (onSelectKind && (ch === '1' || ch === '2')) {
      return onSelectKind(ch === '2' ? 'latex' : 'markdown')
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

    if (ch === 's') {
      return setSearch({ loading: false, query: '', results: [], sel: 0 })
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

    // Start/stop a visual line selection at the cursor (vim-style). While
    // active, plain ↑↓/jk extend it; c then comments on the whole range.
    if (ch === 'v') {
      return toggleSelect()
    }

    // Switch notes (left list): [ previous, ] next.
    if (ch === '[') {
      return move(-1)
    }

    if (ch === ']') {
      return move(1)
    }

    // Wikilink focus (in-document): Tab cycles links, Enter opens the focused
    // one. Clicking a link works too — each is its own hit-target.
    if (key.tab) {
      return focusLink(key.shift ? -1 : 1)
    }

    // Enter: in the notes tree it toggles a folder / opens a note; in the doc
    // it follows the focused wikilink.
    if (key.return) {
      return focus === 'list' ? listActivate() : openFocusedLink()
    }

    // ←/→ move focus across panes: notes ↔ outline ↔ doc.
    if (key.leftArrow || ch === 'h') {
      return moveFocus(-1)
    }

    if (key.rightArrow || ch === 'l') {
      return moveFocus(1)
    }

    // ↑↓/jk navigate the focused pane (note list / outline / doc cursor).
    // v + ↑↓ (or Shift/J/K) extend a selection in the doc.
    if (key.upArrow || ch === 'k' || ch === 'K') {
      return navStep(-1, Boolean(key.shift) || ch === 'K')
    }

    if (key.downArrow || ch === 'j' || ch === 'J') {
      return navStep(1, Boolean(key.shift) || ch === 'J')
    }

    // Mouse wheel: small, smooth steps (a full page per tick felt janky).
    if (key.wheelDown) {
      return docScrollRef.current?.scrollBy(3)
    }

    if (key.wheelUp) {
      return docScrollRef.current?.scrollBy(-3)
    }

    // Page scroll: PgUp/PgDn, space, ctrl-u/d.
    if (key.pageDown || ch === ' ' || (key.ctrl && ch === 'd')) {
      return docScrollRef.current?.scrollBy(pageSize)
    }

    if (key.pageUp || (key.ctrl && ch === 'u')) {
      return docScrollRef.current?.scrollBy(-pageSize)
    }

    if (ch === 'g') {
      const first = blocks.findIndex(b => b.kind !== 'blank')

      return first >= 0 ? jumpCursor(first) : docScrollRef.current?.scrollTo(0)
    }

    if (ch === 'G') {
      let last = -1
      blocks.forEach((b, bi) => {
        if (b.kind !== 'blank') {
          last = bi
        }
      })

      return last >= 0 ? jumpCursor(last) : docScrollRef.current?.scrollToBottom?.()
    }
  })

  const { body: rawBody, tags: docTags } = doc?.content ? splitFrontmatter(doc.content) : { body: '', tags: '' }
  const { body: docBody, comments: docComments } = splitComments(rawBody)
  const listW = Math.max(16, Math.min(30, Math.floor(cols * 0.2)))
  // The outline column only shows while reading (the editor takes the full pane).
  const outlineW = editing ? 0 : Math.max(15, Math.min(26, Math.floor(cols * 0.17)))
  // The comments rail shows on the right when the terminal is wide enough.
  const showComments = !editing && cols >= 100
  const commentsW = showComments ? Math.max(20, Math.min(34, Math.floor(cols * 0.22))) : 0

  const docWidth = Math.max(
    24,
    cols - listW - outlineW - commentsW - 6 - (outlineW ? 2 : 0) - (commentsW ? 2 : 0)
  )

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

  // Header: the note's title (H1 / filename, never the raw path) on its own
  // line, with folder + tags as a muted subtitle beneath it.
  const docTitle =
    notes[selected]?.title || (currentRel ? (currentRel.split('/').pop() ?? '').replace(/\.md$/i, '') : 'no note')

  const docFolder = currentRel ? currentRel.split('/').slice(0, -1).join('/') : ''
  const docSubtitle = [docFolder, docTags && docTags.replace(/\s*,\s*/g, ' · ')].filter(Boolean).join('   ·   ')

  // Split the body into renderable blocks with source line ranges. A reading
  // cursor moves over these (skipping blanks); the selected range drives the
  // line references attached to comments.
  const blocks = buildBlocks(docBody)
  const headings = blocks.map((b, i) => ({ i, level: b.level, title: b.title })).filter(b => b.title)

  // Outline highlight: the heading at/above the cursor.
  const activeHeadingIdx = (() => {
    let h = -1

    for (const head of headings) {
      if (head.i <= cursor) {
        h = head.i
      }
    }

    return h
  })()

  // Scroll the cursor block into view, but ONLY when it's actually outside the
  // viewport — so the cursor moves line-by-line within the visible area and we
  // only scroll at the edges (smooth when an arrow is held), instead of
  // re-pinning the cursor to a fixed offset every move (which jumped the doc
  // and tucked the top line under the header).
  const scrollToBlock = (bi: number) => {
    const el = blockRefs.current[bi]
    const sb = docScrollRef.current

    if (!el || !sb) {
      return
    }

    const node = el.yogaNode

    if (!node) {
      sb.scrollToElement?.(el, 1)

      return
    }

    const top = node.getComputedTop()
    const height = node.getComputedHeight() || 1
    const scrollTop = sb.getScrollTop?.() ?? 0
    const viewH = sb.getViewportHeight?.() ?? 0

    if (viewH <= 0) {
      sb.scrollToElement?.(el, 1)

      return
    }

    // Nudge by exactly the overflow with a relative scroll (no anchored
    // re-layout) so holding an arrow scrolls one line at a time, smoothly.
    if (top < scrollTop) {
      sb.scrollBy?.(top - scrollTop)
    } else if (top + height > scrollTop + viewH) {
      sb.scrollBy?.(top + height - (scrollTop + viewH))
    }
    // Otherwise it's already fully visible — leave the scroll position alone.
  }

  // Move the reading cursor to the next selectable (non-blank) block. The
  // selection grows when `extend` is asked for OR a visual selection is
  // already active (selAnchor set via `v`) — so once you start selecting,
  // plain ↑↓/jk keep extending until you clear it.
  const moveCursor = (dir: -1 | 1, extend = false) => {
    let nc = cursor

    do {
      nc += dir
    } while (nc >= 0 && nc < blocks.length && blocks[nc]!.kind === 'blank')

    if (nc < 0 || nc >= blocks.length) {
      return
    }

    if (extend || selAnchor >= 0) {
      setSelAnchor(prev => (prev < 0 ? cursor : prev))
    } else {
      setSelAnchor(-1)
    }

    setCursor(nc)
    scrollToBlock(nc)
  }

  // Toggle a visual selection anchored at the current line (vim-style). While
  // active, movement extends the range; `v` again or Esc clears it.
  const toggleSelect = () => {
    setSelAnchor(prev => (prev < 0 ? cursor : -1))
  }

  const jumpCursor = (bi: number) => {
    if (bi < 0 || bi >= blocks.length) {
      return
    }

    setSelAnchor(-1)
    setCursor(bi)
    scrollToBlock(bi)
  }

  // Step the outline: jump the doc cursor to the previous/next heading.
  const stepHeading = (dir: -1 | 1) => {
    if (!headings.length) {
      return
    }

    const pos = headings.findIndex(h => h.i === activeHeadingIdx)
    const next = headings[Math.max(0, Math.min(headings.length - 1, (pos < 0 ? 0 : pos) + dir))]

    if (next) {
      jumpCursor(next.i)
    }
  }

  // ←/→ move focus across the panes; outline is skipped when it's hidden.
  const focusOrder = (): ('doc' | 'list' | 'outline')[] =>
    outlineW > 0 ? ['list', 'outline', 'doc'] : ['list', 'doc']

  const moveFocus = (dir: -1 | 1) => {
    const order = focusOrder()
    const idx = order.indexOf(focus)
    const next = order[Math.max(0, Math.min(order.length - 1, (idx < 0 ? order.length - 1 : idx) + dir))]

    if (next) {
      setFocus(next)
    }
  }

  // ↑/↓ act on the focused pane.
  const navStep = (dir: -1 | 1, extend: boolean) => {
    if (focus === 'list') {
      return listMove(dir)
    }

    if (focus === 'outline') {
      return stepHeading(dir)
    }

    return moveCursor(dir, extend)
  }

  // Current selection as a block-index range (inclusive).
  const selLo = selAnchor < 0 ? cursor : Math.min(selAnchor, cursor)
  const selHi = selAnchor < 0 ? cursor : Math.max(selAnchor, cursor)

  // Ordered [[wikilinks]] in the body, tagged with their block (for the
  // inline highlight + keyboard focus). Same INLINE_RE the renderer uses.
  const docLinks: { block: number; rel?: string; target: string }[] = []
  const blockLinkBase: number[] = []

  blocks.forEach((b, bi) => {
    blockLinkBase[bi] = docLinks.length

    if (b.kind !== 'blank') {
      for (const m of b.text.matchAll(INLINE_RE)) {
        if (m[19]) {
          docLinks.push({ block: bi, rel: resolveTarget(m[19]), target: m[19] })
        }
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
    jumpCursor(docLinks[next]!.block)
  }

  const openFocusedLink = () => {
    const link = focusedLink >= 0 ? docLinks[focusedLink] : undefined

    if (link?.rel) {
      jumpTo(link.rel)
    } else if (link) {
      setFlash(`unresolved link: ${wikiLinkLabel(link.target)}`)
    }
  }

  // The line-reference label + snippet for the current selection (what a new
  // comment anchors to).
  const selStartLine = blocks[selLo]?.start ?? 0
  const selEndLine = blocks[selHi]?.end ?? selStartLine
  const lineRef = selStartLine ? (selEndLine > selStartLine ? `L${selStartLine}-${selEndLine}` : `L${selStartLine}`) : 'note'

  const selSnippet = stripInlineMarkup((blocks[selLo]?.text ?? '').split('\n')[0] ?? '')
    .replace(/^#+\s*/, '')
    .replace(/^[-*+]\s*/, '')
    .slice(0, 42)
    .trim()

  let body

  if (search) {
    const modalW = Math.max(40, Math.min(cols - 8, 88))

    body = (
      <Box alignItems="center" flexGrow={1} justifyContent="center" minHeight={0}>
        <Box
          borderColor={t.color.accent}
          borderStyle="round"
          flexDirection="column"
          paddingX={2}
          paddingY={1}
          width={modalW}
        >
          <Text bold color={t.color.primary}>
            Search the vault
          </Text>
          <Box marginTop={1}>
            <Text color={t.color.muted}>{'🔎 '}</Text>
            <Text color={t.color.text}>{search.query}</Text>
            <Text color={t.color.text} inverse>
              {' '}
            </Text>
          </Box>
          <Box flexDirection="column" marginTop={1}>
            {!search.query.trim() ? (
              <Text color={t.color.muted}>Type to search titles, headings and content across the vault…</Text>
            ) : search.results.length === 0 ? (
              <Text color={t.color.muted}>{search.loading ? 'Searching…' : 'No matches.'}</Text>
            ) : (
              search.results.slice(0, 12).map((r, i) => {
                const on = i === search.sel
                const folder = (r.rel_path ?? '').split('/').slice(0, -1).join('/')

                return (
                  <Box
                    flexDirection="column"
                    key={r.rel_path ?? i}
                    onClick={(event: { cellIsBlank?: boolean; stopPropagation?: () => void }) => {
                      if (event.cellIsBlank) {
                        return
                      }

                      event.stopPropagation?.()
                      openSearchResult(r.rel_path)
                    }}
                  >
                    <Text wrap="truncate-end">
                      <Text color={on ? t.color.primary : t.color.muted}>{on ? '▸ ' : '  '}</Text>
                      <Text bold={on} color={on ? t.color.text : t.color.label}>
                        {truncate(r.title || r.rel_path || '—', modalW - 18)}
                      </Text>
                      {folder ? <Text color={t.color.muted}>{`  ${folder}`}</Text> : null}
                    </Text>
                    {r.snippet ? (
                      <Text color={t.color.muted} wrap="truncate-end">
                        {`    ${r.snippet}`}
                      </Text>
                    ) : null}
                  </Box>
                )
              })
            )}
          </Box>
          <Box marginTop={1}>
            <Text color={t.color.muted}>
              {search.results.length > 12
                ? `↑↓ select · ⏎ open · Esc close · ${search.results.length} matches`
                : '↑↓ select · ⏎ open · Esc close'}
            </Text>
          </Box>
        </Box>
      </Box>
    )
  } else if (loading && !data) {
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
        <Box flexDirection="column" flexShrink={0} marginRight={2} noSelect width={listW}>
          <Text bold color={focus === 'list' ? t.color.primary : t.color.label} wrap="truncate-end">
            {`${focus === 'list' ? '▸ ' : '  '}Notes (${notes.length})`}
          </Text>
          <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1} ref={listScrollRef}>
            {noteRows.map((row, ri) => {
              const onCursor = focus === 'list' && ri === listIdx
              const indent = '  '.repeat(row.depth)

              if (row.kind === 'folder') {
                return (
                  <Box
                    key={`f:${row.path}`}
                    onClick={(event: { cellIsBlank?: boolean; stopPropagation?: () => void }) => {
                      if (event.cellIsBlank || editing) {
                        return
                      }

                      event.stopPropagation?.()
                      setFocus('list')
                      setListIdx(ri)
                      toggleFolder(row.path)
                    }}
                  >
                    <Text color={onCursor ? t.color.primary : t.color.muted}>{`${indent}${row.expanded ? '▾' : '▸'} `}</Text>
                    <Text bold color={onCursor ? t.color.text : t.color.label} wrap="truncate-end">
                      {truncate(row.name, listW - indent.length - 3)}
                    </Text>
                  </Box>
                )
              }

              const sel = row.noteIndex === selected

              return (
                <Box
                  key={`n:${row.path}`}
                  onClick={(event: { cellIsBlank?: boolean; stopPropagation?: () => void }) => {
                    if (event.cellIsBlank || editing) {
                      return
                    }

                    event.stopPropagation?.()
                    setFocus('list')
                    setListIdx(ri)
                    setSelected(row.noteIndex)
                  }}
                >
                  <Text color={onCursor ? t.color.primary : sel ? t.color.accent : t.color.muted}>
                    {`${indent}${onCursor ? '▸' : sel ? '•' : ' '} `}
                  </Text>
                  <Text bold={sel || onCursor} color={sel || onCursor ? t.color.text : t.color.muted} wrap="truncate-end">
                    {truncate(row.name, listW - indent.length - 3)}
                  </Text>
                </Box>
              )
            })}
          </ScrollBox>
        </Box>

        {/* Middle: outline (markdown headings) */}
        {!editing && outlineW > 0 ? (
          <Box flexDirection="column" flexShrink={0} marginRight={2} noSelect width={outlineW}>
            <Text bold color={focus === 'outline' ? t.color.primary : t.color.label} wrap="truncate-end">
              {`${focus === 'outline' ? '▸ ' : '  '}Outline`}
            </Text>
            <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1}>
              {headings.length > 0 ? (
                headings.map(h => {
                  const on = h.i === activeHeadingIdx
                  const indent = '  '.repeat(Math.max(0, h.level - 1))

                  return (
                    <Box
                      key={h.i}
                      onClick={(event: { cellIsBlank?: boolean; stopPropagation?: () => void }) => {
                        if (event.cellIsBlank) {
                          return
                        }

                        event.stopPropagation?.()
                        setFocus('outline')
                        jumpCursor(h.i)
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
        <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0} minWidth={0}>
          {/* Header is fixed-height so it never collapses onto the body. */}
          <Box flexDirection="column" flexShrink={0}>
            <Text bold color={focus === 'doc' ? t.color.primary : t.color.text} wrap="truncate-end">
              {`${focus === 'doc' ? '▸ ' : '  '}${truncate(docTitle, docWidth - 2)}`}
            </Text>
            {docSubtitle ? (
              <Text color={t.color.muted} wrap="truncate-end">
                {truncate(docSubtitle, docWidth)}
              </Text>
            ) : null}
          </Box>
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
                {docLoading && !docBody ? (
                  // Only show the spinner on a cold load. While previewing
                  // through the list, keep the current doc on screen until the
                  // next one arrives so the reader swaps cleanly without a
                  // "Loading…" blink on every cursor move.
                  <Text color={t.color.muted}>Loading…</Text>
                ) : docError ? (
                  <Text color={t.color.error} wrap="wrap">
                    {docError}
                  </Text>
                ) : docBody ? (
                  blocks.map((b, i) => {
                    const onCursor = i >= selLo && i <= selHi

                    // Blank lines inside a selection still draw the gutter so a
                    // multi-line selection reads as one continuous bar (no gaps).
                    if (b.kind === 'blank') {
                      return (
                        <Box flexDirection="row" key={i}>
                          <Text bold={onCursor} color={onCursor ? t.color.primary : t.color.muted}>
                            {onCursor ? '▌ ' : '  '}
                          </Text>
                          <Text> </Text>
                        </Box>
                      )
                    }

                    return (
                      <Box
                        flexDirection="row"
                        key={i}
                        onClick={(event: { cellIsBlank?: boolean; stopPropagation?: () => void }) => {
                          if (event.cellIsBlank) {
                            return
                          }

                          event.stopPropagation?.()
                          setFocus('doc')
                          jumpCursor(i)
                        }}
                         
                        ref={(el: any) => {
                          blockRefs.current[i] = el
                        }}
                      >
                        <Text bold={onCursor} color={onCursor ? t.color.primary : t.color.muted}>
                          {onCursor ? '▌ ' : '  '}
                        </Text>
                        {/* Definite width + clip: Md wraps paragraphs at the
                            parent box width (it only honors `cols` for tables),
                            and the doc ScrollBox doesn't clip horizontally — so
                            without a hard width the body bled into the Comments
                            column. */}
                        <Box flexShrink={0} overflow="hidden" width={Math.max(10, docWidth - 2)}>
                          <Md
                            activeWikiLink={
                              focusedLink >= 0 && docLinks[focusedLink]?.block === i
                                ? focusedLink - blockLinkBase[i]!
                                : undefined
                            }
                            cols={Math.max(10, docWidth - 2)}
                            onWikiLink={(target: string) => jumpTo(resolveTarget(target))}
                            t={t}
                            text={b.text}
                          />
                        </Box>
                      </Box>
                    )
                  })
                ) : (
                  <Text color={t.color.muted}>Select a note to read it.</Text>
                )}
                {doc?.truncated ? (
                  <Text color={t.color.muted}>{'\n… (truncated — open in Obsidian for the rest)'}</Text>
                ) : null}

                {/* Outgoing links live inline now (click / Tab) — no separate
                    index needed. Backlinks stay: they aren't shown inline. */}
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

        {/* Far right: comments rail (margin notes anchored to sections) */}
        {showComments ? (
          <Box flexDirection="column" flexShrink={0} marginLeft={2} noSelect width={commentsW}>
            <Text bold color={t.color.label} wrap="truncate-end">
              {`Comments${docComments.length ? ` (${docComments.length})` : ''}`}
            </Text>
            <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1}>
              {docComments.length > 0 ? (
                docComments.map((c, i) => {
                  // anchor = "L12-14 ¦ snippet" — split the line-ref from the snippet.
                  const [ref, ...rest] = c.anchor.split(' ¦ ')
                  const snippet = rest.join(' ¦ ')
                  const lineM = /^L(\d+)(?:-(\d+))?/.exec(ref ?? '')
                  const lo = lineM ? Number(lineM[1]) : -1
                  const hi = lineM ? Number(lineM[2] ?? lineM[1]) : -1
                  const on = lo >= 0 && selStartLine <= hi && selEndLine >= lo

                  return (
                    <Box
                      flexDirection="column"
                      key={i}
                      marginBottom={1}
                      onClick={(event: { cellIsBlank?: boolean; stopPropagation?: () => void }) => {
                        if (event.cellIsBlank) {
                          return
                        }

                        event.stopPropagation?.()
                        const bi = blocks.findIndex(b => b.kind !== 'blank' && b.start <= lo && b.end >= lo)

                        if (bi >= 0) {
                          jumpCursor(bi)
                        }
                      }}
                    >
                      <Text color={on ? t.color.primary : t.color.accent} wrap="truncate-end">
                        {`▌ ${ref}`}
                      </Text>
                      {snippet ? (
                        <Text color={t.color.muted} wrap="truncate-end">
                          {snippet}
                        </Text>
                      ) : null}
                      <Text color={t.color.text} wrap="wrap">
                        {c.text}
                      </Text>
                    </Box>
                  )
                })
              ) : (
                <Text color={t.color.muted} wrap="wrap">
                  No comments yet. Put the cursor on a line (↑↓, Shift to select more) and press c.
                </Text>
              )}
            </ScrollBox>
          </Box>
        ) : null}
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
          { k: 's', label: 'Search', run: () => setSearch({ loading: false, query: '', results: [], sel: 0 }) },
          { k: 'v', label: selAnchor >= 0 ? 'End select' : 'Select', run: toggleSelect },
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
      {onSelectKind ? (
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
      ) : null}
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
              : `comment on ${lineRef}${selSnippet ? ` (${selSnippet})` : ''}: `}
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
              {selAnchor >= 0
                ? `SELECTING ${lineRef} · ↑↓ extend · c comment · Esc cancel`
                : `←/→ ${focus === 'list' ? 'notes' : focus === 'outline' ? 'outline' : 'doc'} · ↑↓ navigate · v select · ⏎ open link · c comment`}
            </Text>
          ) : null}
        </>
      )}
    </Box>
  )

  // Chat modal — a focused chat window that replaces the content region while
  // open (so nothing renders behind it: opaque, theme-matched, no bleed). The
  // OBSIDIAN header + footer stay, so it's clearly still inside the vault.
  let chatOverlay = null

  if (chat) {
    const modalW = Math.max(40, Math.min(cols - 6, 96))
    // Fixed height so a long reply scrolls inside the card instead of growing
    // the box unbounded.
    const modalH = Math.max(8, Math.min(termRows - 6, 32))
    const spinner = SPINNER[spin % SPINNER.length]
    const word = THINKING_WORDS[Math.floor(spin / 8) % THINKING_WORDS.length]

    const liveLabel = chat.status && !['reasoning', 'sending', 'thinking', 'writing'].includes(chat.status)
      ? chat.status
      : chat.status === 'writing'
        ? 'writing'
        : chat.status === 'reasoning'
          ? 'reasoning'
          : word

    chatOverlay = (
      <Box alignItems="center" flexGrow={1} justifyContent="center" minHeight={0}>
        <Box
          borderColor={t.color.accent}
          borderStyle="round"
          flexDirection="column"
          height={modalH}
          minHeight={0}
          paddingX={2}
          paddingY={1}
          width={modalW}
        >
          <Text wrap="truncate-end">
            <Text bold color={t.color.primary}>
              Ask the desk
            </Text>
            <Text color={t.color.muted}>{currentRel ? `  ·  ${docTitle}` : ''}</Text>
          </Text>

          <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
            {chat.turns.length === 0 && !chat.busy ? (
              <Text color={t.color.muted} wrap="wrap">
                Chat with the desk about this note without leaving Obsidian. It shares your main
                session, so the exchange is also in the chat when you go back.
              </Text>
            ) : (
              chat.turns.map((turn, i) => (
                <Box flexDirection="column" key={i} marginTop={i ? 1 : 0}>
                  <Text bold color={turn.role === 'user' ? t.color.primary : turn.role === 'system' ? t.color.error : t.color.accent}>
                    {turn.role === 'user' ? 'you' : turn.role === 'system' ? 'system' : 'desk'}
                  </Text>
                  {turn.role === 'assistant' ? (
                    <Md cols={modalW - 4} t={t} text={turn.text} />
                  ) : (
                    <Text color={turn.role === 'system' ? t.color.error : t.color.text} wrap="wrap">
                      {turn.text}
                    </Text>
                  )}
                </Box>
              ))
            )}

            {chat.busy ? (
              <Box flexDirection="column" marginTop={chat.turns.length ? 1 : 0}>
                <Text color={t.color.accent} wrap="truncate-end">
                  {`${spinner} ${liveLabel}…`}
                </Text>
                {chat.todos.length > 0 ? (
                  <Box flexDirection="column">
                    {chat.todos.map((td, i) => (
                      <Text color={td.done ? t.color.ok : t.color.muted} key={i} wrap="truncate-end">
                        {`${td.done ? '☑' : '☐'} ${td.text}`}
                      </Text>
                    ))}
                  </Box>
                ) : null}
                {chat.stream ? (
                  <Text color={t.color.text} wrap="wrap">
                    {chat.stream}
                  </Text>
                ) : null}
              </Box>
            ) : null}
          </ScrollBox>

          {chat.confirmSave ? (
            <Box marginTop={1}>
              <Text color={t.color.warn} wrap="truncate-end">
                Unsaved edits — save before leaving? y save · n discard · Esc keep chatting
              </Text>
            </Box>
          ) : (
            <>
              <Box marginTop={1}>
                <Text color={t.color.muted}>{'› '}</Text>
                <Text color={t.color.text}>{chat.input}</Text>
                <Text color={t.color.text} inverse>
                  {' '}
                </Text>
              </Box>
              <Text color={t.color.muted} wrap="truncate-end">
                {chat.busy ? `${spinner} the desk is on it — type to queue · Esc close` : '⏎ send · Esc close'}
              </Text>
            </>
          )}
        </Box>
      </Box>
    )
  }

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      {chat ? chatOverlay : body}
      {footer}
    </Box>
  )
}
