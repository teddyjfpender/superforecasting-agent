/**
 * Pure render/format helpers for the Superforecaster web terminal.
 *
 * This is a STANDALONE COPY of the pure logic ported from the ui-tui package:
 *   - ui-tui/src/lib/forecastCharts.ts  (chart + format primitives)
 *   - ui-tui/src/components/forecastsWorkspace.tsx  (forecast-shaped formatters)
 *
 * It deliberately does NOT import from the ui-tui package — the web terminal
 * owns its own copy. Everything here is plain TS (no React, no Ink, no I/O) and
 * returns plain strings / string[] / plain objects, so it is trivially testable
 * and can be dropped straight into web-terminal render code.
 *
 * Design notes (carried over from the source):
 *  - Probabilities are level-scaled (fixed 0..1), NOT max-normalized: a 52%
 *    forecast reads as mid-height, not full just because it is the tallest
 *    point in a flat series.
 *  - LOAD-BEARING CORRECTNESS RULE: headlineCompact / deltaLabel / headlineLabel
 *    branch on `item.headline_kind` FIRST so a distribution mean (e.g. CPI
 *    μ=3.1) renders "μ 3.1", never "310%". Do not reorder those branches.
 */

import type {
  ForecastWorkspaceItem,
  ForecastWorkspacePanel
} from './forecastTypes'

// ─────────────────────────────────────────────────────────────────────────────
// Chart + format primitives (ported verbatim from forecastCharts.ts)
// ─────────────────────────────────────────────────────────────────────────────

const SPARK_RAMP = ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'] as const

export const clamp01 = (value: number): number => Math.max(0, Math.min(1, value))

export const finite = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value)

// ── Formatting ──────────────────────────────────────────────────────────────

/** `0.523` → `"52%"`. `null`/non-finite → `"—"`. */
export const pct = (value: number | null | undefined, digits = 0): string =>
  finite(value) ? `${(value * 100).toFixed(digits)}%` : '—'

/** Direction glyph for a probability delta. */
export const deltaGlyph = (delta: number | null | undefined): string => {
  if (!finite(delta) || Math.abs(delta) < 0.005) {
    return '·'
  }
  return delta > 0 ? '▲' : '▼'
}

/** `0.031` → `"▲ +3pt"`, `-0.012` → `"▼ -1pt"`, `~0` → `"· flat"`. */
export const pctDelta = (delta: number | null | undefined): string => {
  if (!finite(delta) || Math.abs(delta) < 0.005) {
    return '· flat'
  }
  const points = Math.round(delta * 100)
  const sign = points > 0 ? '+' : ''
  return `${deltaGlyph(delta)} ${sign}${points}pt`
}

const trimZeros = (s: string): string => (s.includes('.') ? s.replace(/\.?0+$/, '') : s) || '0'

/**
 * Compact number with a magnitude suffix and ~3 significant figures:
 * `73000` → `"73k"`, `73500` → `"73.5k"`, `1_234_567` → `"1.23M"`,
 * `4.24` → `"4.24"`, `0.1` → `"0.1"`. Keeps axis labels and list values a
 * stable, short width regardless of magnitude (k / M / B / T). Nullish → `"—"`.
 */
const MAGNITUDES: ReadonlyArray<readonly [number, string]> = [
  [1e12, 'T'],
  [1e9, 'B'],
  [1e6, 'M'],
  [1e3, 'k']
]

const pickScale = (maxAbs: number): readonly [number, string] => {
  for (const [scale, suffix] of MAGNITUDES) {
    if (maxAbs >= scale) {
      return [scale, suffix]
    }
  }
  return [1, '']
}

// Minimal decimals needed to represent a value (capped), e.g. 100.08 → 2, 100 → 0.
const naturalDecimals = (x: number): number => {
  const s = Math.abs(x).toFixed(4).replace(/0+$/, '').replace(/\.$/, '')
  const dot = s.indexOf('.')
  return dot === -1 ? 0 : s.length - dot - 1
}

export const compactNumber = (value: number | null | undefined): string => {
  if (!finite(value)) {
    return '—'
  }
  const sign = value < 0 ? '-' : ''
  const abs = Math.abs(value)
  for (const [scale, suffix] of MAGNITUDES) {
    if (abs >= scale) {
      const scaled = abs / scale
      const decimals = scaled >= 100 ? 0 : scaled >= 10 ? 1 : 2
      return `${sign}${trimZeros(scaled.toFixed(decimals))}${suffix}`
    }
  }
  // Below 1000 there is no suffix; match the prior 2-decimal-then-trim display
  // (e.g. 4.24 -> "4.24", 0.098 -> "0.1") so existing values are unchanged.
  return `${sign}${trimZeros(abs.toFixed(2))}`
}

/**
 * Format a set of axis tick values with a SHARED magnitude suffix AND a SHARED
 * decimal count, so the labels always line up at the same precision: a chart
 * spanning 99.92..100.08 reads "100.08 / 100.00 / 99.92", not "100.08 / 100 /
 * 99.92". Non-finite entries render `"—"`.
 */
export const axisLabels = (values: ReadonlyArray<number | null | undefined>): string[] => {
  const present = values.filter(finite)
  if (!present.length) {
    return values.map(() => '—')
  }
  const [scale, suffix] = pickScale(Math.max(...present.map(value => Math.abs(value)), 0))
  const decimals = Math.min(4, Math.max(0, ...present.map(value => naturalDecimals(value / scale))))
  return values.map(value => (finite(value) ? `${(value / scale).toFixed(decimals)}${suffix}` : '—'))
}

/** ISO timestamp → `YYYY-MM-DD`; nullish → `"—"`. */
export const shortDate = (value: string | null | undefined): string =>
  value ? value.slice(0, 10) : '—'

// ── Level sparkline (fixed 0..1 scale) ───────────────────────────────────────

/**
 * One-line sparkline of probabilities on a fixed [yMin, yMax] scale. `null`
 * entries render as a gap so a sparse history does not lie about activity.
 */
export const levelSparkline = (
  values: ReadonlyArray<number | null>,
  { yMin = 0, yMax = 1 }: { yMin?: number; yMax?: number } = {}
): string => {
  const span = yMax - yMin
  if (!values.length || span <= 0) {
    return ''
  }
  return values
    .map(value => {
      if (!finite(value)) {
        return ' '
      }
      const frac = clamp01((value - yMin) / span)
      const idx = Math.round(frac * (SPARK_RAMP.length - 1))
      return SPARK_RAMP[idx]
    })
    .join('')
}

// ── Band chart (probability time-series with CI band) ────────────────────────

export interface BandPoint {
  y: number | null
  lo?: number | null
  hi?: number | null
}

export interface BandChart {
  rows: string[]
  axis: { top: string; bottom: string }
}

const MARKER = '●'
const BAND = '░'
const FLAT = '─'

/**
 * Render a discrete probability time-series with an optional confidence band.
 *
 * Each point becomes a column: a faint vertical band from `lo` to `hi` (when
 * present) with a solid marker at `y`. The y-axis is fixed to [yMin, yMax]
 * (default 0..1) so heights are comparable across forecasts. Returns the plot
 * rows (top→bottom, each prefixed with a y-gutter) plus axis labels.
 */
export const bandChart = (
  points: ReadonlyArray<BandPoint>,
  {
    width = 48,
    height = 7,
    yMin = 0,
    yMax = 1
  }: { width?: number; height?: number; yMin?: number; yMax?: number } = {}
): BandChart => {
  const h = Math.max(3, height)
  // Axis labels are abbreviated (k/M/B/T) and share one decimal count + suffix so
  // all three read at the same precision (100.08 / 100.00 / 99.92), then are
  // right-padded to a uniform width so the plot column never shifts.
  const [topLabel, midLabel, bottomLabel] = axisLabels([yMax, (yMax + yMin) / 2, yMin]) as [
    string,
    string,
    string
  ]
  const labelW = Math.max(4, topLabel.length, midLabel.length, bottomLabel.length)
  const gutterW = labelW + 2 // label + " │"
  const plotW = Math.max(1, width - gutterW)
  const span = yMax - yMin || 1
  const active = points.filter(point => finite(point.y))

  const grid: string[][] = Array.from({ length: h }, () => Array.from({ length: plotW }, () => ' '))

  const rowFor = (value: number): number => {
    const frac = clamp01((value - yMin) / span)
    return Math.round((1 - frac) * (h - 1))
  }

  const colFor = (index: number, count: number): number =>
    count <= 1 ? 0 : Math.round((index * (plotW - 1)) / (count - 1))

  active.forEach((point, index) => {
    const col = colFor(index, active.length)
    const lo = finite(point.lo) ? point.lo : null
    const hi = finite(point.hi) ? point.hi : null
    if (lo !== null && hi !== null) {
      const rTop = rowFor(Math.max(lo, hi))
      const rBot = rowFor(Math.min(lo, hi))
      for (let r = rTop; r <= rBot; r += 1) {
        grid[r]![col] = BAND
      }
    }
    grid[rowFor(point.y as number)]![col] = MARKER
  })

  const labelFor = (row: number): string => {
    if (row === 0) {
      return topLabel.padStart(labelW)
    }
    if (row === h - 1) {
      return bottomLabel.padStart(labelW)
    }
    if (row === Math.floor((h - 1) / 2)) {
      return midLabel.padStart(labelW)
    }
    return ' '.repeat(labelW)
  }

  const rows = grid.map((cells, row) => `${labelFor(row)} │${cells.join('')}`)
  return {
    rows,
    axis: { top: topLabel, bottom: bottomLabel }
  }
}

// ── Histogram (categorical / distribution outcomes) ──────────────────────────

export interface HistogramBar {
  label: string
  value: number
}

/**
 * Horizontal bar chart. Bars are scaled to the largest value so the mode fills
 * the track; the raw value is printed at the end of each row. Labels are
 * truncated/padded to `labelWidth`.
 */
export const histogram = (
  bars: ReadonlyArray<HistogramBar>,
  { width = 22, labelWidth = 16 }: { width?: number; labelWidth?: number } = {}
): string[] => {
  const usable = bars.filter(bar => finite(bar.value))
  if (!usable.length) {
    return []
  }
  const max = Math.max(...usable.map(bar => bar.value), 0)
  const track = Math.max(1, width)
  return usable.map(bar => {
    const label =
      bar.label.length > labelWidth ? `${bar.label.slice(0, labelWidth - 1)}…` : bar.label.padEnd(labelWidth)
    const frac = max > 0 ? clamp01(bar.value / max) : 0
    const fill = Math.round(frac * track)
    // Probabilities and other fractional values get 2 decimals; whole counts
    // stay integer (so "1200" doesn't become "1200.00").
    const valueText = Number.isInteger(bar.value) ? String(bar.value) : bar.value.toFixed(2)
    return `${label} ${'█'.repeat(fill)}${'░'.repeat(track - fill)} ${valueText}`
  })
}

// ── Box-whisker (panel spread) ───────────────────────────────────────────────

export interface SpreadSummary {
  min?: number | null
  p25?: number | null
  median?: number | null
  p75?: number | null
  max?: number | null
}

/**
 * One-line whisker plot of a panel spread on a [yMin, yMax] track:
 * `├──▒▒┃▒▒──┤` — whiskers (─) from min→max, IQR box (▒) from p25→p75, median (┃).
 * Returns `''` when the spread has no usable min/max.
 */
export const boxWhisker = (
  spread: SpreadSummary,
  { width = 24, yMin = 0, yMax = 1 }: { width?: number; yMin?: number; yMax?: number } = {}
): string => {
  const min = finite(spread.min) ? spread.min : null
  const max = finite(spread.max) ? spread.max : null
  if (min === null || max === null) {
    return ''
  }
  const track = Math.max(3, width)
  const span = yMax - yMin || 1
  const col = (value: number): number => Math.round(clamp01((value - yMin) / span) * (track - 1))

  const cMin = col(min)
  const cMax = col(max)
  const p25 = finite(spread.p25) ? col(spread.p25) : cMin
  const p75 = finite(spread.p75) ? col(spread.p75) : cMax
  const med = finite(spread.median) ? col(spread.median) : Math.round((cMin + cMax) / 2)

  const cells = Array.from({ length: track }, () => ' ')
  for (let i = cMin; i <= cMax; i += 1) {
    cells[i] = FLAT
  }
  for (let i = Math.min(p25, p75); i <= Math.max(p25, p75); i += 1) {
    cells[i] = '▒'
  }
  cells[cMin] = '├'
  cells[cMax] = '┤'
  cells[med] = '┃'
  return cells.join('')
}

// ─────────────────────────────────────────────────────────────────────────────
// Forecast-shaped formatters (ported from forecastsWorkspace.tsx)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Distribution values (μ, σ, median, CI bounds, Δμ) are abbreviated with
 * k/M/B/T so a Bitcoin mean reads "73k", not "73000", and the master-list and
 * detail values stay short. Percentages and small values pass through unchanged.
 */
export const trimNum = (value: number): string => compactNumber(value)

export const unitSuffix = (units: null | string | undefined): string => {
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
export const headlineCompact = (item: ForecastWorkspaceItem): string => {
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
export const deltaLabel = (item: ForecastWorkspaceItem): string => {
  const d = item.delta
  if (!finite(d) || Math.abs(d) < (item.headline_kind === 'distribution' ? 1e-6 : 0.005)) {
    return '· flat'
  }
  if (item.headline_kind === 'distribution') {
    return `${deltaGlyph(d)} Δμ ${d > 0 ? '+' : ''}${trimNum(d)}${unitSuffix(item.units)}`
  }
  return pctDelta(d)
}

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
export const distributionBars = (
  probability: ForecastWorkspaceItem['probability']
): HistogramBar[] | null => {
  if (!probability || typeof probability !== 'object' || Array.isArray(probability)) {
    return null
  }
  const entries = Object.entries(probability).filter(([, value]) => finite(value)) as [string, number][]
  if (entries.length < 2) {
    return null
  }
  const distributionalKeys = new Set([
    'mean',
    'mu',
    'sd',
    'sigma',
    'std',
    'stdev',
    'variance',
    'expected',
    'value'
  ])
  if (entries.every(([key]) => distributionalKeys.has(key.toLowerCase()))) {
    return null
  }
  return entries.map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value)
}

// Confidence band half-width factor (a low-confidence forecast gets a wider band).
const CONF_BAND_K = 0.18

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

// ─────────────────────────────────────────────────────────────────────────────
// Render const tables (ported verbatim from forecastsWorkspace.tsx)
// ─────────────────────────────────────────────────────────────────────────────

export const ANALYST_ANGLES: {
  key: 'be_aware' | 'how_it_feels' | 'how_it_thinks' | 'looking_for'
  label: string
  warn?: boolean
}[] = [
  { key: 'how_it_feels', label: 'how it feels' },
  { key: 'how_it_thinks', label: 'how it thinks' },
  { key: 'looking_for', label: 'watching for', warn: true },
  { key: 'be_aware', label: 'be aware', warn: true }
]

export const STANCE_LABEL: Record<string, string> = {
  lean_no: 'lean no',
  lean_yes: 'lean yes',
  toss_up: 'toss-up'
}

// Cross-pollination: the world-views of related / parent / child forecasts.
export const RELATIONSHIP_TAG: Record<string, { glyph: string; label: string }> = {
  child: { glyph: '▾', label: 'child' },
  correlated_sibling: { glyph: '~', label: 'sibling' },
  parent: { glyph: '▴', label: 'parent' }
}

// Re-export the data shapes so consumers can `import { ForecastWorkspaceItem } from './forecastFormat'`.
export type {
  ForecastAnalystNote,
  ForecastRelated,
  ForecastRelatedView,
  ForecastSharedSource,
  ForecastWorkspaceDistribution,
  ForecastWorkspaceEvidence,
  ForecastWorkspaceHistoryPoint,
  ForecastWorkspaceItem,
  ForecastWorkspacePanel,
  ForecastWorkspacePanelEstimate,
  ForecastWorkspaceResolution,
  ForecastWorkspaceResponse,
  ForecastWorkspaceScores,
  ForecastWorkspaceTrigger
} from './forecastTypes'
