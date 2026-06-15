import { Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text, useInput, useStdout } from '@hermes/ink'
import { useEffect, useRef, useState } from 'react'

import { patchOverlayState } from '../app/overlayStore.js'
import type { GatewayClient } from '../gatewayClient.js'
import type { ObsidianNote, ObsidianStatusResponse } from '../gatewayTypes.js'
import { asRpcResult } from '../lib/rpc.js'
import type { Theme } from '../theme.js'

import { OverlayScrollbar } from './agentsOverlay.js'

export const openObsidianView = () => patchOverlayState({ obsidian: true })
export const closeObsidianView = () => patchOverlayState({ obsidian: false })

const truncate = (value: string, max: number): string =>
  value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value

const shortDate = (iso: string | undefined): string => {
  if (!iso) {
    return ''
  }

  const stamp = Date.parse(iso)

  if (!Number.isFinite(stamp)) {
    return ''
  }

  return new Date(stamp).toLocaleDateString('en-US', { day: 'numeric', month: 'short' })
}

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
  const scrollRef = useRef<null | ScrollBoxHandle>(null)

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

  // Create the vault (default or OBSIDIAN_VAULT_PATH) and seed the starter
  // knowledge base, then reload to show it.
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

  useEffect(() => {
    scrollRef.current?.scrollTo(0)
  }, [data])

  useEffect(() => {
    const id = setInterval(() => setNow(value => value + 1), 500)

    return () => clearInterval(id)
  }, [])

  const pageSize = Math.max(4, termRows - 10)

  useInput((ch, key) => {
    if (ch === 'q' || key.escape) {
      return onClose()
    }

    // `s` sets up + seeds a vault when none is connected yet.
    if (ch === 's' && !(data?.exists && data?.vault)) {
      return runSetup()
    }

    if (ch === 'r') {
      return load(true)
    }

    if (key.upArrow || ch === 'k' || key.wheelUp) {
      return scrollRef.current?.scrollBy(-2)
    }

    if (key.downArrow || ch === 'j' || key.wheelDown) {
      return scrollRef.current?.scrollBy(2)
    }

    if (key.pageUp || (key.ctrl && ch === 'u')) {
      return scrollRef.current?.scrollBy(-pageSize)
    }

    if (key.pageDown || (key.ctrl && ch === 'd')) {
      return scrollRef.current?.scrollBy(pageSize)
    }

    if (ch === 'g') {
      return scrollRef.current?.scrollTo(0)
    }

    if (ch === 'G') {
      return scrollRef.current?.scrollToBottom?.()
    }
  })

  const width = Math.max(40, cols - 4)
  const notes: ObsidianNote[] = data?.notes ?? []
  const hasVault = Boolean(data?.exists && data?.vault)

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
            choose a different location. From there the desk reads, writes and links notes — your
            knowledge base grows as you forecast.
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
        <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1} ref={scrollRef}>
          <Box flexDirection="column" paddingBottom={3} paddingRight={1}>
            {notes.map((note, i) => (
              <Box flexDirection="column" key={note.rel_path ?? i} marginBottom={1}>
                <Text wrap="truncate-end">
                  <Text bold color={t.color.text}>
                    {truncate(note.title || note.rel_path || '—', width - 24)}
                  </Text>
                  <Text color={t.color.muted}>{note.modified ? `  ${shortDate(note.modified)}` : ''}</Text>
                </Text>
                <Text color={t.color.label} wrap="truncate-end">
                  {`  ${note.folder ? `${truncate(note.folder, 32)}/` : ''}`}
                </Text>
                {note.excerpt ? (
                  <Text color={t.color.muted} wrap="truncate-end">{`  ${truncate(note.excerpt, width - 6)}`}</Text>
                ) : null}
              </Box>
            ))}
          </Box>
        </ScrollBox>
        <NoSelect flexShrink={0} marginLeft={1}>
          <OverlayScrollbar scrollRef={scrollRef} t={t} tick={now} />
        </NoSelect>
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
          {truncate(data.vault, width)}
        </Text>
      ) : null}
    </Box>
  )

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      {flash ? <Text color={t.color.accent}>{flash}</Text> : null}
      <Text color={t.color.muted} wrap="truncate-end">
        {hasVault
          ? '↑↓/jk scroll · PgUp/PgDn page · g/G top/bottom · r refresh · Esc/q close'
          : 's set up vault · r retry · Esc/q close'}
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
