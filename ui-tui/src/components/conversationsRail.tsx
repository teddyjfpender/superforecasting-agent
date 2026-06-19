import { Box, Text, useStdout } from '@hermes/ink'
import { useEffect, useState } from 'react'

import type { GatewayClient } from '../gatewayClient.js'
import type { SessionListItem, SessionListResponse } from '../gatewayTypes.js'
import { asRpcResult } from '../lib/rpc.js'
import type { Theme } from '../theme.js'

// A ChatGPT-style left rail of recent conversations, shown on the Home/landing
// screen alongside the Outrider hero. Click "New chat" to start fresh (the hero
// stays); click a past conversation to re-enter it. Click-only by design — the
// composer keeps keyboard focus on the landing screen, and the full keyboard
// session browser stays available via /sessions.

const age = (ts: number): string => {
  const d = (Date.now() / 1000 - ts) / 86_400

  if (d < 1) {
    return 'today'
  }

  if (d < 2) {
    return 'yesterday'
  }

  return `${Math.floor(d)}d`
}

interface ConversationsRailProps {
  currentSid: null | string
  gw: GatewayClient
  onNewChat: () => void
  onSelect: (id: string) => void
  // Bump to force a re-fetch (e.g. the active session changed).
  refreshKey?: string
  t: Theme
  width?: number
}

export function ConversationsRail({ currentSid, gw, onNewChat, onSelect, refreshKey, t, width = 30 }: ConversationsRailProps) {
  const { stdout } = useStdout()
  const rows = stdout?.rows ?? 24
  const [items, setItems] = useState<SessionListItem[]>([])

  useEffect(() => {
    let alive = true
    gw.request<SessionListResponse>('session.list', { limit: 50 })
      .then(raw => {
        const r = asRpcResult<SessionListResponse>(raw)

        if (alive && r) {
          setItems(r.sessions ?? [])
        }
      })
      .catch(() => {
        /* a missing list just shows the empty state */
      })

    return () => {
      alive = false
    }
  }, [gw, refreshKey])

  // Leave room for the nav, header, "New chat", and the prompt bar.
  const maxRows = Math.max(3, rows - 12)
  const shown = items.slice(0, maxRows)

  return (
    <Box
      borderBottom={false}
      borderColor={t.color.border}
      borderLeft={false}
      borderRight
      borderStyle="single"
      borderTop={false}
      flexDirection="column"
      flexShrink={0}
      paddingRight={1}
      width={width}
    >
      <Box flexShrink={0} marginBottom={1}>
        <Text bold color={t.color.primary}>
          {t.brand.icon} {t.brand.name}
        </Text>
      </Box>

      <Box flexShrink={0} onClick={onNewChat}>
        <Text bold color={t.color.accent}>
          {'✎ New chat'}
        </Text>
      </Box>

      <Box flexShrink={0} marginTop={1}>
        <Text color={t.color.muted}>Recent</Text>
      </Box>

      <Box flexDirection="column" marginTop={0} minHeight={0} overflow="hidden">
        {shown.length === 0 ? (
          <Text color={t.color.muted} wrap="wrap">
            No conversations yet.
          </Text>
        ) : (
          shown.map(s => {
            const on = currentSid !== null && s.id === currentSid
            const label = s.title?.trim() || s.preview?.trim() || '(untitled)'

            return (
              <Box flexShrink={0} key={s.id} onClick={() => onSelect(s.id)} width="100%">
                <Text color={on ? t.color.accent : t.color.text} wrap="truncate-end">
                  {on ? '▸ ' : '  '}
                  {label}
                </Text>
                <Text color={t.color.muted}>{` ${age(s.started_at)}`}</Text>
              </Box>
            )
          })
        )}
      </Box>
    </Box>
  )
}
