/**
 * Pure unicode chart + format primitives for the forecasts workspace.
 *
 * Everything here returns plain strings / string[] so callers can drop the
 * output straight into <Text>. No Ink, no React, no I/O — trivially testable.
 *
 * Design notes:
 *  - Probabilities are level-scaled (fixed 0..1), NOT max-normalized like the
 *    subagent sparkline: a 52% forecast should read as mid-height, not full
 *    just because it is the tallest point in a flat series.
 *  - The band chart treats each snapshot as a discrete re-forecast event
 *    (markers), with an optional confidence/spread band drawn behind it — a
 *    fake continuous line would imply data we do not have between updates.
 */

const SPARK_RAMP = ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'] as const

export const clamp01 = (value: number): number => Math.max(0, Math.min(1, value))

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)

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
  const gutterW = 6 // "0.62 │"
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
      return yMax.toFixed(2).padStart(4)
    }
    if (row === h - 1) {
      return yMin.toFixed(2).padStart(4)
    }
    if (row === Math.floor((h - 1) / 2)) {
      return ((yMax + yMin) / 2).toFixed(2).padStart(4)
    }
    return '    '
  }

  const rows = grid.map((cells, row) => `${labelFor(row)} │${cells.join('')}`)
  return {
    rows,
    axis: { top: yMax.toFixed(2), bottom: yMin.toFixed(2) }
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
    const label = bar.label.length > labelWidth ? `${bar.label.slice(0, labelWidth - 1)}…` : bar.label.padEnd(labelWidth)
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
