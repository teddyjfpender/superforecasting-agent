import { Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text, useInput, useStdout } from '@hermes/ink'
import { Fragment, type ReactNode, useEffect, useMemo, useRef, useState } from 'react'

import { forecastQuestionDetailSections } from '../app/forecastPanel.js'
import { patchOverlayState } from '../app/overlayStore.js'
import type { GatewayClient } from '../gatewayClient.js'
import type {
  ForecastAnalystNote,
  ForecastQuestionPacketResponse,
  ForecastWorkspaceItem,
  ForecastWorkspacePanel,
  ForecastWorkspaceResponse
} from '../gatewayTypes.js'
import type { PanelSection } from '../types.js'
import {
  type BandPoint,
  bandChart,
  boxWhisker,
  clamp01,
  deltaGlyph,
  histogram,
  type HistogramBar,
  levelSparkline,
  pct,
  pctDelta,
  shortDate
} from '../lib/forecastCharts.js'
import { asRpcResult } from '../lib/rpc.js'
import { OverlayScrollbar } from './agentsOverlay.js'
import { windowItems } from './overlayControls.js'
import type { Theme } from '../theme.js'

export const openForecastsWorkspace = (initialId: string | null = null) =>
  patchOverlayState({ forecasts: true, forecastsInitialId: initialId })

export const closeForecastsWorkspace = () =>
  patchOverlayState({ forecasts: false, forecastsInitialId: null })

const WIDE_COLS = 100
const CONF_BAND_K = 0.18

// Packet sections rendered under the visual summary. Intentionally excludes the
// header facts (question/Current Forecast/Ledger State), Recent Evidence, and
// Resolution — ForecastDetail already shows those — so the tail is purely the
// long-form content the desk view omits.
const TAIL_SECTION_TITLES = new Set<string>([
  'Forecast History',
  'Assumptions And References',
  'Model Runs',
  'Actions'
])

interface ForecastsWorkspaceProps {
  gw: GatewayClient
  initialId?: null | string
  onClose: () => void
  t: Theme
}

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)

const trimNum = (value: number): string => {
  const fixed = value.toFixed(2)
  return fixed.replace(/\.?0+$/, '') || '0'
}

const unitSuffix = (units: null | string | undefined): string => {
  const u = (units ?? '').toLowerCase()
  if (u.includes('percent') || u.includes('%')) {
    return '%'
  }
  return ''
}

/**
 * Headline label for a forecast.
 *   probability/categorical → a percent ("59%")
 *   distribution            → a continuous summary ("μ 4.23% · σ 0.10")
 * so a CPI mean never renders as a misleading "310%" or a raw JSON dump.
 */
export const headlineLabel = (item: ForecastWorkspaceItem): string => {
  const dist = item.distribution
  if (item.headline_kind === 'distribution' && dist && finite(dist.mean)) {
    const suffix = unitSuffix(item.units)
    const parts = [`μ ${trimNum(dist.mean)}${suffix}`]
    if (finite(dist.sd)) {
      parts.push(`σ ${trimNum(dist.sd)}`)
    }
    return parts.join(' · ')
  }
  const headline = item.headline_probability
  if (finite(headline) && headline >= 0 && headline <= 1) {
    return pct(headline)
  }
  if (finite(headline)) {
    return item.probability_display ?? String(headline)
  }
  return item.probability_display ?? '—'
}

/** Compact one-token headline for the master list (e.g. "59%" or "μ4.23%"). */
const headlineCompact = (item: ForecastWorkspaceItem): string => {
  if (item.headline_kind === 'distribution' && item.distribution && finite(item.distribution.mean)) {
    return `μ${trimNum(item.distribution.mean)}${unitSuffix(item.units)}`
  }
  const headline = item.headline_probability
  if (finite(headline) && headline >= 0 && headline <= 1) {
    return pct(headline)
  }
  return finite(headline) ? String(headline) : '—'
}

/** Delta in headline units: percent-points for probabilities, outcome units (Δμ) for distributions. */
const deltaLabel = (item: ForecastWorkspaceItem): string => {
  const d = item.delta
  if (!finite(d) || Math.abs(d) < (item.headline_kind === 'distribution' ? 1e-6 : 0.005)) {
    return '· flat'
  }
  if (item.headline_kind === 'distribution') {
    return `${deltaGlyph(d)} Δμ ${d > 0 ? '+' : ''}${trimNum(d)}${unitSuffix(item.units)}`
  }
  return pctDelta(d)
}

const truncate = (value: string, max: number): string =>
  value.length <= max ? value : `${value.slice(0, Math.max(0, max - 1))}…`

export const matchesFilter = (item: ForecastWorkspaceItem, query: string): boolean => {
  if (!query) {
    return true
  }
  const needle = query.toLowerCase()
  const haystack = [item.title, item.domain, item.id, ...(item.topics ?? [])]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
  return haystack.includes(needle)
}

/** Categorical / bucket distribution → sorted bars; null for scalar or mean/sd shapes. */
export const distributionBars = (probability: ForecastWorkspaceItem['probability']): HistogramBar[] | null => {
  if (!probability || typeof probability !== 'object' || Array.isArray(probability)) {
    return null
  }
  const entries = Object.entries(probability).filter(([, value]) => finite(value)) as [string, number][]
  if (entries.length < 2) {
    return null
  }
  const distributionalKeys = new Set(['mean', 'mu', 'sd', 'sigma', 'std', 'stdev', 'variance', 'expected', 'value'])
  if (entries.every(([key]) => distributionalKeys.has(key.toLowerCase()))) {
    return null
  }
  return entries.map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value)
}

/** Confidence/spread band for one history point. Latest point prefers the panel spread. */
const bandForPoint = (
  y: number,
  confidence: null | number | undefined,
  isLatest: boolean,
  panel: ForecastWorkspacePanel | null | undefined
): { hi?: number; lo?: number } => {
  if (isLatest && panel?.spread && finite(panel.spread.min) && finite(panel.spread.max)) {
    return { hi: panel.spread.max, lo: panel.spread.min }
  }
  if (!finite(confidence)) {
    return {}
  }
  const half = clamp01(1 - confidence) * CONF_BAND_K
  return { hi: clamp01(y + half), lo: clamp01(y - half) }
}

export const historyToBandPoints = (item: ForecastWorkspaceItem): BandPoint[] => {
  const history = item.history ?? []
  const isDistribution = item.headline_kind === 'distribution'
  return history.map((point, index) => {
    const y = point.headline_probability
    if (!finite(y)) {
      return { y: null }
    }
    // Distribution snapshots carry their own 90% interval (in outcome units);
    // use it directly and never the panel's probability spread.
    if (finite(point.band_low) && finite(point.band_high)) {
      return { hi: point.band_high, lo: point.band_low, y }
    }
    const isLatest = index === history.length - 1
    const band = bandForPoint(
      y,
      point.confidence ?? item.confidence,
      !isDistribution && isLatest,
      isDistribution ? null : item.panel
    )
    return { hi: band.hi ?? null, lo: band.lo ?? null, y }
  })
}

const MIN_CHART_SPAN = 0.12

/**
 * Auto-zoom the y-axis to the data + band range so small probability moves and
 * the confidence band are actually visible (a fixed 0..1 axis squashes a
 * 0.49→0.58 series into one row). A minimum span stops a flat series from
 * exploding into noise; probability series stay clamped to [0,1]; the axis
 * labels report the real bounds so the zoom is honest.
 */
export const chartScale = (points: BandPoint[]): { yMax: number; yMin: number } => {
  const values: number[] = []
  for (const point of points) {
    if (finite(point.y)) {
      values.push(point.y)
    }
    if (finite(point.lo)) {
      values.push(point.lo)
    }
    if (finite(point.hi)) {
      values.push(point.hi)
    }
  }
  if (!values.length) {
    return { yMax: 1, yMin: 0 }
  }
  const probabilityLike = values.every(value => value >= 0 && value <= 1)
  let lo = Math.min(...values)
  let hi = Math.max(...values)
  if (hi - lo < MIN_CHART_SPAN) {
    const mid = (lo + hi) / 2
    lo = mid - MIN_CHART_SPAN / 2
    hi = mid + MIN_CHART_SPAN / 2
  }
  const pad = (hi - lo) * 0.15
  lo -= pad
  hi += pad
  if (probabilityLike) {
    lo = Math.max(0, lo)
    hi = Math.min(1, hi)
  }
  if (hi - lo < 1e-6) {
    hi = lo + 1
  }
  return { yMax: hi, yMin: lo }
}

export function ForecastsWorkspace({ gw, initialId = null, onClose, t }: ForecastsWorkspaceProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24

  const [items, setItems] = useState<ForecastWorkspaceItem[]>([])
  const [desk, setDesk] = useState<{ active: number; alerts: number; closing: number; generatedAt?: string }>({
    active: 0,
    alerts: 0,
    closing: 0
  })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<null | string>(null)
  const [cursor, setCursor] = useState(0)
  const [focus, setFocus] = useState<'detail' | 'list'>('list')
  const [query, setQuery] = useState('')
  const [filtering, setFiltering] = useState(false)
  const [flash, setFlash] = useState('')
  const [now, setNow] = useState(0)
  // The "tail end" detail (forecast history, assumptions, model runs, the action
  // playbook) lives in the `forecast.question` packet, not the lighter
  // `forecast.workspace` item. Fetch it per-selection and render it under the
  // visual summary inside the detail pane's own ScrollBox.
  const [packet, setPacket] = useState<ForecastQuestionPacketResponse | null>(null)
  const [packetId, setPacketId] = useState<null | string>(null)
  const initialIdRef = useRef(initialId)
  const detailScrollRef = useRef<null | ScrollBoxHandle>(null)

  const wide = cols >= WIDE_COLS

  const load = (announce = false) => {
    setLoading(true)
    gw.request<unknown>('forecast.workspace', { limit: 75 })
      .then(raw => {
        const result = asRpcResult<ForecastWorkspaceResponse>(raw)
        if (!result) {
          setError('forecast.workspace returned no data')
          setLoading(false)
          return
        }
        const forecasts = result.forecasts ?? []
        setItems(forecasts)
        setDesk({
          active: result.active_count ?? forecasts.length,
          alerts: result.open_alert_count ?? 0,
          closing: result.closing_soon_count ?? 0,
          generatedAt: result.generated_at
        })
        setError(null)
        setLoading(false)
        if (announce) {
          setFlash('refreshed')
        }
        if (initialIdRef.current) {
          const idx = forecasts.findIndex(item => item.id === initialIdRef.current)
          initialIdRef.current = null
          if (idx >= 0) {
            setCursor(idx)
          }
        }
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err))
        setLoading(false)
      })
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gw])

  useEffect(() => {
    // Drives OverlayScrollbar reflow detection while the user scrolls the
    // detail pane (the content height changes per selected forecast).
    const id = setInterval(() => setNow(value => value + 1), 500)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    // Re-opening the workspace on a different forecast (e.g. `/forecast <id>`
    // while it is already open) must jump the cursor. useRef alone never sees
    // the prop change, so sync it here and navigate once items are loaded.
    if (!initialId) {
      return
    }
    initialIdRef.current = initialId
    const idx = items.findIndex(item => item.id === initialId)
    if (idx >= 0) {
      setCursor(idx)
      setFocus('list')
    }
  }, [initialId, items])

  const filtered = useMemo(() => items.filter(item => matchesFilter(item, query)), [items, query])

  useEffect(() => {
    // Keep the cursor inside the (possibly filtered) list.
    if (cursor > filtered.length - 1) {
      setCursor(Math.max(0, filtered.length - 1))
    }
  }, [cursor, filtered.length])

  useEffect(() => {
    detailScrollRef.current?.scrollTo(0)
  }, [cursor])

  const selected = filtered[cursor] ?? null
  const selectedId = selected?.id ?? null

  useEffect(() => {
    if (!selectedId) {
      setPacket(null)
      setPacketId(null)
      return
    }
    // Race guard: if the cursor moves before this resolves, drop the stale
    // result so the tail never shows a previous forecast's history/evidence.
    let cancelled = false
    gw.request<unknown>('forecast.question', { id: selectedId })
      .then(raw => {
        if (cancelled) {
          return
        }
        const result = asRpcResult<ForecastQuestionPacketResponse>(raw)
        setPacket(result ?? null)
        setPacketId(result ? selectedId : null)
      })
      .catch(() => {
        if (cancelled) {
          return
        }
        setPacket(null)
        setPacketId(null)
      })
    return () => {
      cancelled = true
    }
  }, [selectedId, gw])

  // Only the sections the visual summary does NOT already cover — history,
  // assumptions/references, model runs, and the action playbook.
  const packetTail = useMemo(() => {
    if (!packet || packetId !== selectedId) {
      return null
    }
    return forecastQuestionDetailSections(packet).filter(
      section => section.title && TAIL_SECTION_TITLES.has(section.title)
    )
  }, [packet, packetId, selectedId])
  const tailLoading = !!selectedId && packetId !== selectedId

  // The analyst write-up time series (oldest-first). The most recent note is the
  // desk quick-read; the rest are the reviewable log.
  const analystNotes = useMemo(() => {
    if (!packet || packetId !== selectedId) {
      return null
    }
    return packet.packet?.analyst_notes ?? []
  }, [packet, packetId, selectedId])
  const latestNote = analystNotes && analystNotes.length ? analystNotes[analystNotes.length - 1] : null
  const priorNotes = analystNotes ? analystNotes.slice(0, -1).reverse() : []

  const closeWith = () => {
    onClose()
  }

  const detailPageSize = Math.max(4, termRows - 12)

  useInput((ch, key) => {
    // Filter text-entry mode swallows printable keys.
    if (filtering) {
      if (key.return) {
        return setFiltering(false)
      }
      if (key.escape) {
        setQuery('')
        return setFiltering(false)
      }
      if (key.backspace || key.delete) {
        return setQuery(q => q.slice(0, -1))
      }
      if (ch && !key.ctrl && !key.meta && ch.length === 1 && ch >= ' ') {
        return setQuery(q => q + ch)
      }
      return
    }

    if (ch === 'q') {
      return closeWith()
    }

    if (key.escape) {
      return focus === 'detail' ? setFocus('list') : closeWith()
    }

    if (ch === 'r') {
      return load(true)
    }

    if (ch === '/') {
      setQuery('')
      return setFiltering(true)
    }

    if (focus === 'detail') {
      if (key.leftArrow || ch === 'h') {
        return setFocus('list')
      }
      if (key.upArrow || ch === 'k' || key.wheelUp) {
        return detailScrollRef.current?.scrollBy(-2)
      }
      if (key.downArrow || ch === 'j' || key.wheelDown) {
        return detailScrollRef.current?.scrollBy(2)
      }
      if (key.pageUp || (key.ctrl && ch === 'u')) {
        return detailScrollRef.current?.scrollBy(-detailPageSize)
      }
      if (key.pageDown || (key.ctrl && ch === 'd')) {
        return detailScrollRef.current?.scrollBy(detailPageSize)
      }
      if (ch === 'g') {
        return detailScrollRef.current?.scrollTo(0)
      }
      if (ch === 'G') {
        return detailScrollRef.current?.scrollToBottom?.()
      }
      return
    }

    // List focus.
    if ((key.return || key.rightArrow || ch === 'l') && selected) {
      return setFocus('detail')
    }
    if (key.upArrow || ch === 'k' || key.wheelUp) {
      return setCursor(c => Math.max(0, c - 1))
    }
    if (key.downArrow || ch === 'j' || key.wheelDown) {
      return setCursor(c => Math.min(Math.max(0, filtered.length - 1), c + 1))
    }
    if (ch === 'g') {
      return setCursor(0)
    }
    if (ch === 'G') {
      return setCursor(Math.max(0, filtered.length - 1))
    }
  })

  // ── Header ──────────────────────────────────────────────────────────
  const header = (
    <Box flexDirection="column" flexShrink={0} marginBottom={1}>
      <Text wrap="truncate-end">
        <Text bold color={t.color.primary}>
          FORECASTS
        </Text>
        <Text color={t.color.muted}>{'   '}</Text>
        <Text color={t.color.text}>{desk.active}</Text>
        <Text color={t.color.muted}> active · </Text>
        <Text color={desk.closing > 0 ? t.color.warn : t.color.label}>{desk.closing}</Text>
        <Text color={t.color.muted}> closing soon · </Text>
        <Text color={desk.alerts > 0 ? t.color.statusBad : t.color.label}>{desk.alerts}</Text>
        <Text color={t.color.muted}>
          {` open alert${desk.alerts === 1 ? '' : 's'}`}
          {desk.generatedAt ? ` · as of ${shortDate(desk.generatedAt)}` : ''}
        </Text>
      </Text>
    </Box>
  )

  // ── Body ────────────────────────────────────────────────────────────
  let body: ReactNode
  if (loading && !items.length) {
    body = (
      <Box flexGrow={1}>
        <Text color={t.color.muted}>Loading forecast desk…</Text>
      </Box>
    )
  } else if (error) {
    body = (
      <Box flexDirection="column" flexGrow={1}>
        <Text color={t.color.error}>Failed to load forecasts: {error}</Text>
        <Text color={t.color.muted}>Press r to retry · q to close</Text>
      </Box>
    )
  } else if (!filtered.length) {
    body = (
      <Box flexDirection="column" flexGrow={1}>
        <Text color={t.color.muted}>
          {items.length ? `No forecasts match "${query}".` : 'No active forecasts. Create one with /forecast new …'}
        </Text>
      </Box>
    )
  } else {
    const listW = wide ? Math.max(34, Math.floor(cols * 0.4)) : cols - 2
    const detailW = wide ? cols - listW - 3 : cols - 2
    const visibleRows = Math.max(1, termRows - 11)

    const list = (
      <ForecastList
        cursor={cursor}
        focus={focus === 'list'}
        items={filtered}
        showWhenNarrowFocusList={!wide && focus === 'list'}
        t={t}
        visibleRows={visibleRows}
        width={listW}
      />
    )

    const detail = selected ? (
      <Box flexDirection="row" flexGrow={1} flexShrink={1} minHeight={0}>
        <ScrollBox flexDirection="column" flexGrow={1} flexShrink={1} ref={detailScrollRef}>
          <Box flexDirection="column" paddingBottom={3} paddingRight={1}>
            <ForecastDetail
              afterChart={
                latestNote ? (
                  <>
                    <Rule t={t} width={detailW} />
                    <AnalystNote
                      note={latestNote}
                      showStance={selected.headline_kind !== 'distribution'}
                      t={t}
                      variant={latestNote.kind === 'retrospective' ? 'retrospective' : 'quickread'}
                      width={detailW}
                    />
                    <Rule t={t} width={detailW} />
                  </>
                ) : tailLoading ? (
                  <Box marginTop={1}>
                    <Text color={t.color.muted}>loading quick read…</Text>
                  </Box>
                ) : null
              }
              item={selected}
              t={t}
              width={detailW}
            />
            {packetTail && packetTail.length ? (
              <ForecastPacketTail sections={packetTail} t={t} width={detailW} />
            ) : tailLoading ? (
              <Box marginTop={1}>
                <Text color={t.color.muted}>loading detail…</Text>
              </Box>
            ) : null}
            <AnalystLog notes={priorNotes} t={t} />
          </Box>
        </ScrollBox>
        <NoSelect flexShrink={0} marginLeft={1}>
          <OverlayScrollbar scrollRef={detailScrollRef} t={t} tick={now} />
        </NoSelect>
      </Box>
    ) : null

    if (wide) {
      body = (
        <Box flexDirection="row" flexGrow={1} flexShrink={1} minHeight={0}>
          <Box flexDirection="column" flexShrink={0} width={listW}>
            {list}
          </Box>
          <Box flexDirection="column" flexShrink={0} marginLeft={1}>
            <Text color={t.color.border}>{'│'}</Text>
          </Box>
          <Box flexDirection="column" flexGrow={1} flexShrink={1} marginLeft={1} minHeight={0}>
            {detail}
          </Box>
        </Box>
      )
    } else {
      body = (
        <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
          {focus === 'list' ? list : detail}
        </Box>
      )
    }
  }

  // ── Footer ──────────────────────────────────────────────────────────
  const footerHint = filtering
    ? `filter: ${truncate(query, Math.max(8, cols - 30))}▌  · Enter apply · Esc clear`
    : focus === 'detail'
      ? '↑↓/jk scroll · PgUp/PgDn page · g/G top/bottom · ←/Esc back to list · r refresh · q close'
      : `↑↓/jk move · Enter/→ focus detail · / filter${query ? ` (${filtered.length}/${items.length})` : ''} · r refresh · Esc/q close`

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      {flash ? <Text color={t.color.accent}>{flash}</Text> : null}
      <Text color={t.color.muted} wrap="truncate-end">
        {footerHint}
      </Text>
    </Box>
  )

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      {body}
      {footer}
    </Box>
  )
}

// ── Master list ───────────────────────────────────────────────────────────

interface ForecastListProps {
  cursor: number
  focus: boolean
  items: ForecastWorkspaceItem[]
  showWhenNarrowFocusList: boolean
  t: Theme
  visibleRows: number
  width: number
}

function ForecastList({ cursor, focus, items, t, visibleRows, width }: ForecastListProps) {
  const { items: windowed, offset } = windowItems(items, cursor, visibleRows)
  return (
    <Box flexDirection="column" flexGrow={0} flexShrink={0} minHeight={0} overflow="hidden">
      {windowed.map((item, i) => (
        <ForecastListRow
          active={offset + i === cursor && focus}
          item={item}
          key={item.id ?? offset + i}
          t={t}
          width={width}
        />
      ))}
      {items.length > windowed.length ? (
        <Text color={t.color.muted}>
          {'  '}
          {offset + windowed.length}/{items.length}
        </Text>
      ) : null}
    </Box>
  )
}

function ForecastListRow({
  active,
  item,
  t,
  width
}: {
  active: boolean
  item: ForecastWorkspaceItem
  t: Theme
  width: number
}) {
  const delta = item.delta
  const glyph = deltaGlyph(delta)
  const deltaColor = !finite(delta) || Math.abs(delta) < 0.005 ? t.color.muted : delta > 0 ? t.color.ok : t.color.error
  const sparkValues = (item.history ?? []).slice(-8).map(point => point.headline_probability ?? null)
  // Probabilities use the fixed 0..1 scale; distribution means (e.g. ~4.2%)
  // are scaled to their own data range so the trend is visible, not clamped flat.
  const sparkOpts =
    item.headline_kind === 'distribution'
      ? (() => {
          const finiteVals = sparkValues.filter((v): v is number => finite(v))
          return finiteVals.length ? { yMax: Math.max(...finiteVals), yMin: Math.min(...finiteVals) } : {}
        })()
      : {}
  const spark = levelSparkline(sparkValues, sparkOpts)
  const probText = headlineCompact(item)
  // Reserve: marker(2) prob(6) gap(1) glyph(1) gap(1) spark(8) → ~20; rest for title.
  const titleW = Math.max(10, width - 21)
  const title = truncate(item.title ?? item.id ?? 'untitled', titleW).padEnd(titleW)
  const alertBadge = (item.open_alert_count ?? 0) > 0 ? `!${item.open_alert_count}` : ''
  return (
    <Box width={width}>
      <Text backgroundColor={active ? t.color.selectionBg : undefined} wrap="truncate-end">
        <Text bold={active} color={active ? t.color.primary : t.color.muted}>
          {active ? '▸ ' : '  '}
        </Text>
        <Text bold={active} color={active ? t.color.text : t.color.label}>
          {title}
        </Text>
        <Text color={t.color.text}> {probText.padStart(6)}</Text>
        <Text color={deltaColor}> {glyph}</Text>
        <Text color={t.color.border}> {spark}</Text>
        {alertBadge ? <Text color={t.color.statusBad}> {alertBadge}</Text> : null}
      </Text>
    </Box>
  )
}

// ── Detail pane ─────────────────────────────────────────────────────────────

function SectionTitle({ children, t }: { children: string; t: Theme }) {
  return (
    <Box marginTop={1}>
      <Text bold color={t.color.accent}>
        {children}
      </Text>
    </Box>
  )
}

function KV({ k, t, v }: { k: string; t: Theme; v: string }) {
  return (
    <Text wrap="truncate-end">
      <Text color={t.color.label}>{k.padEnd(13)}</Text>
      <Text color={t.color.text}>{v}</Text>
    </Text>
  )
}

export function ForecastDetail({
  afterChart,
  item,
  t,
  width
}: {
  afterChart?: ReactNode
  item: ForecastWorkspaceItem
  t: Theme
  width: number
}) {
  const delta = item.delta
  const deltaColor = !finite(delta) || Math.abs(delta) < 0.005 ? t.color.muted : delta > 0 ? t.color.ok : t.color.error
  const bandPoints = useMemo(() => historyToBandPoints(item), [item])
  const hasSeries = bandPoints.some(point => finite(point.y))
  const scale = useMemo(() => chartScale(bandPoints), [bandPoints])
  const chart = useMemo(
    // Never exceed the pane width (clamps the chart on very narrow terminals so
    // the line-drawn axis/markers don't wrap and shred the layout).
    () => (hasSeries ? bandChart(bandPoints, { height: 9, width: Math.min(56, Math.max(1, width - 1)), ...scale }) : null),
    [bandPoints, hasSeries, scale, width]
  )
  // Prefer the server-classified PMF (buckets only, moments/intervals stripped);
  // fall back to the raw dict for plain categorical forecasts.
  const bars = useMemo(() => {
    const pmf = item.distribution?.pmf
    if (pmf && pmf.length) {
      return pmf.map(row => ({ label: row.label, value: row.probability }))
    }
    return distributionBars(item.probability)
  }, [item.distribution, item.probability])
  const dist = item.distribution
  const isDistribution = item.headline_kind === 'distribution'
  const unit = unitSuffix(item.units)
  const panel = item.panel ?? null
  const topics = (item.topics ?? []).join(', ')

  return (
    <Box flexDirection="column">
      <Text bold color={t.color.primary} wrap="truncate-end">
        {item.title ?? item.id}
      </Text>
      <Text wrap="truncate-end">
        {item.domain ? <Text color={t.color.label}>{item.domain}</Text> : null}
        {item.impact ? (
          <Text color={t.color.muted}>
            {item.domain ? ' · ' : ''}impact <Text color={t.color.warn}>{item.impact}</Text>
          </Text>
        ) : null}
        {item.status ? (
          <Text color={item.status === 'active' ? t.color.ok : t.color.label}> · {item.status}</Text>
        ) : null}
        {topics ? <Text color={t.color.muted}> · {topics}</Text> : null}
      </Text>

      <Box marginTop={1}>
        <Text wrap="truncate-end">
          <Text bold color={t.color.primary}>
            {isDistribution ? '' : 'P '}
            {headlineLabel(item)}
          </Text>
          <Text color={t.color.muted}>{'  conf '}</Text>
          <Text color={t.color.label}>{finite(item.confidence) ? item.confidence.toFixed(2) : '—'}</Text>
          <Text color={t.color.muted}>{'  '}</Text>
          <Text bold color={deltaColor}>
            {deltaLabel(item)}
          </Text>
          <Text color={t.color.muted}>{'  as-of '}</Text>
          <Text color={t.color.label}>{`${shortDate(item.as_of)}${item.freshness ? ` (${item.freshness})` : ''}`}</Text>
        </Text>
      </Box>
      {isDistribution && dist && (finite(dist.median) || dist.ci90) ? (
        <Text wrap="truncate-end">
          {finite(dist.median) ? (
            <Text>
              <Text color={t.color.muted}>median </Text>
              <Text color={t.color.text}>
                {trimNum(dist.median)}
                {unit}
              </Text>
            </Text>
          ) : null}
          {dist.ci50 ? (
            <Text>
              <Text color={t.color.muted}>{'  ·  50% '}</Text>
              <Text color={t.color.text}>{`[${trimNum(dist.ci50[0]!)}, ${trimNum(dist.ci50[1]!)}]`}</Text>
            </Text>
          ) : null}
          {dist.ci90 ? (
            <Text>
              <Text color={t.color.muted}>{'  ·  90% '}</Text>
              <Text color={t.color.text}>{`[${trimNum(dist.ci90[0]!)}, ${trimNum(dist.ci90[1]!)}]`}</Text>
            </Text>
          ) : null}
        </Text>
      ) : null}
      <Text wrap="truncate-end">
        <Text color={t.color.muted}>close </Text>
        <Text color={t.color.label}>{shortDate(item.close_time)}</Text>
        <Text color={t.color.muted}>{'  ·  ev '}</Text>
        <Text color={t.color.label}>{item.evidence_count ?? 0}</Text>
        <Text color={t.color.muted}>{'  ·  '}</Text>
        <Text color={t.color.label}>{`${item.snapshot_count ?? 0} update${(item.snapshot_count ?? 0) === 1 ? '' : 's'}`}</Text>
        {item.method ? <Text color={t.color.muted}>{`  ·  ${item.method}`}</Text> : null}
      </Text>

      {item.resolution_criteria ? (
        <Box marginTop={1}>
          <Text color={t.color.text} wrap="wrap">
            {truncate(item.resolution_criteria, 220)}
          </Text>
        </Box>
      ) : null}

      {chart ? (
        <>
          <SectionTitle t={t}>{isDistribution ? `mean over time${unit ? ` (${unit})` : ''}` : 'probability over time'}</SectionTitle>
          {chart.rows.map((row, i) => (
            <Text color={t.color.accent} key={i}>
              {row}
            </Text>
          ))}
          <Text color={t.color.label} wrap="truncate-end">
            {`  ${shortDate(item.history?.[0]?.as_of)} → ${shortDate(item.as_of)}  ${
              isDistribution ? '● mean  ░ 90% interval' : panel ? '● forecast  ░ panel spread / confidence band' : '● forecast  ░ confidence band'
            }`}
          </Text>
        </>
      ) : null}

      {/* Title + quick stats + chart lead; the analyst quick read slots in here,
          right after the chart, ahead of the deeper breakdown below. */}
      {afterChart}

      {bars ? (
        <>
          <SectionTitle t={t}>{isDistribution ? 'outcome buckets (PMF)' : 'outcome distribution'}</SectionTitle>
          {histogram(bars, {
            // Adapt label + bar widths to the pane so a narrow detail column
            // never forces the bars off-screen.
            labelWidth: Math.max(8, Math.min(16, width - 14)),
            width: Math.max(6, Math.min(width - Math.max(8, Math.min(16, width - 14)) - 8, 30))
          }).map((row, i) => (
            <Text color={t.color.accent} key={i}>
              {row}
            </Text>
          ))}
        </>
      ) : null}

      {panel ? <PanelSection panel={panel} t={t} width={width} /> : null}

      {(item.reasons_up?.length || item.reasons_down?.length || item.change_my_mind?.length) ? (
        <>
          <SectionTitle t={t}>reasoning</SectionTitle>
          {(item.reasons_up ?? []).map((reason, i) => (
            <Text color={t.color.text} key={`up${i}`} wrap="truncate-end">
              <Text color={t.color.ok}>▲ </Text>
              {reason}
            </Text>
          ))}
          {(item.reasons_down ?? []).map((reason, i) => (
            <Text color={t.color.text} key={`dn${i}`} wrap="truncate-end">
              <Text color={t.color.error}>▼ </Text>
              {reason}
            </Text>
          ))}
          {(item.change_my_mind ?? []).map((reason, i) => (
            <Text color={t.color.text} key={`cmm${i}`} wrap="truncate-end">
              <Text color={t.color.warn}>⟳ </Text>
              {reason}
            </Text>
          ))}
        </>
      ) : null}

      {item.evidence?.length ? (
        <>
          <SectionTitle t={t}>recent evidence</SectionTitle>
          {item.evidence
            .slice()
            .reverse()
            .slice(0, 6)
            .map((evidence, i) => {
              const stanceColor =
                evidence.stance === 'increases'
                  ? t.color.ok
                  : evidence.stance === 'decreases'
                    ? t.color.error
                    : t.color.muted
              return (
                <Text key={evidence.id ?? i} wrap="truncate-end">
                  <Text color={t.color.label}>{shortDate(evidence.available_at)} </Text>
                  <Text bold color={stanceColor}>{(evidence.stance ?? 'context').slice(0, 3)} </Text>
                  <Text color={t.color.text}>{truncate(evidence.claim || evidence.summary || evidence.source || '—', 64)}</Text>
                </Text>
              )
            })}
        </>
      ) : null}

      <DecisionCard item={item} t={t} />

      {item.scores || item.resolution ? (
        <>
          <SectionTitle t={t}>scoring</SectionTitle>
          {item.scores ? (
            <KV
              k="calibration"
              t={t}
              v={`${item.scores.count ?? 0} scored · brier ${
                finite(item.scores.mean_brier) ? item.scores.mean_brier.toFixed(3) : '—'
              } · bucket ${item.scores.last_bucket ?? '—'}`}
            />
          ) : null}
          {item.resolution ? (
            <KV
              k="resolution"
              t={t}
              v={`${String(item.resolution.outcome ?? '—')} (${item.resolution.resolution_status ?? '—'})`}
            />
          ) : null}
        </>
      ) : null}
    </Box>
  )
}

function PanelSection({ panel, t, width }: { panel: ForecastWorkspacePanel; t: Theme; width: number }) {
  const whisker = boxWhisker(panel.spread ?? {}, { width: Math.max(12, Math.min(width - 18, 28)) })
  return (
    <>
      <SectionTitle t={t}>{`panel (${panel.estimates?.length ?? 0} perspectives)`}</SectionTitle>
      <Text wrap="truncate-end">
        <Text color={t.color.muted}>aggregate </Text>
        <Text bold color={t.color.primary}>
          {pct(panel.aggregate_probability)}
        </Text>
        <Text color={t.color.muted}>{`  ${panel.aggregation_method ?? 'pool'} · trim ${panel.trim ?? 0}`}</Text>
      </Text>
      {whisker ? (
        <Text wrap="truncate-end">
          <Text color={t.color.label}>{`${pct(panel.spread?.min)} `}</Text>
          <Text color={t.color.accent}>{whisker}</Text>
          <Text color={t.color.label}>{` ${pct(panel.spread?.max)}`}</Text>
        </Text>
      ) : null}
      {(panel.estimates ?? []).map((estimate, i) => (
        <Text key={estimate.perspective ?? i} wrap="truncate-end">
          <Text bold={!estimate.trimmed} color={estimate.trimmed ? t.color.muted : t.color.label}>
            {estimate.trimmed ? '× ' : '  '}
            {(estimate.perspective ?? '—').padEnd(10)}
          </Text>
          <Text color={t.color.text}>{pct(estimate.probability).padStart(5)}</Text>
          {estimate.crux ? <Text color={t.color.label}>{`  ${truncate(estimate.crux, 40)}`}</Text> : null}
        </Text>
      ))}
    </>
  )
}

// Renders the long-form packet sections (forecast history, assumptions, model
// runs, actions) under the visual summary. Read-only — the workspace has its own
// keymap, so the action rows are shown as a reference playbook, not links. Uses
// the hanging-indent two-column pattern (fixed key column + flexGrow value with
// minWidth={0}) so long rationales / URLs wrap instead of overflowing the pane.
export function ForecastPacketTail({ sections, t, width }: { sections: PanelSection[]; t: Theme; width: number }) {
  const keyWidth = Math.min(18, Math.max(8, Math.floor(width * 0.34)))
  return (
    <>
      {sections.map((section, si) => {
        const isActions = section.title === 'Actions'
        return (
          <Fragment key={section.title ?? si}>
            {section.title ? <SectionTitle t={t}>{section.title}</SectionTitle> : null}
            {(section.rows ?? []).map((row, ri) =>
              // Action commands are long; render the command on its own wrapping
              // line with the description indented beneath, like a playbook.
              isActions ? (
                <Box flexDirection="column" key={ri}>
                  <Box flexDirection="row">
                    <Box flexShrink={0} width={2}>
                      <Text color={t.color.muted}>{'• '}</Text>
                    </Box>
                    <Box flexGrow={1} flexShrink={1} minWidth={0}>
                      <Text color={t.color.accent} wrap="wrap">
                        {row[0]}
                      </Text>
                    </Box>
                  </Box>
                  {row[1] ? (
                    <Box flexDirection="row">
                      <Box flexShrink={0} width={2}>
                        <Text> </Text>
                      </Box>
                      <Box flexGrow={1} flexShrink={1} minWidth={0}>
                        <Text color={t.color.muted} wrap="wrap">
                          {row[1]}
                        </Text>
                      </Box>
                    </Box>
                  ) : null}
                </Box>
              ) : (
                <Box flexDirection="row" key={ri}>
                  <Box flexShrink={0} width={keyWidth}>
                    <Text color={t.color.label} wrap="truncate-end">
                      {row[0]}
                    </Text>
                  </Box>
                  <Box flexGrow={1} flexShrink={1} minWidth={0}>
                    <Text color={t.color.text} wrap="wrap">
                      {row[1] || ' '}
                    </Text>
                  </Box>
                </Box>
              )
            )}
            {(section.items ?? []).map((item, ii) => (
              <Box flexDirection="row" key={`it${ii}`}>
                <Box flexShrink={0} width={2}>
                  <Text color={t.color.muted}>{'· '}</Text>
                </Box>
                <Box flexGrow={1} flexShrink={1} minWidth={0}>
                  <Text color={t.color.text} wrap="wrap">
                    {item}
                  </Text>
                </Box>
              </Box>
            ))}
            {section.text ? (
              <Text color={t.color.muted} wrap="wrap">
                {section.text}
              </Text>
            ) : null}
          </Fragment>
        )
      })}
    </>
  )
}

// A thin horizontal rule to separate opinion / data / history (Bloomberg feel).
function Rule({ t, width }: { t: Theme; width: number }) {
  return (
    <Box marginTop={1}>
      <Text color={t.color.border}>{'─'.repeat(Math.max(8, Math.min(width, 80)))}</Text>
    </Box>
  )
}

// A wrapping paragraph that never overflows the bounded detail ScrollBox: the
// flexGrow + flexShrink + minWidth={0} value box lets long lines wrap as a
// hanging indent instead of pushing past the pane edge.
// A wrapping, hanging-indent paragraph. Uses paddingLeft on a plain column Box
// (NOT a flexGrow row) so Ink wraps the text at (boxWidth - 2) deterministically.
// The earlier flexGrow + minWidth={0} row resolved its width against the
// ScrollBox's measured content and overflowed the pane by a column or two,
// which both clipped the last characters and made the text reflow/jump as the
// measurement settled. paddingLeft is the same mechanism the resolution-criteria
// text uses, which wraps cleanly.
function WrapText({ bold = false, children, color, t }: { bold?: boolean; children: string; color?: string; t: Theme }) {
  return (
    <Box paddingLeft={2}>
      <Text bold={bold} color={color ?? t.color.text} wrap="wrap">
        {children}
      </Text>
    </Box>
  )
}

const ANALYST_ANGLES: { key: 'be_aware' | 'how_it_feels' | 'how_it_thinks' | 'looking_for'; label: string; warn?: boolean }[] = [
  { key: 'how_it_feels', label: 'how it feels' },
  { key: 'how_it_thinks', label: 'how it thinks' },
  { key: 'looking_for', label: 'watching for', warn: true },
  { key: 'be_aware', label: 'be aware', warn: true }
]

const STANCE_LABEL: Record<string, string> = {
  lean_no: 'lean no',
  lean_yes: 'lean yes',
  toss_up: 'toss-up'
}

// The prominent analyst write-up block (the desk "quick read", or the closing
// "retrospective" once resolved). Renders the four labeled angles when present,
// else falls back to the synthesized body split into paragraphs.
export function AnalystNote({
  note,
  showStance = true,
  t,
  variant
}: {
  note: ForecastAnalystNote
  showStance?: boolean
  t: Theme
  variant: 'quickread' | 'retrospective'
  width?: number
}) {
  const isRetro = variant === 'retrospective'
  const angles = ANALYST_ANGLES.map(angle => ({ ...angle, text: (note[angle.key] ?? '').trim() })).filter(
    angle => angle.text
  )
  const fallback =
    angles.length === 0
      ? (note.body ?? '')
          .split(/\n\n+/)
          .map(paragraph => paragraph.trim())
          .filter(Boolean)
      : []
  const verdictColor =
    note.verdict === 'right'
      ? t.color.ok
      : note.verdict === 'close'
        ? t.color.warn
        : note.verdict
          ? t.color.error
          : t.color.muted

  return (
    <Box flexDirection="column" marginTop={1}>
      <SectionTitle t={t}>{isRetro ? 'RETROSPECTIVE' : 'QUICK READ'}</SectionTitle>
      <Text wrap="truncate-end">
        <Text color={t.color.muted}>{`as of ${shortDate(note.as_of)}`}</Text>
        {showStance && note.stance ? (
          <Text color={t.color.label}>{`  ·  ${STANCE_LABEL[note.stance] ?? note.stance}`}</Text>
        ) : null}
        {note.verdict ? (
          <Text bold color={verdictColor}>
            {`  ·  ${note.verdict}`}
          </Text>
        ) : null}
        {note.generator === 'template' ? <Text color={t.color.muted}>{'  ·  auto'}</Text> : null}
      </Text>
      {note.headline ? (
        <Box marginTop={1}>
          <WrapText bold color={t.color.text} t={t}>
            {note.headline}
          </WrapText>
        </Box>
      ) : null}
      {angles.map(angle => (
        <Box flexDirection="column" key={angle.key} marginTop={1}>
          <Text bold color={angle.warn ? t.color.warn : t.color.label}>
            {angle.label}
          </Text>
          <WrapText t={t}>{angle.text}</WrapText>
        </Box>
      ))}
      {fallback.map((paragraph, index) => (
        <Box key={index} marginTop={1}>
          <WrapText t={t}>{paragraph}</WrapText>
        </Box>
      ))}
    </Box>
  )
}

// The reviewable time series of prior write-ups, newest-first, as compact
// dateline + headline rows under the main quick read.
function AnalystLog({ notes, t }: { notes: ForecastAnalystNote[]; t: Theme }) {
  if (!notes.length) {
    return null
  }
  return (
    <Box flexDirection="column">
      <SectionTitle t={t}>analyst log</SectionTitle>
      {notes.map((note, index) => (
        <Box flexDirection="row" key={`${note.created_at ?? note.as_of ?? ''}:${index}`}>
          <Box flexShrink={0} width={2}>
            <Text color={t.color.muted}>{note.kind === 'retrospective' ? '◆ ' : '· '}</Text>
          </Box>
          <Box flexGrow={1} flexShrink={1} minWidth={0}>
            <Text wrap="truncate-end">
              <Text color={t.color.muted}>{`${shortDate(note.as_of)}  `}</Text>
              <Text color={t.color.text}>{note.headline || (note.body ?? '').slice(0, 90) || '(note)'}</Text>
            </Text>
          </Box>
        </Box>
      ))}
    </Box>
  )
}

function DecisionCard({ item, t }: { item: ForecastWorkspaceItem; t: Theme }) {
  const issues = item.decision_readiness_issues ?? []
  const hasCard = item.decision_owner || item.action_threshold || (item.update_triggers?.length ?? 0) > 0
  if (!hasCard && !issues.length) {
    return null
  }
  return (
    <>
      <SectionTitle t={t}>decision card</SectionTitle>
      <KV k="owner" t={t} v={item.decision_owner || '—'} />
      <KV k="deadline" t={t} v={shortDate(item.decision_deadline)} />
      <KV k="action" t={t} v={item.action_threshold || '—'} />
      {(item.update_triggers ?? []).slice(0, 4).map((trigger, i) => (
        <Text color={t.color.text} key={i} wrap="truncate-end">
          <Text color={t.color.label}>{(i === 0 ? 'triggers' : '').padEnd(13)}</Text>
          {trigger.mechanism ?? '—'}
          {trigger.threshold ? <Text color={t.color.label}>{` [${trigger.threshold}]`}</Text> : null}
        </Text>
      ))}
      {issues.length ? (
        <Text color={t.color.warn} wrap="truncate-end">
          {'readiness'.padEnd(13)}
          {issues.join(' · ')}
        </Text>
      ) : null}
    </>
  )
}
