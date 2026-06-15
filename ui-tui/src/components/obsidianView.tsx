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

type Focus = 'doc' | 'list'

interface ObsidianViewProps {
  gw: GatewayClient
  onClose: () => void
  t: Theme
}

export function ObsidianView({ gw, onClose, t }: ObsidianViewProps) {
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
  const [focus, setFocus] = useState<Focus>('list')
  const listScrollRef = useRef<null | ScrollBoxHandle>(null)
  const docScrollRef = useRef<null | ScrollBoxHandle>(null)

  const notes: ObsidianNote[] = data?.notes ?? []
  const hasVault = Boolean(data?.exists && data?.vault)
  const currentRel = notes[selected]?.rel_path

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
        docScrollRef.current?.scrollTo(0)
      })
      .catch((err: unknown) => {
        setDocError(err instanceof Error ? err.message : String(err))
        setDocLoading(false)
      })
  }

  // Create + seed a vault when none is connected, then reload into it.
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

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gw])

  // Keep selection in range as the note set changes.
  useEffect(() => {
    if (notes.length && selected > notes.length - 1) {
      setSelected(notes.length - 1)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  // Load the selected note whenever its identity changes (selection or refresh).
  useEffect(() => {
    if (currentRel) {
      loadNote(currentRel)
    } else {
      setDoc(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentRel])

  // Keep the selected row visible in the (1-line-per-note) list.
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
    if (ch === 'q') {
      return onClose()
    }

    if (key.escape) {
      return focus === 'doc' ? setFocus('list') : onClose()
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

    if (key.tab || ch === '\t') {
      return setFocus(f => (f === 'list' ? 'doc' : 'list'))
    }

    if (focus === 'list') {
      if (key.upArrow || ch === 'k' || key.wheelUp) {
        return move(-1)
      }

      if (key.downArrow || ch === 'j' || key.wheelDown) {
        return move(1)
      }

      if (key.pageUp) {
        return move(-pageSize)
      }

      if (key.pageDown) {
        return move(pageSize)
      }

      if (key.return || key.rightArrow || ch === 'l') {
        return setFocus('doc')
      }

      return
    }

    // focus === 'doc'
    if (key.leftArrow || ch === 'h') {
      return setFocus('list')
    }

    if (key.upArrow || ch === 'k' || key.wheelUp) {
      return docScrollRef.current?.scrollBy(-2)
    }

    if (key.downArrow || ch === 'j' || key.wheelDown) {
      return docScrollRef.current?.scrollBy(2)
    }

    if (key.pageUp || (key.ctrl && ch === 'u')) {
      return docScrollRef.current?.scrollBy(-pageSize)
    }

    if (key.pageDown || (key.ctrl && ch === 'd')) {
      return docScrollRef.current?.scrollBy(pageSize)
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
            knowledge base — the art of superforecasting, a getting-started guide, the core methods
            (reference classes, Bayesian updating, calibration), and a question-dossier template, all
            wikilinked into an index.
          </Text>
        </Box>
        <Box marginTop={1}>
          <Text color={t.color.muted} wrap="wrap">
            It is created at ~/Documents/Obsidian Vault by default; set OBSIDIAN_VAULT_PATH first to
            choose a different location.
          </Text>
        </Box>
      </Box>
    )
  } else if (notes.length === 0) {
    body = (
      <Text color={t.color.muted} wrap="wrap">
        Vault is connected but empty of notes yet — ask the desk to sync learnings or write a forecast
        dossier, and they will appear here.
      </Text>
    )
  } else {
    body = (
      <Box flexDirection="row" flexGrow={1} flexShrink={1} minHeight={0}>
        {/* Left: the note list */}
        <Box flexDirection="column" flexShrink={0} marginRight={2} width={listW}>
          <Text bold={focus === 'list'} color={focus === 'list' ? t.color.primary : t.color.muted} wrap="truncate-end">
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
                    setFocus('list')
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

        {/* Right: the selected note */}
        <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
          <Text bold={focus === 'doc'} color={focus === 'doc' ? t.color.primary : t.color.muted} wrap="truncate-end">
            {truncate(currentRel ?? 'no note', docWidth)}
          </Text>
          <Box flexDirection="row" flexGrow={1} flexShrink={1} minHeight={0}>
            <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1} ref={docScrollRef}>
              <Box flexDirection="column" paddingBottom={3} paddingRight={1}>
                {docLoading ? (
                  <Text color={t.color.muted}>Loading…</Text>
                ) : docError ? (
                  <Text color={t.color.error} wrap="wrap">
                    {docError}
                  </Text>
                ) : doc?.content ? (
                  <Md cols={docWidth} t={t} text={doc.content} />
                ) : (
                  <Text color={t.color.muted}>Select a note to read it.</Text>
                )}
                {doc?.truncated ? <Text color={t.color.muted}>{'\n… (truncated — open in Obsidian for the rest)'}</Text> : null}
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

  const footerKeys = !hasVault
    ? 's set up vault · r retry · Esc/q close'
    : notes.length === 0
      ? 'r refresh · Esc/q close'
      : focus === 'list'
        ? '↑↓ select · ⏎/→ read · Tab pane · r refresh · Esc/q close'
        : '↑↓/jk scroll · PgUp/PgDn page · g/G · ←/Tab list · q close'

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      {flash ? <Text color={t.color.accent}>{flash}</Text> : null}
      <Text color={t.color.muted} wrap="truncate-end">
        {footerKeys}
      </Text>
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
