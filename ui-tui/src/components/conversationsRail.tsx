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

// A one-line conversation label: prefer the title, else the first-message
// preview; collapse whitespace and strip a leading injected system-reminder
// block (e.g. "[IMPORTANT: ...]", often unclosed in a truncated preview) so the
// rail shows the real conversation, not prompt scaffolding.
const cleanLabel = (title?: string, preview?: string): string => {
  const s = (title?.trim() || preview?.trim() || '')
    .replace(/\s+/g, ' ')
    .replace(/^\[[^\]]*\]?\s*/, '')
    .trim()

  return s || '(untitled)'
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
  // Track the row the user clicked: resuming a session mints a NEW sid that
  // won't match the list id, so the parent's currentSid can't mark the active
  // chat — this can. Cleared on "New chat".
  const [clickedId, setClickedId] = useState<null | string>(null)

  const openChat = (id: string) => {
    setClickedId(id)
    onSelect(id)
  }

  const startNewChat = () => {
    setClickedId(null)
    onNewChat()
  }

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

      <Box flexShrink={0} onClick={startNewChat}>
        <Text bold color={clickedId === null ? t.color.accent : t.color.muted}>
          {clickedId === null ? '▸ ✎ New chat' : '  ✎ New chat'}
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
            const on = clickedId !== null ? s.id === clickedId : currentSid !== null && s.id === currentSid

            return (
              <Box flexShrink={0} key={s.id} onClick={() => openChat(s.id)} width="100%">
                <Text bold={on} color={on ? t.color.accent : t.color.text} wrap="truncate-end">
                  {on ? '▸ ' : '  '}
                  {cleanLabel(s.title, s.preview)}
                </Text>
              </Box>
            )
          })
        )}
      </Box>
    </Box>
  )
}
