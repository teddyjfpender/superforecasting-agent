import { Box, Text, useInput, useStdout } from '@hermes/ink'
import { useEffect, useState } from 'react'

import { patchOverlayState } from '../app/overlayStore.js'
import type { Theme } from '../theme.js'

import { type FooterChip, FooterChips } from './footerChips.js'

export const openMessagingView = () => patchOverlayState({ messaging: true })
export const closeMessagingView = () => patchOverlayState({ messaging: false })

// Messaging — the Telegram / Signal surface. No account is linked yet; this
// renders an aligned chat scaffold: a CHATS rail (avatar · name · time, with a
// preview line) and a thread pane with incoming/outgoing bubbles. The rail is
// separated by a thin vertical rule (not a full box) and the layout is given an
// explicit height so it never reflows on keystroke.

interface Channel {
  key: string
  label: string
}

const CHANNELS: Channel[] = [
  { key: 'telegram', label: 'Telegram' },
  { key: 'signal', label: 'Signal' }
]

const bar = (n: number): string => '░'.repeat(Math.max(3, n))

// Placeholder bubble widths + side. Alternating sides with varied widths read
// as a real back-and-forth thread rather than a uniform ladder.
const BUBBLES: { mine: boolean; w: number }[] = [
  { mine: false, w: 26 },
  { mine: true, w: 16 },
  { mine: false, w: 32 },
  { mine: true, w: 22 },
  { mine: false, w: 18 },
  { mine: true, w: 28 }
]

const NAME_WIDTHS = [8, 6, 9, 7, 8, 6, 9, 7]
const PREVIEW_WIDTHS = [13, 10, 14, 11, 9, 12, 13, 10]

// A pane's right-edge vertical separator (all other edges off).
const RIGHT_RULE = {
  borderBottom: false,
  borderLeft: false,
  borderStyle: 'single',
  borderTop: false
} as const

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

  // No real text cursor in this view — park it so it doesn't sit in the corner.
  useEffect(() => {
    stdout?.write('\x1b[?25l')

    return () => {
      stdout?.write('\x1b[?25h')
    }
  }, [stdout])

  // Explicit content height = screen minus chrome (padding 2 + header 2 +
  // footer 3). Fixing it stops the panes reflowing as state changes.
  const contentHeight = Math.max(8, termRows - 7)
  // Each chat row is 2 lines + a gap; size the rail to fit.
  const chatCount = Math.max(4, Math.min(8, Math.floor((contentHeight - 2) / 3)))
  // Each bubble is a 3-row box + a gap; reserve the title + connect hint.
  const bubbleCount = Math.max(2, Math.min(BUBBLES.length, Math.floor((contentHeight - 4) / 4)))

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

  const width = Math.max(48, cols - 4)
  const live = tick % 2 === 0
  const railWidth = Math.min(32, Math.max(24, Math.floor(width * 0.3)))
  const bubbleMax = Math.max(12, Math.floor((width - railWidth) * 0.5))

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

  // CHATS rail — avatar · name (left) · time (right), preview beneath.
  const rail = (
    <Box
      {...RIGHT_RULE}
      borderColor={t.color.border}
      flexDirection="column"
      flexShrink={0}
      height={contentHeight}
      overflow="hidden"
      paddingRight={1}
      width={railWidth}
    >
      <Text bold color={t.color.label}>
        CHATS
      </Text>
      <Box flexDirection="column" marginTop={1}>
        {Array.from({ length: chatCount }, (_, r) => {
          const isActive = r === selected

          return (
            <Box flexDirection="column" key={r} marginBottom={1} onClick={() => setSelected(r)}>
              <Box justifyContent="space-between" width="100%">
                <Box>
                  <Text color={isActive ? t.color.accent : t.color.muted}>{isActive ? '▸ ' : '  '}</Text>
                  <Text color={isActive ? t.color.accent : t.color.muted}>● </Text>
                  <Text color={isActive ? t.color.text : t.color.border} wrap="truncate-end">
                    {bar(NAME_WIDTHS[r % NAME_WIDTHS.length])}
                  </Text>
                </Box>
                <Text color={t.color.border}>░░:░░</Text>
              </Box>
              <Text color={t.color.border} wrap="truncate-end">
                {'      '}
                {bar(PREVIEW_WIDTHS[r % PREVIEW_WIDTHS.length])}
              </Text>
            </Box>
          )
        })}
      </Box>
    </Box>
  )

  // Thread pane — incoming bubbles left, outgoing right, each a bordered chip.
  const thread = (
    <Box
      flexDirection="column"
      flexGrow={1}
      flexShrink={1}
      height={contentHeight}
      marginLeft={1}
      minWidth={0}
      overflow="hidden"
    >
      <Text bold color={t.color.label} wrap="truncate-end">
        {CHANNELS[channel].label.toUpperCase()} · {bar(6)}
      </Text>
      <Box flexDirection="column" flexGrow={1} marginTop={1}>
        {BUBBLES.slice(0, bubbleCount).map((b, i) => (
          <Box justifyContent={b.mine ? 'flex-end' : 'flex-start'} key={i} marginBottom={1}>
            <Box borderColor={t.color.border} borderStyle="round" paddingX={1}>
              <Text color={t.color.border}>{bar(Math.min(b.w, bubbleMax))}</Text>
            </Box>
          </Box>
        ))}
      </Box>
      <Box flexShrink={0} marginTop={1}>
        <Text color={t.color.muted} wrap="wrap">
          Not connected — link a Telegram or Signal account and your conversations will appear here.
        </Text>
      </Box>
    </Box>
  )

  const chips: FooterChip[] = [
    { k: '⇥', label: 'Channel', run: () => setChannel(i => (i + 1) % CHANNELS.length) },
    { k: '↑↓', label: 'Chat' },
    { k: 'c', label: 'Connect' },
    { k: 'q', label: 'Close', run: onClose }
  ]

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      <FooterChips chips={chips} t={t} />
      <Text color={t.color.muted} wrap="truncate-end">
        Tab channel · ↑↓/jk chat · c connect · Esc/q close
      </Text>
    </Box>
  )

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      <Box flexDirection="row" flexShrink={0} height={contentHeight}>
        {rail}
        {thread}
      </Box>
      {footer}
    </Box>
  )
}
