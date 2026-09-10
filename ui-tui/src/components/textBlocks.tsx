import { Box, Text } from '@superforecasting/ink'

import type { Theme } from '../theme.js'

// Small shared text primitives for read-mostly panes (presentation renderer,
// and reusable by the Desk). WrapText uses a width-bounded Box + wrap="wrap"
// rather than flexGrow so long paragraphs don't reflow/jitter inside a bounded
// ScrollBox (the load-bearing lesson from forecastsWorkspace).

export function SectionTitle({ children, t }: { children: string; t: Theme }) {
  return (
    <Box flexShrink={0} marginTop={1}>
      <Text bold color={t.color.accent}>
        {children}
      </Text>
    </Box>
  )
}

export function Rule({ t, width }: { t: Theme; width: number }) {
  return (
    <Box flexShrink={0}>
      <Text color={t.color.border}>{'─'.repeat(Math.max(1, width))}</Text>
    </Box>
  )
}

export function WrapText({
  bold = false,
  children,
  color,
  t,
  width
}: {
  bold?: boolean
  children: string
  color?: string
  t: Theme
  width: number
}) {
  return (
    <Box flexShrink={0} width={Math.max(8, width)}>
      <Text bold={bold} color={color ?? t.color.text} wrap="wrap">
        {children}
      </Text>
    </Box>
  )
}
