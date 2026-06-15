import { Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text, useInput, useStdout } from '@hermes/ink'
import { useEffect, useRef, useState } from 'react'

import { patchOverlayState } from '../app/overlayStore.js'
import type { GatewayClient } from '../gatewayClient.js'
import type { ObsidianNote, ObsidianNoteResponse, ObsidianStatusResponse } from '../gatewayTypes.js'
import { asRpcResult } from '../lib/rpc.js'
import type { Theme } from '../theme.js'

import { OverlayScrollbar } from './agentsOverlay.js'
import { Md } from './markdown.js'

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
  const listScrollRef = useRef<null | ScrollBoxHandle>(null)
  const docScrollRef = useRef<null | ScrollBoxHandle>(null)

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

    // comment → append to the open note
    if (!currentRel) {
      return
    }

    gw.request<unknown>('obsidian.append', { rel_path: currentRel, text: value })
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
  }, [doc])

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

    if (ch === 'a') {
      return askAgent()
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

  const listW = Math.max(22, Math.min(40, Math.floor(cols * 0.32)))
  const docWidth = Math.max(30, cols - listW - 6)
  const { body: docBody, tags: docTags } = doc?.content ? splitFrontmatter(doc.content) : { body: '', tags: '' }

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
                    if (event.cellIsBlank) {
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
                {docLoading ? (
                  <Text color={t.color.muted}>Loading…</Text>
                ) : docError ? (
                  <Text color={t.color.error} wrap="wrap">
                    {docError}
                  </Text>
                ) : docBody ? (
                  <Md cols={docWidth} t={t} text={docBody} />
                ) : (
                  <Text color={t.color.muted}>Select a note to read it.</Text>
                )}
                {doc?.truncated ? (
                  <Text color={t.color.muted}>{'\n… (truncated — open in Obsidian for the rest)'}</Text>
                ) : null}

                {outgoing.length > 0 ? (
                  <Box flexDirection="column" marginTop={1}>
                    <Text bold color={t.color.accent}>
                      Links
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
                        <Text color={link.rel ? t.color.primary : t.color.muted}>{link.rel ? '→ ' : '× '}</Text>
                        <Text color={link.rel ? t.color.text : t.color.muted} wrap="truncate-end">
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
                        <Text color={t.color.primary}>← </Text>
                        <Text color={t.color.text} wrap="truncate-end">
                          {truncate(note.title || note.rel_path || '—', docWidth - 6)}
                        </Text>
                      </Box>
                    ))}
                  </Box>
                ) : null}
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

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      {prompt ? (
        <Text wrap="truncate-end">
          <Text color={t.color.primary}>{prompt.mode === 'create' ? 'new note path: ' : 'comment: '}</Text>
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
              ↑↓ select · Space/PgDn scroll · g/G top/bottom · click a note to open
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
