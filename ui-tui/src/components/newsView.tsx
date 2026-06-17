import { Box, Text, useInput, useStdout } from '@hermes/ink'
import { useEffect, useState } from 'react'

import { patchOverlayState } from '../app/overlayStore.js'
import type { Theme } from '../theme.js'

import { type FooterChip, FooterChips } from './footerChips.js'

export const openNewsView = () => patchOverlayState({ news: true })
export const closeNewsView = () => patchOverlayState({ news: false })

// News — live RSS feeds with quick reading. No feeds are wired yet; this
// renders the three-pane scaffold the reader will use: a SOURCES rail to
// filter, an ARTICLES list to browse, and a READER pane to consume the
// selected item. Panes are separated by thin vertical rules (not full boxes)
// and given an explicit height so the layout never reflows on keystroke.

interface FeedSource {
  key: string
  label: string
}

const SOURCES: FeedSource[] = [
  { key: 'all', label: 'All feeds' },
  { key: 'markets', label: 'Markets' },
  { key: 'world', label: 'World' },
  { key: 'tech', label: 'Technology' },
  { key: 'politics', label: 'Politics' },
  { key: 'science', label: 'Science' }
]

// A skeleton text bar — light-shade blocks read as "content pending" rather
// than the rule-lines a row of dashes implied.
const bar = (n: number): string => '░'.repeat(Math.max(3, n))

// Organic-looking placeholder widths so the list/reader don't look like a
// perfectly uniform grid.
const TITLE_WIDTHS = [30, 22, 34, 18, 28, 24, 32, 20, 26, 23]
const PARA_WIDTHS = [40, 44, 38, 42, 30, 44, 36]

// Props for a pane's right-edge vertical separator. Edges show unless set to
// false, so this leaves a single vertical line on the right.
const RIGHT_RULE = {
  borderBottom: false,
  borderLeft: false,
  borderStyle: 'single',
  borderTop: false
} as const

interface NewsViewProps {
  onClose: () => void
  t: Theme
}

export function NewsView({ onClose, t }: NewsViewProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24

  const [source, setSource] = useState(0)
  const [article, setArticle] = useState(0)
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

  const width = Math.max(48, cols - 4)
  // Explicit content height = screen minus chrome (padding 2 + header 2 +
  // footer 3). Fixing it stops the panes from reflowing as state changes.
  const contentHeight = Math.max(8, termRows - 7)
  // Each article occupies 3 rows (title + meta + gap); size the list to fit.
  const rowCount = Math.max(3, Math.min(10, Math.floor((contentHeight - 2) / 3)))

  useInput((ch, key) => {
    if (ch === 'q' || key.escape) {
      return onClose()
    }

    // Tab / ←→ filters by source; ↑↓ browses the article list.
    if (key.tab || key.rightArrow) {
      return setSource(i => (i + 1) % SOURCES.length)
    }

    if (key.leftArrow) {
      return setSource(i => (i - 1 + SOURCES.length) % SOURCES.length)
    }

    if (key.upArrow || ch === 'k') {
      return setArticle(i => Math.max(0, i - 1))
    }

    if (key.downArrow || ch === 'j') {
      return setArticle(i => Math.min(rowCount - 1, i + 1))
    }
  })

  const live = tick % 2 === 0
  const railWidth = Math.min(26, Math.max(20, Math.floor(width * 0.2)))
  const readerWidth = Math.min(52, Math.max(28, Math.floor(width * 0.36)))

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

  // 1. SOURCES rail — filter. Counts right-aligned for a tidy column.
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
        SOURCES
      </Text>
      <Box flexDirection="column" marginTop={1}>
        {SOURCES.map((src, i) => {
          const isActive = i === source

          return (
            <Box justifyContent="space-between" key={src.key} onClick={() => setSource(i)} width="100%">
              <Text color={isActive ? t.color.accent : t.color.muted} wrap="truncate-end">
                {isActive ? '▸ ' : '  '}
                {src.label}
              </Text>
              <Text color={t.color.border}>—</Text>
            </Box>
          )
        })}
      </Box>
    </Box>
  )

  // 2. ARTICLES list — browse. Each row: marker + headline bar, meta beneath.
  const list = (
    <Box
      {...RIGHT_RULE}
      borderColor={t.color.border}
      flexDirection="column"
      flexGrow={1}
      flexShrink={1}
      height={contentHeight}
      marginLeft={1}
      minWidth={0}
      overflow="hidden"
      paddingRight={1}
    >
      <Text bold color={t.color.label} wrap="truncate-end">
        {SOURCES[source].label.toUpperCase()}
      </Text>
      <Box flexDirection="column" marginTop={1}>
        {Array.from({ length: rowCount }, (_, r) => {
          const isActive = r === article

          return (
            <Box flexDirection="column" key={r} marginBottom={1} onClick={() => setArticle(r)}>
              <Box width="100%">
                <Text color={isActive ? t.color.accent : t.color.border}>{isActive ? '▸ ' : '  '}</Text>
                <Text color={isActive ? t.color.text : t.color.border} wrap="truncate-end">
                  {bar(TITLE_WIDTHS[r % TITLE_WIDTHS.length])}
                </Text>
              </Box>
              <Text color={t.color.muted} wrap="truncate-end">
                {'   '}
                {bar(8)} · {bar(3)}
              </Text>
            </Box>
          )
        })}
      </Box>
    </Box>
  )

  // 3. READER pane — consume. Headline + byline + paragraph skeleton.
  const reader = (
    <Box
      flexDirection="column"
      flexShrink={0}
      height={contentHeight}
      marginLeft={1}
      overflow="hidden"
      width={readerWidth}
    >
      <Text bold color={t.color.label} wrap="truncate-end">
        READER
      </Text>
      <Box flexDirection="column" marginTop={1}>
        <Text color={t.color.text} wrap="truncate-end">
          {bar(TITLE_WIDTHS[article % TITLE_WIDTHS.length])}
        </Text>
        <Text color={t.color.muted} wrap="truncate-end">
          {bar(10)} · {bar(6)}
        </Text>
        <Box flexDirection="column" marginTop={1}>
          {PARA_WIDTHS.map((w, i) => (
            <Text color={t.color.border} key={i} wrap="truncate-end">
              {bar(Math.min(w, readerWidth - 2))}
            </Text>
          ))}
        </Box>
      </Box>
      <Box marginTop={1}>
        <Text color={t.color.muted} wrap="wrap">
          Select an article to read its full text here. No feeds configured yet — add an RSS source to populate.
        </Text>
      </Box>
    </Box>
  )

  const chips: FooterChip[] = [
    { k: '↑↓', label: 'Browse' },
    { k: '⇥', label: 'Source', run: () => setSource(i => (i + 1) % SOURCES.length) },
    { k: '⏎', label: 'Open' },
    { k: 'a', label: 'Add feed' },
    { k: 'r', label: 'Refresh' },
    { k: 'q', label: 'Close', run: onClose }
  ]

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      <FooterChips chips={chips} t={t} />
      <Text color={t.color.muted} wrap="truncate-end">
        ↑↓/jk browse · Tab/←→ source · Enter open · a add feed · r refresh · Esc/q close
      </Text>
    </Box>
  )

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      <Box flexDirection="row" flexShrink={0} height={contentHeight}>
        {rail}
        {list}
        {reader}
      </Box>
      {footer}
    </Box>
  )
}
