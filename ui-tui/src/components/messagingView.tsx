import { Box, NoSelect, Text, useInput, useStdout } from '@hermes/ink'
import { useEffect, useState } from 'react'

import { patchOverlayState } from '../app/overlayStore.js'
import type { Theme } from '../theme.js'

export const openMessagingView = () => patchOverlayState({ messaging: true })
export const closeMessagingView = () => patchOverlayState({ messaging: false })

// Messaging — the Telegram / Signal surface. No account is linked yet; this
// renders the chat scaffold (conversation rail + thread pane + a disabled
// composer) so threads drop straight in once an account is connected.

interface Channel {
  key: string
  label: string
}

const CHANNELS: Channel[] = [
  { key: 'telegram', label: 'Telegram' },
  { key: 'signal', label: 'Signal' }
]

interface MessagingViewProps {
  onClose: () => void
  t: Theme
}

export function MessagingView({ onClose, t }: MessagingViewProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24

  const [channel, setChannel] = useState(0)
  const [selected, setSelected] = useState(0)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    const id = setInterval(() => setTick(value => value + 1), 600)

    return () => clearInterval(id)
  }, [])

  const chatCount = Math.max(4, Math.min(8, termRows - 14))

  useInput((ch, key) => {
    if (ch === 'q' || key.escape) {
      return onClose()
    }

    if (key.tab) {
      return setChannel(i => (i + 1) % CHANNELS.length)
    }

    if (key.upArrow || ch === 'k') {
      return setSelected(i => Math.max(0, i - 1))
    }

    if (key.downArrow || ch === 'j') {
      return setSelected(i => Math.min(chatCount - 1, i + 1))
    }
  })

  const width = Math.max(40, cols - 4)
  const live = tick % 2 === 0
  const railWidth = Math.min(26, Math.max(16, Math.floor(width * 0.3)))
  const threadWidth = Math.max(20, width - railWidth - 2)

  const header = (
    <Box flexShrink={0} marginBottom={1}>
      <Text wrap="truncate-end">
        <Text bold color={t.color.primary}>
          MESSAGING
        </Text>
        <Text color={t.color.muted}>{'   '}</Text>
        <Text color={live ? t.color.warn : t.color.muted}>●</Text>
        <Text color={t.color.muted}> offline · </Text>
        {CHANNELS.map((c, i) => (
          <Text color={i === channel ? t.color.accent : t.color.muted} key={c.key}>
            {i > 0 ? ' · ' : ''}
            {c.label}
          </Text>
        ))}
      </Text>
    </Box>
  )

  // Conversation rail: a name bar + a muted last-message preview per row.
  const rail = (
    <NoSelect flexDirection="column" flexShrink={0} marginRight={1} width={railWidth}>
      <Text bold color={t.color.label}>
        CHATS
      </Text>
      {Array.from({ length: chatCount }, (_, r) => {
        const isActive = r === selected

        return (
          <Box flexDirection="column" key={r} marginTop={r === 0 ? 1 : 0} onClick={() => setSelected(r)}>
            <Text color={isActive ? t.color.accent : t.color.muted} wrap="truncate-end">
              {isActive ? '▸ ' : '  '}
              {'— — —'}
            </Text>
            <Text color={t.color.border} wrap="truncate-end">
              {'  '}
              {'─'.repeat(Math.max(6, railWidth - 6))}
            </Text>
          </Box>
        )
      })}
    </NoSelect>
  )

  // Thread pane: alternating left/right skeleton bubbles so the chat shape
  // reads at a glance, then the connect hint.
  const thread = (
    <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0} width={threadWidth}>
      <Text bold color={t.color.label} wrap="truncate-end">
        {CHANNELS[channel].label.toUpperCase()} · —
      </Text>
      <Box flexDirection="column" flexGrow={1} marginTop={1}>
        {Array.from({ length: Math.max(3, Math.min(6, termRows - 16)) }, (_, r) => {
          const mine = r % 2 === 1
          const bubble = '─'.repeat(Math.max(8, Math.floor(threadWidth * (r % 3 === 0 ? 0.55 : 0.4))))

          return (
            <Box justifyContent={mine ? 'flex-end' : 'flex-start'} key={r} marginBottom={1}>
              <Text color={t.color.border}>{bubble}</Text>
            </Box>
          )
        })}
      </Box>
      <Box marginTop={1}>
        <Text color={t.color.muted} wrap="wrap">
          Not connected — link a Telegram or Signal account and your conversations will appear here.
        </Text>
      </Box>
    </Box>
  )

  // Disabled composer — visually present so the input affordance is obvious.
  const composer = (
    <Box borderColor={t.color.border} borderStyle="round" flexShrink={0} marginTop={1} paddingX={1}>
      <Text color={t.color.muted} wrap="truncate-end">
        Connect an account to start messaging…
      </Text>
    </Box>
  )

  const footer = (
    <Box flexShrink={0} marginTop={1}>
      <Text color={t.color.muted} wrap="truncate-end">
        Tab channel · ↑↓/jk chat · c connect · Esc/q close
      </Text>
    </Box>
  )

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      <Box flexDirection="row" flexGrow={1} flexShrink={1} minHeight={0}>
        {rail}
        {thread}
      </Box>
      {composer}
      {footer}
    </Box>
  )
}
