import { Box, NoSelect, Text, useInput, useStdout } from '@hermes/ink'
import { useEffect, useState } from 'react'

import { patchOverlayState } from '../app/overlayStore.js'
import type { Theme } from '../theme.js'

import { type FooterChip, FooterChips } from './footerChips.js'

export const openMarketsView = () => patchOverlayState({ markets: true })
export const closeMarketsView = () => patchOverlayState({ markets: false })

// Markets — a live financial tape. No feed is wired yet; this renders the
// scaffold (category tabs + a quote table with column headers and skeleton
// rows) so the shape is obvious the moment quotes start streaming in.

interface MarketCategory {
  key: string
  label: string
}

const CATEGORIES: MarketCategory[] = [
  { key: 'watchlist', label: 'Watchlist' },
  { key: 'indices', label: 'Indices' },
  { key: 'fx', label: 'FX' },
  { key: 'crypto', label: 'Crypto' },
  { key: 'commodities', label: 'Commodities' }
]

// Column geometry for the quote table — widened/narrowed to fit the terminal.
interface Column {
  align: 'left' | 'right'
  key: string
  label: string
  width: number
}

const COLUMNS: Column[] = [
  { align: 'left', key: 'symbol', label: 'SYMBOL', width: 10 },
  { align: 'left', key: 'name', label: 'NAME', width: 22 },
  { align: 'right', key: 'last', label: 'LAST', width: 12 },
  { align: 'right', key: 'chg', label: 'CHG', width: 10 },
  { align: 'right', key: 'pct', label: 'CHG%', width: 9 },
  { align: 'right', key: 'vol', label: 'VOL', width: 10 },
  { align: 'right', key: 'updated', label: 'UPDATED', width: 9 }
]

const pad = (value: string, width: number, align: 'left' | 'right'): string => {
  const v = value.length > width ? `${value.slice(0, Math.max(0, width - 1))}…` : value

  return align === 'right' ? v.padStart(width) : v.padEnd(width)
}

interface MarketsViewProps {
  onClose: () => void
  t: Theme
}

export function MarketsView({ onClose, t }: MarketsViewProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24

  const [active, setActive] = useState(0)
  const [tick, setTick] = useState(0)

  // A slow pulse on the "live" dot so the header reads as a feed that is
  // waiting on data rather than a frozen screen.
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

    if (key.tab || key.rightArrow || ch === 'l') {
      return setActive(i => (i + 1) % CATEGORIES.length)
    }

    if (key.leftArrow || ch === 'h') {
      return setActive(i => (i - 1 + CATEGORIES.length) % CATEGORIES.length)
    }
  })

  const width = Math.max(40, cols - 4)
  const live = tick % 2 === 0
  const rowCount = Math.max(4, Math.min(12, termRows - 12))

  // Visible columns: drop the lowest-priority ones first when the terminal is
  // too narrow, so the table never wraps.
  const visibleColumns: Column[] = []
  let used = 0

  for (const col of COLUMNS) {
    if (used + col.width + 1 > width) {
      break
    }

    visibleColumns.push(col)
    used += col.width + 1
  }

  const header = (
    <Box flexDirection="column" flexShrink={0} marginBottom={1}>
      <Text wrap="truncate-end">
        <Text bold color={t.color.primary}>
          MARKETS
        </Text>
        <Text color={t.color.muted}>{'   '}</Text>
        <Text color={live ? t.color.ok : t.color.muted}>●</Text>
        <Text color={t.color.muted}> connecting · </Text>
        <Text color={t.color.text}>live quotes</Text>
        <Text color={t.color.muted}> · streaming tape</Text>
      </Text>
    </Box>
  )

  const tabs = (
    <NoSelect flexShrink={0} marginBottom={1}>
      <Box>
        {CATEGORIES.map((cat, i) => (
          <Box
            key={cat.key}
            onClick={() => setActive(i)}
          >
            {i > 0 ? <Text color={t.color.border}>{'  ·  '}</Text> : null}
            <Text bold={i === active} color={i === active ? t.color.accent : t.color.muted}>
              {cat.label}
            </Text>
          </Box>
        ))}
      </Box>
    </NoSelect>
  )

  const columnHeader = (
    <Text bold color={t.color.label} wrap="truncate-end">
      {visibleColumns.map(col => `${pad(col.label, col.width, col.align)} `).join('')}
    </Text>
  )

  const rule = <Text color={t.color.border}>{'─'.repeat(Math.min(width, used))}</Text>

  // Skeleton rows: dashes where a quote would land. A subtly different dim on
  // alternating rows keeps the table legible while empty.
  const skeleton = (
    <Box flexDirection="column">
      {Array.from({ length: rowCount }, (_, r) => (
        <Text color={t.color.border} key={r} wrap="truncate-end">
          {visibleColumns
            .map(col => `${pad(col.key === 'symbol' ? '—' : col.key === 'name' ? '— — —' : '—', col.width, col.align)} `)
            .join('')}
        </Text>
      ))}
    </Box>
  )

  const body = (
    <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
      {columnHeader}
      {rule}
      {skeleton}
      <Box marginTop={1}>
        <Text color={t.color.muted} wrap="wrap">
          Awaiting market feed — quotes for {CATEGORIES[active].label.toLowerCase()} will stream in here once a data
          source is connected.
        </Text>
      </Box>
    </Box>
  )

  const chips: FooterChip[] = [
    { k: '⇥', label: 'Category', run: () => setActive(i => (i + 1) % CATEGORIES.length) },
    { k: 'r', label: 'Refresh' },
    { k: 'q', label: 'Close', run: onClose }
  ]

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      <FooterChips chips={chips} t={t} />
      <Text color={t.color.muted} wrap="truncate-end">
        Tab/←→ category · r refresh · Esc/q close
      </Text>
    </Box>
  )

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      {tabs}
      {body}
      {footer}
    </Box>
  )
}
