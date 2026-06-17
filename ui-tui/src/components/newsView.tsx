import { Box, NoSelect, Text, useInput, useStdout } from '@hermes/ink'
import { useEffect, useState } from 'react'

import { patchOverlayState } from '../app/overlayStore.js'
import type { Theme } from '../theme.js'

import { type FooterChip, FooterChips } from './footerChips.js'

export const openNewsView = () => patchOverlayState({ news: true })
export const closeNewsView = () => patchOverlayState({ news: false })

// News — live RSS feeds with quick article reading. No feeds are wired yet;
// this renders the two-pane scaffold (sources rail + headline list + reading
// pane) so articles slot straight in once a feed is configured.

interface FeedSource {
  key: string
  label: string
}

// Placeholder source rail — the categories a reader would group feeds under.
const SOURCES: FeedSource[] = [
  { key: 'all', label: 'All feeds' },
  { key: 'markets', label: 'Markets' },
  { key: 'world', label: 'World' },
  { key: 'tech', label: 'Technology' },
  { key: 'politics', label: 'Politics' },
  { key: 'science', label: 'Science' }
]

interface NewsViewProps {
  onClose: () => void
  t: Theme
}

export function NewsView({ onClose, t }: NewsViewProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24

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

  useInput((ch, key) => {
    if (ch === 'q' || key.escape) {
      return onClose()
    }

    if (key.upArrow || ch === 'k') {
      return setSelected(i => Math.max(0, i - 1))
    }

    if (key.downArrow || ch === 'j') {
      return setSelected(i => Math.min(SOURCES.length - 1, i + 1))
    }
  })

  const width = Math.max(40, cols - 4)
  const live = tick % 2 === 0
  const railWidth = Math.min(22, Math.max(14, Math.floor(width * 0.28)))
  const listWidth = Math.max(20, width - railWidth - 2)
  const rowCount = Math.max(4, Math.min(10, termRows - 12))

  const header = (
    <Box flexShrink={0} marginBottom={1}>
      <Text wrap="truncate-end">
        <Text bold color={t.color.primary}>
          NEWS
        </Text>
        <Text color={t.color.muted}>{'   '}</Text>
        <Text color={live ? t.color.ok : t.color.muted}>●</Text>
        <Text color={t.color.muted}> idle · </Text>
        <Text color={t.color.text}>live RSS feeds</Text>
        <Text color={t.color.muted}> · quick reading</Text>
      </Text>
    </Box>
  )

  const rail = (
    <NoSelect flexDirection="column" flexShrink={0} marginRight={1} width={railWidth}>
      <Text bold color={t.color.label}>
        SOURCES
      </Text>
      {SOURCES.map((source, i) => {
        const isActive = i === selected

        return (
          <Box key={source.key} onClick={() => setSelected(i)}>
            <Text color={isActive ? t.color.accent : t.color.muted} wrap="truncate-end">
              {isActive ? '▸ ' : '  '}
              {source.label}
            </Text>
            <Text color={t.color.border}> · —</Text>
          </Box>
        )
      })}
    </NoSelect>
  )

  // Skeleton headline rows: a title bar, then a muted "source · time" line.
  const headlines = (
    <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0} width={listWidth}>
      <Text bold color={t.color.label} wrap="truncate-end">
        {SOURCES[selected].label.toUpperCase()}
      </Text>
      <Box flexDirection="column" marginTop={1}>
        {Array.from({ length: rowCount }, (_, r) => (
          <Box flexDirection="column" key={r} marginBottom={1}>
            <Text color={t.color.border} wrap="truncate-end">
              {'─'.repeat(Math.max(8, Math.floor(listWidth * (r % 3 === 0 ? 0.8 : 0.6))))}
            </Text>
            <Text color={t.color.muted} wrap="truncate-end">
              {'— — —'} · —
            </Text>
          </Box>
        ))}
      </Box>
      <Box marginTop={1}>
        <Text color={t.color.muted} wrap="wrap">
          No feeds configured yet — add an RSS source and headlines will populate this list, newest first.
        </Text>
      </Box>
    </Box>
  )

  const chips: FooterChip[] = [
    { k: '↑↓', label: 'Source' },
    { k: '⏎', label: 'Open' },
    { k: 'a', label: 'Add feed' },
    { k: 'r', label: 'Refresh' },
    { k: 'q', label: 'Close', run: onClose }
  ]

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      <FooterChips chips={chips} t={t} />
      <Text color={t.color.muted} wrap="truncate-end">
        ↑↓/jk source · Enter open · a add feed · r refresh · Esc/q close
      </Text>
    </Box>
  )

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      <Box flexDirection="row" flexGrow={1} flexShrink={1} minHeight={0}>
        {rail}
        {headlines}
      </Box>
      {footer}
    </Box>
  )
}
