import { Box, NoSelect, Text, useInput, useStdout } from '@hermes/ink'
import { useEffect, useMemo, useRef, useState } from 'react'

import { patchOverlayState } from '../app/overlayStore.js'
import { DEFAULT_SERIES, MARKET_CATEGORIES, type MarketSeries } from '../content/marketProviders.js'
import { fetchQuotes } from '../lib/marketFetch.js'
import { getProviderKey } from '../lib/marketKeys.js'
import {
  loadMarketConfig,
  loadQuoteCache,
  type MarketConfig,
  type QuoteCache,
  quoteKey,
  saveMarketConfig,
  saveQuoteCache
} from '../lib/marketStore.js'
import { openExternalUrl } from '../lib/openExternalUrl.js'
import { sparkline } from '../lib/sparkline.js'
import type { Theme } from '../theme.js'

import { AddProviderModal } from './addProviderModal.js'
import { type FooterChip, FooterChips } from './footerChips.js'
import { MarketSearchModal } from './marketSearchModal.js'

export const openMarketsView = () => patchOverlayState({ markets: true })
export const closeMarketsView = () => patchOverlayState({ markets: false })

// Markets — a live tape backed by user-chosen providers, with a searchable
// universe and a rich per-line-item detail pane (sparkline + day/52-week ranges
// + heuristics). `a` adds providers/categories, `/` searches for any ticker.

const STALE_MS = 60_000
const WATCHLIST = 'Watchlist'

const fmtNum = (v: null | number | undefined, unit?: string): string => {
  if (v === null || v === undefined) {
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
    return `${(v / 1e9).toFixed(2)}B`
  }

  if (a >= 1e6) {
    return `${(v / 1e6).toFixed(2)}M`
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

  const m = Math.floor((Date.now() - ms) / 60_000)

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

const pad = (value: string, width: number, align: 'left' | 'right'): string => {
  const v = value.length > width ? `${value.slice(0, Math.max(0, width - 1))}…` : value

  return align === 'right' ? v.padStart(width) : v.padEnd(width)
}

// A low ──●── high position bar showing where `value` sits in [lo, hi].
const rangeBar = (value: null | number, lo: null | number | undefined, hi: null | number | undefined, width: number): string => {
  if (value === null || lo === null || lo === undefined || hi === null || hi === undefined || hi <= lo) {
    return '─'.repeat(width)
  }

  const pos = Math.min(width - 1, Math.max(0, Math.round(((value - lo) / (hi - lo)) * (width - 1))))

  return `${'─'.repeat(pos)}●${'─'.repeat(width - 1 - pos)}`
}

const sameSeries = (a: MarketSeries, b: MarketSeries): boolean =>
  a.provider === b.provider && a.symbol.toLowerCase() === b.symbol.toLowerCase()

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
  const [sel, setSel] = useState(0)
  const [tick, setTick] = useState(0)
  const [fetching, setFetching] = useState(false)
  const [modal, setModal] = useState<'' | 'providers' | 'search'>('')
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
  const watchlist = config.watchlist

  // Tabs: a Watchlist tab (if any) plus the selected provider categories.
  const categories = useMemo(() => {
    const base = MARKET_CATEGORIES.filter(c => config.categories.includes(c))

    return [...(watchlist.length ? [WATCHLIST] : []), ...base]
  }, [config, watchlist])

  const activeCategory = categories[Math.min(active, Math.max(0, categories.length - 1))]

  const seriesFor = (category: string | undefined): MarketSeries[] => {
    if (!category) {
      return []
    }

    if (category === WATCHLIST) {
      return watchlist
    }

    return DEFAULT_SERIES.filter(s => providers.has(s.provider) && s.category === category)
  }

  // Everything we fetch: the watchlist + enabled-provider series in selected cats.
  const allSeries = useMemo(
    () => [...watchlist, ...DEFAULT_SERIES.filter(s => providers.has(s.provider) && config.categories.includes(s.category))],
    [watchlist, providers, config]
  )

  const refresh = async (force: boolean) => {
    if (inflightRef.current || allSeries.length === 0) {
      return
    }

    const targets = force
      ? allSeries
      : allSeries.filter(s => {
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

  const persist = (next: MarketConfig) => {
    saveMarketConfig(next)
    setConfig(next)
  }

  const onProvidersSaved = (next: MarketConfig) => {
    setModal('')
    persist({ ...next, watchlist })
    setActive(0)
    setFlash('saved')
  }

  // Toggle a searched symbol in the watchlist (and ensure Yahoo is enabled).
  const toggleWatch = (s: MarketSeries) => {
    const exists = watchlist.some(w => sameSeries(w, s))
    const nextWatch = exists ? watchlist.filter(w => !sameSeries(w, s)) : [...watchlist, s]
    const nextProviders = exists || providers.has(s.provider) ? config.providers : [...config.providers, s.provider]
    persist({ ...config, providers: nextProviders, watchlist: nextWatch })
    setFlash(exists ? `removed ${s.symbol}` : `added ${s.symbol}`)
  }

  const rows = useMemo(() => {
    return seriesFor(activeCategory).map(s => ({ quote: cacheRef.current[quoteKey(s.provider, s.symbol)], series: s }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeCategory, providers, watchlist, cacheVersion])

  const clampedSel = Math.min(sel, Math.max(0, rows.length - 1))
  const selectedRow = rows[clampedSel]

  useInput((ch, key) => {
    if (modal) {
      return
    }

    if (ch === 'q' || key.escape) {
      return onClose()
    }

    if (ch === 'a') {
      return setModal('providers')
    }

    if (ch === '/') {
      return setModal('search')
    }

    if (ch === 'r') {
      setFlash('refreshing…')

      return void refresh(true)
    }

    if (key.return && selectedRow?.series.provider === 'yahoo') {
      if (openExternalUrl(`https://finance.yahoo.com/quote/${encodeURIComponent(selectedRow.series.symbol)}`)) {
        setFlash('opened in browser')
      }

      return
    }

    if (key.tab || key.rightArrow) {
      setSel(0)

      return setActive(i => (i + 1) % Math.max(1, categories.length))
    }

    if (key.leftArrow) {
      setSel(0)

      return setActive(i => (i - 1 + Math.max(1, categories.length)) % Math.max(1, categories.length))
    }

    if (key.upArrow || ch === 'k' || key.wheelUp) {
      return setSel(i => Math.max(0, i - 1))
    }

    if (key.downArrow || ch === 'j' || key.wheelDown) {
      return setSel(i => Math.min(Math.max(0, rows.length - 1), i + 1))
    }
  })

  const width = Math.max(40, cols - 4)
  const live = tick % 2 === 0
  const hasContent = providers.size > 0 || watchlist.length > 0
  const contentHeight = Math.max(8, termRows - 8)

  const header = (
    <Box flexDirection="column" flexShrink={0} marginBottom={1}>
      <Text wrap="truncate-end">
        <Text bold color={t.color.primary}>
          MARKETS
        </Text>
        <Text color={t.color.muted}>{'   '}</Text>
        <Text color={fetching ? (live ? t.color.warn : t.color.muted) : hasContent ? t.color.ok : t.color.muted}>●</Text>
        <Text color={t.color.muted}> {fetching ? 'updating…' : hasContent ? 'live quotes' : 'no providers'} · </Text>
        <Text color={t.color.text}>
          {hasContent ? `${config.providers.length} providers · ${watchlist.length} watched` : 'press a to add data'}
        </Text>
      </Text>
    </Box>
  )

  // Empty: no providers and no watchlist.
  if (!hasContent && !modal) {
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
                Enable data providers (Yahoo, Frankfurter and CoinGecko need no key; FRED/BLS/BEA use a free key) and
                pick categories — or search for any ticker and add it to your watchlist.
              </Text>
            </Box>
            <Box marginTop={1}>
              <Text bold color={t.color.accent}>
                Press a
              </Text>
              <Text color={t.color.text}> to add providers · </Text>
              <Text bold color={t.color.accent}>
                /
              </Text>
              <Text color={t.color.text}> to search for a ticker.</Text>
            </Box>
          </Box>
        </Box>
        <Box flexDirection="column" flexShrink={0} marginTop={1}>
          <FooterChips chips={[{ k: 'a', label: 'Add data', run: () => setModal('providers') }, { k: '/', label: 'Search', run: () => setModal('search') }, { k: 'q', label: 'Close', run: onClose }]} t={t} />
          <Text color={t.color.muted} wrap="truncate-end">
            a add providers · / search · Esc/q close
          </Text>
        </Box>
      </Box>
    )
  }

  if (modal === 'providers') {
    return (
      <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
        {header}
        <AddProviderModal cols={cols} initial={config} onCancel={() => setModal('')} onSaved={onProvidersSaved} rows={termRows} t={t} />
      </Box>
    )
  }

  if (modal === 'search') {
    return (
      <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
        {header}
        <MarketSearchModal
          cols={cols}
          isWatched={s => watchlist.some(w => sameSeries(w, s))}
          onAdd={toggleWatch}
          onClose={() => setModal('')}
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
          <Box key={cat} onClick={() => { setActive(i); setSel(0) }}>
            {i > 0 ? <Text color={t.color.border}>{'  ·  '}</Text> : null}
            <Text bold={i === active} color={i === active ? t.color.accent : t.color.muted}>
              {cat}
            </Text>
          </Box>
        ))}
      </Box>
    </NoSelect>
  )

  // ---- left: selectable quote table ---------------------------------------
  const detailWidth = Math.min(46, Math.max(34, Math.floor(width * 0.4)))
  const tableWidth = Math.max(24, width - detailWidth - 2)
  const pctW = 9
  const lastW = 12
  const nameW = Math.max(10, tableWidth - 2 - lastW - pctW - 3)
  const listRows = Math.max(3, contentHeight - 1)
  const listStart = Math.max(0, Math.min(clampedSel - Math.floor(listRows / 2), rows.length - listRows))
  const windowed = rows.slice(Math.max(0, listStart), Math.max(0, listStart) + listRows)

  const cellColor = (v: null | number | undefined): string =>
    v === null || v === undefined || v === 0 ? t.color.muted : v > 0 ? t.color.ok : t.color.error

  const table = (
    <Box
      borderBottom={false}
      borderColor={t.color.border}
      borderLeft={false}
      borderStyle="single"
      borderTop={false}
      flexDirection="column"
      flexShrink={0}
      height={contentHeight}
      overflow="hidden"
      paddingRight={1}
      width={tableWidth}
    >
      <Text bold color={t.color.label} wrap="truncate-end">
        {pad('NAME', nameW + 2, 'left')}
        {pad('LAST', lastW, 'right')} {pad('CHG%', pctW, 'right')}
      </Text>
      <Box flexDirection="column">
        {rows.length === 0 ? (
          <Text color={t.color.muted} wrap="wrap">
            {fetching ? 'Fetching…' : `No ${activeCategory ?? ''} series. Press a to add a provider, or / to search.`}
          </Text>
        ) : (
          windowed.map(({ quote, series }, i) => {
            const idx = listStart + i
            const on = idx === clampedSel

            return (
              <Box key={`${series.provider}:${series.symbol}`} onClick={() => setSel(idx)} width="100%">
                <Text wrap="truncate-end">
                  <Text color={on ? t.color.accent : t.color.border}>{on ? '▸ ' : '  '}</Text>
                  <Text bold={on} color={on ? t.color.text : t.color.label}>
                    {pad(quote?.name || series.name, nameW, 'left')}
                  </Text>
                  <Text color={on ? t.color.text : t.color.label}> {pad(fmtNum(quote?.value, series.unit), lastW, 'right')}</Text>
                  <Text color={cellColor(quote?.changePct ?? null)}> {pad(quote ? fmtPct(quote.changePct) : '—', pctW, 'right')}</Text>
                </Text>
              </Box>
            )
          })
        )}
      </Box>
    </Box>
  )

  // ---- right: detail pane --------------------------------------------------
  const q = selectedRow?.quote
  const s = selectedRow?.series
  const spark = q?.history ? sparkline(q.history, detailWidth - 2) : ''
  const fromHigh = q?.value != null && q.week52High ? ((q.value - q.week52High) / q.week52High) * 100 : null
  const barW = Math.max(10, detailWidth - 14)

  const detail = (
    <Box flexDirection="column" flexShrink={0} height={contentHeight} marginLeft={1} overflow="hidden" width={detailWidth}>
      {s ? (
        <Box flexDirection="column">
          <Text bold color={t.color.text} wrap="truncate-end">
            {q?.name || s.name}
          </Text>
          <Text color={t.color.muted} wrap="truncate-end">
            {s.symbol}
            {q?.exchange ? ` · ${q.exchange}` : ''} · {s.category}
            {q?.currency ? ` · ${q.currency}` : ''}
          </Text>

          <Box marginTop={1}>
            <Text bold color={t.color.text}>
              {fmtNum(q?.value ?? null, s.unit)}
            </Text>
            <Text color={cellColor(q?.change ?? null)}>
              {'   '}
              {q ? fmtSigned(q.change) : '—'} ({q ? fmtPct(q.changePct) : '—'})
            </Text>
          </Box>

          {spark ? (
            <Box marginTop={1}>
              <Text color={(q?.changePct ?? 0) >= 0 ? t.color.ok : t.color.error}>{spark}</Text>
            </Box>
          ) : null}

          <Box flexDirection="column" marginTop={1}>
            {q?.dayLow != null && q?.dayHigh != null ? (
              <Text color={t.color.muted} wrap="truncate-end">
                <Text color={t.color.label}>{'Day  '}</Text>
                {fmtNum(q.dayLow)} <Text color={t.color.border}>{rangeBar(q.value, q.dayLow, q.dayHigh, barW)}</Text> {fmtNum(q.dayHigh)}
              </Text>
            ) : null}
            {q?.week52Low != null && q?.week52High != null ? (
              <Text color={t.color.muted} wrap="truncate-end">
                <Text color={t.color.label}>{'52w  '}</Text>
                {fmtNum(q.week52Low)} <Text color={t.color.border}>{rangeBar(q.value, q.week52Low, q.week52High, barW)}</Text> {fmtNum(q.week52High)}
              </Text>
            ) : null}
            {fromHigh != null ? (
              <Text color={cellColor(fromHigh)} wrap="truncate-end">
                {`${fmtPct(fromHigh)} from 52-week high`}
              </Text>
            ) : null}
          </Box>

          <Box flexDirection="column" marginTop={1}>
            {q?.prevClose != null ? (
              <Text color={t.color.muted}>
                <Text color={t.color.label}>Prev close </Text>
                {fmtNum(q.prevClose)}
              </Text>
            ) : null}
            {q?.volume != null ? (
              <Text color={t.color.muted}>
                <Text color={t.color.label}>Volume     </Text>
                {fmtVol(q.volume)}
              </Text>
            ) : null}
            <Text color={t.color.muted}>
              <Text color={t.color.label}>Updated    </Text>
              {q ? relTime(q.asOf) : '—'} · {s.provider}
            </Text>
          </Box>

          {s.provider === 'yahoo' ? (
            <Box marginTop={1}>
              <Text color={t.color.muted} wrap="wrap">
                Press Enter to open {s.symbol} on Yahoo Finance.
              </Text>
            </Box>
          ) : null}
        </Box>
      ) : (
        <Text color={t.color.muted}>Select a row to see details.</Text>
      )}
    </Box>
  )

  const chips: FooterChip[] = [
    { k: '↑↓', label: 'Select' },
    { k: '⇥', label: 'Category', run: () => { setSel(0); setActive(i => (i + 1) % Math.max(1, categories.length)) } },
    { k: '/', label: 'Search', run: () => setModal('search') },
    { k: 'a', label: 'Add data', run: () => setModal('providers') },
    { k: 'r', label: 'Refresh', run: () => { setFlash('refreshing…'); void refresh(true) } },
    { k: 'q', label: 'Close', run: onClose }
  ]

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      <FooterChips chips={chips} t={t} />
      <Text color={t.color.muted} wrap="truncate-end">
        {flash ? <Text color={t.color.accent}>{flash} · </Text> : null}
        ↑↓/jk select · Tab/←→ category · ⏎ open · / search · a add data · r refresh · Esc/q close
      </Text>
    </Box>
  )

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      {tabs}
      <Box flexDirection="row" flexShrink={0} height={contentHeight}>
        {table}
        {detail}
      </Box>
      {footer}
    </Box>
  )
}
