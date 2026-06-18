import { Box, NoSelect, Text, useInput, useStdout } from '@hermes/ink'
import { useEffect, useMemo, useRef, useState } from 'react'

import { patchOverlayState } from '../app/overlayStore.js'
import { DEFAULT_SERIES, MARKET_CATEGORIES, type MarketSeries } from '../content/marketProviders.js'
import { fetchQuotes, type MarketQuote } from '../lib/marketFetch.js'
import { getProviderKey } from '../lib/marketKeys.js'
import {
  loadMarketConfig,
  loadQuoteCache,
  type MarketConfig,
  type QuoteCache,
  quoteKey,
  saveQuoteCache
} from '../lib/marketStore.js'
import type { Theme } from '../theme.js'

import { AddProviderModal } from './addProviderModal.js'
import { type FooterChip, FooterChips } from './footerChips.js'

export const openMarketsView = () => patchOverlayState({ markets: true })
export const closeMarketsView = () => patchOverlayState({ markets: false })

// Markets — a live financial tape backed by user-chosen providers (Yahoo,
// Frankfurter, CoinGecko, FRED, BLS, BEA). Press `a` to enable providers (with
// API keys where needed) and pick which categories to watch.

const STALE_MS = 60_000

interface Column {
  align: 'left' | 'right'
  key: string
  label: string
  width: number
}

const COLUMNS: Column[] = [
  { align: 'left', key: 'name', label: 'NAME', width: 22 },
  { align: 'left', key: 'symbol', label: 'SYMBOL', width: 12 },
  { align: 'right', key: 'last', label: 'LAST', width: 13 },
  { align: 'right', key: 'chg', label: 'CHG', width: 11 },
  { align: 'right', key: 'pct', label: 'CHG%', width: 9 },
  { align: 'right', key: 'vol', label: 'VOL', width: 9 },
  { align: 'right', key: 'updated', label: 'UPDATED', width: 8 }
]

const pad = (value: string, width: number, align: 'left' | 'right'): string => {
  const v = value.length > width ? `${value.slice(0, Math.max(0, width - 1))}…` : value

  return align === 'right' ? v.padStart(width) : v.padEnd(width)
}

const fmtNum = (v: null | number, unit?: string): string => {
  if (v === null) {
    return '—'
  }

  const a = Math.abs(v)

  if (unit === '%') {
    return v.toFixed(2)
  }

  if (a >= 1000) {
    return v.toLocaleString('en-US', { maximumFractionDigits: 2 })
  }

  if (a >= 1) {
    return v.toFixed(2)
  }

  return v.toFixed(4)
}

const fmtSigned = (v: null | number): string => (v === null ? '—' : `${v >= 0 ? '+' : ''}${fmtNum(v)}`)
const fmtPct = (v: null | number): string => (v === null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`)

const fmtVol = (v?: null | number): string => {
  if (v === null || v === undefined) {
    return '—'
  }

  const a = Math.abs(v)

  if (a >= 1e9) {
    return `${(v / 1e9).toFixed(1)}B`
  }

  if (a >= 1e6) {
    return `${(v / 1e6).toFixed(1)}M`
  }

  if (a >= 1e3) {
    return `${(v / 1e3).toFixed(1)}K`
  }

  return String(v)
}

const relTime = (ms: number): string => {
  if (!ms) {
    return '—'
  }

  const diff = Date.now() - ms
  const m = Math.floor(diff / 60_000)

  if (m < 1) {
    return 'now'
  }

  if (m < 60) {
    return `${m}m`
  }

  const h = Math.floor(m / 60)

  if (h < 24) {
    return `${h}h`
  }

  return new Date(ms).toLocaleDateString('en-US', { day: 'numeric', month: 'short' })
}

interface MarketsViewProps {
  onClose: () => void
  t: Theme
}

export function MarketsView({ onClose, t }: MarketsViewProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24

  const [config, setConfig] = useState<MarketConfig>(() => loadMarketConfig())
  const [active, setActive] = useState(0)
  const [tick, setTick] = useState(0)
  const [fetching, setFetching] = useState(false)
  const [setup, setSetup] = useState(false)
  const [flash, setFlash] = useState('')

  const cacheRef = useRef<QuoteCache>(loadQuoteCache())
  const [cacheVersion, setCacheVersion] = useState(0)
  const inflightRef = useRef(false)
  const aliveRef = useRef(true)

  useEffect(() => {
    aliveRef.current = true
    const id = setInterval(() => setTick(v => v + 1), 600)

    return () => {
      aliveRef.current = false
      clearInterval(id)
    }
  }, [])

  useEffect(() => {
    stdout?.write('\x1b[?25l')

    return () => {
      stdout?.write('\x1b[?25h')
    }
  }, [stdout])

  const providers = useMemo(() => new Set(config.providers), [config])

  const categories = useMemo(
    () => MARKET_CATEGORIES.filter(c => config.categories.includes(c)),
    [config]
  )

  const activeCategory = categories[Math.min(active, Math.max(0, categories.length - 1))]

  // Series to fetch: enabled providers ∩ selected categories.
  const activeSeries = useMemo(
    () => DEFAULT_SERIES.filter(s => providers.has(s.provider) && config.categories.includes(s.category)),
    [providers, config]
  )

  const refresh = async (force: boolean) => {
    if (inflightRef.current || activeSeries.length === 0) {
      return
    }

    const targets = force
      ? activeSeries
      : activeSeries.filter(s => {
          const q = cacheRef.current[quoteKey(s.provider, s.symbol)]

          return !q || Date.now() - q.asOf > STALE_MS
        })

    if (targets.length === 0) {
      return
    }

    inflightRef.current = true

    if (aliveRef.current) {
      setFetching(true)
    }

    await fetchQuotes(targets, {
      getKey: getProviderKey,
      onBatch: quotes => {
        for (const q of quotes) {
          cacheRef.current[quoteKey(q.provider, q.symbol)] = q
        }

        if (aliveRef.current) {
          setCacheVersion(v => v + 1)
        }
      }
    })
    saveQuoteCache(cacheRef.current)
    inflightRef.current = false

    if (aliveRef.current) {
      setFetching(false)
    }
  }

  useEffect(() => {
    void refresh(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config])

  const openSetup = () => setSetup(true)

  const onSaved = (next: MarketConfig) => {
    setSetup(false)
    setConfig(next)
    setActive(0)
    setFlash('saved')
  }

  useInput((ch, key) => {
    if (setup) {
      return
    }

    if (ch === 'q' || key.escape) {
      return onClose()
    }

    if (ch === 'a') {
      return openSetup()
    }

    if (ch === 'r') {
      setFlash('refreshing…')

      return void refresh(true)
    }

    if (categories.length === 0) {
      return
    }

    if (key.tab || key.rightArrow || ch === 'l') {
      return setActive(i => (i + 1) % categories.length)
    }

    if (key.leftArrow || ch === 'h') {
      return setActive(i => (i - 1 + categories.length) % categories.length)
    }
  })

  const width = Math.max(40, cols - 4)
  const live = tick % 2 === 0
  const hasProviders = providers.size > 0

  // Fit columns to width (drop low-priority ones first).
  const visibleColumns: Column[] = []
  let used = 0

  for (const col of COLUMNS) {
    if (used + col.width + 1 > width) {
      break
    }

    visibleColumns.push(col)
    used += col.width + 1
  }

  const rows = useMemo(() => {
    const series = activeCategory
      ? DEFAULT_SERIES.filter(s => providers.has(s.provider) && s.category === activeCategory)
      : []

    return series.map(s => ({ quote: cacheRef.current[quoteKey(s.provider, s.symbol)], series: s }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeCategory, providers, cacheVersion])

  const cellColor = (v: null | number): string =>
    v === null || v === 0 ? t.color.muted : v > 0 ? t.color.ok : t.color.error

  const header = (
    <Box flexDirection="column" flexShrink={0} marginBottom={1}>
      <Text wrap="truncate-end">
        <Text bold color={t.color.primary}>
          MARKETS
        </Text>
        <Text color={t.color.muted}>{'   '}</Text>
        <Text color={fetching ? (live ? t.color.warn : t.color.muted) : hasProviders ? t.color.ok : t.color.muted}>●</Text>
        <Text color={t.color.muted}> {fetching ? 'updating…' : hasProviders ? 'live quotes' : 'no providers'} · </Text>
        <Text color={t.color.text}>
          {hasProviders ? `${config.providers.length} providers` : 'press a to add data'}
        </Text>
      </Text>
    </Box>
  )

  // No providers yet → prompt setup.
  if (!hasProviders && !setup) {
    return (
      <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
        {header}
        <Box alignItems="center" flexGrow={1} justifyContent="center">
          <Box flexDirection="column" width={Math.min(74, width)}>
            <Text bold color={t.color.text}>
              Build your market tape.
            </Text>
            <Box marginTop={1}>
              <Text color={t.color.muted} wrap="wrap">
                Enable data providers — Yahoo Finance, Frankfurter (ECB FX) and CoinGecko need no key; FRED, BLS and BEA
                use a free API key you enter once and store securely. Then pick the categories you want: indices,
                stocks, FX, crypto, commodities, rates, inflation, employment, GDP, trade.
              </Text>
            </Box>
            <Box marginTop={1}>
              <Text bold color={t.color.accent}>
                Press a
              </Text>
              <Text color={t.color.text}> to add market data.</Text>
            </Box>
          </Box>
        </Box>
        <Box flexDirection="column" flexShrink={0} marginTop={1}>
          <FooterChips chips={[{ k: 'a', label: 'Add data', run: openSetup }, { k: 'q', label: 'Close', run: onClose }]} t={t} />
          <Text color={t.color.muted} wrap="truncate-end">
            a add data · Esc/q close
          </Text>
        </Box>
      </Box>
    )
  }

  if (setup) {
    return (
      <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
        {header}
        <AddProviderModal
          cols={cols}
          initial={config}
          onCancel={() => setSetup(false)}
          onSaved={onSaved}
          rows={termRows}
          t={t}
        />
      </Box>
    )
  }

  const tabs = (
    <NoSelect flexShrink={0} marginBottom={1}>
      <Box>
        {categories.map((cat, i) => (
          <Box key={cat} onClick={() => setActive(i)}>
            {i > 0 ? <Text color={t.color.border}>{'  ·  '}</Text> : null}
            <Text bold={i === active} color={i === active ? t.color.accent : t.color.muted}>
              {cat}
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

  const cellText = (col: Column, q: MarketQuote | undefined, s: MarketSeries): { color?: string; text: string } => {
    switch (col.key) {
      case 'chg':
        return { color: cellColor(q?.change ?? null), text: q ? fmtSigned(q.change) : '—' }

      case 'last':
        return { text: q ? fmtNum(q.value, s.unit) : '—' }

      case 'name':
        return { text: q?.name || s.name }

      case 'pct':
        return { color: cellColor(q?.changePct ?? null), text: q ? fmtPct(q.changePct) : '—' }

      case 'symbol':
        return { color: t.color.muted, text: s.symbol }

      case 'updated':
        return { color: t.color.muted, text: q ? relTime(q.asOf) : '—' }

      case 'vol':
        return { color: t.color.muted, text: q ? fmtVol(q.volume) : '—' }

      default:
        return { text: '' }
    }
  }

  const body = (
    <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
      {columnHeader}
      {rule}
      <Box flexDirection="column">
        {rows.length === 0 ? (
          <Text color={t.color.muted} wrap="wrap">
            {fetching
              ? 'Fetching quotes…'
              : `No ${activeCategory ?? ''} series from your enabled providers. Press a to add a provider that covers it.`}
          </Text>
        ) : (
          rows.map(({ quote, series }) => (
            <Text key={`${series.provider}:${series.symbol}`} wrap="truncate-end">
              {visibleColumns.map(col => {
                const { color, text } = cellText(col, quote, series)

                return (
                  <Text color={color ?? t.color.text} key={col.key}>
                    {`${pad(text, col.width, col.align)} `}
                  </Text>
                )
              })}
            </Text>
          ))
        )}
      </Box>
    </Box>
  )

  const chips: FooterChip[] = [
    { k: '⇥', label: 'Category', run: () => setActive(i => (i + 1) % Math.max(1, categories.length)) },
    { k: 'a', label: 'Add data', run: openSetup },
    { k: 'r', label: 'Refresh', run: () => { setFlash('refreshing…'); void refresh(true) } },
    { k: 'q', label: 'Close', run: onClose }
  ]

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      <FooterChips chips={chips} t={t} />
      <Text color={t.color.muted} wrap="truncate-end">
        {flash ? <Text color={t.color.accent}>{flash} · </Text> : null}
        Tab/←→ category · a add data · r refresh · Esc/q close
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
