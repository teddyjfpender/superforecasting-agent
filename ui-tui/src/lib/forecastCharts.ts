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
  // 2dp — matches the desk's window columns; 'flat' only when the rendered
  // value would read 0.00pt.
  if (!finite(delta) || Math.abs(delta) < 0.00005) {
    return '· flat'
  }
  const points = (delta * 100).toFixed(2)
  const sign = delta > 0 ? '+' : ''
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

// ── Windowed change (1D / 1W / 1MO list columns) ─────────────────────────────

/**
 * Minimal shape windowDelta needs from a history point.
 *
 * `headline_regime` (thesis series only) marks which series the headline point
 * belongs to — "event" once a joint-threshold event is configured, else
 * "health". A delta must never straddle that switch, so the window comparison is
 * restricted to the current regime. Member/forecast rows carry no regime
 * (`undefined`), which disables the gate entirely — their behaviour is unchanged.
 */
export interface WindowPoint {
  as_of?: string
  headline_probability?: number | null
  headline_regime?: string | null
}

const DAY_MS = 86_400_000

/**
 * The regime-aware result of a window comparison.
 *
 * `delta` is the change in the headline over the trailing `days` window (null
 * when there is no honest same-regime anchor). `newSeries` is true ONLY when the
 * delta is null *because* the only in-window baseline belongs to a PRIOR regime
 * (the headline series switched — e.g. health → event) — so the desk renders a
 * subtle "new series" hint instead of a bare "—", and never a cross-regime lie.
 */
export interface WindowDeltaDetail {
  delta: number | null
  newSeries: boolean
}

/**
 * Regime-aware change in the headline value over the trailing `days` window.
 *
 * Compares against `as_of` (the economic effective date the snapshot speaks to),
 * NOT `created_at`, so a back-dated re-forecast lands in the right window. The
 * "current" value is the newest finite headline; the baseline is the newest
 * finite point at or before `nowMs − days·86_400_000`. When the current point
 * carries a `headline_regime`, only baselines of the SAME regime are eligible —
 * a cross-regime point is skipped (and, if it was the only in-window candidate,
 * flagged as `newSeries`). Points without a regime never gate (member rows).
 */
export const windowDeltaDetail = (
  history: ReadonlyArray<WindowPoint> | null | undefined,
  nowMs: number,
  days: number
): WindowDeltaDetail => {
  const points = history ?? []
  if (points.length < 2) {
    return { delta: null, newSeries: false }
  }

  // Current = the newest point carrying a finite headline (+ its regime).
  let current: number | null = null
  let currentRegime: string | null | undefined
  for (let i = points.length - 1; i >= 0; i -= 1) {
    const y = points[i]!.headline_probability
    if (finite(y)) {
      current = y
      currentRegime = points[i]!.headline_regime
      break
    }
  }
  if (current === null) {
    return { delta: null, newSeries: false }
  }

  const cutoff = nowMs - days * DAY_MS

  // The LAST (newest) point at or before the cutoff — i.e. the value as it stood
  // a window ago. Points are oldest→newest, so scan backward and take the first
  // in-window, finite, SAME-regime point. A cross-regime in-window point is
  // skipped but remembered so the null is reported as a "new series" boundary.
  let sawCrossRegime = false
  for (let i = points.length - 1; i >= 0; i -= 1) {
    const point = points[i]!
    const ms = point.as_of ? Date.parse(point.as_of) : Number.NaN
    if (Number.isFinite(ms) && ms <= cutoff && finite(point.headline_probability)) {
      if (
        currentRegime != null &&
        point.headline_regime != null &&
        point.headline_regime !== currentRegime
      ) {
        sawCrossRegime = true
        continue
      }
      return { delta: current - point.headline_probability, newSeries: false }
    }
  }

  return { delta: null, newSeries: sawCrossRegime }
}

/**
 * Change in the headline value over the trailing `days` window (regime-aware).
 *
 * Returns `null` when there is no honest same-regime in-window anchor — callers
 * render that as "—", never a 0. This is a POINT delta; for distribution
 * forecasts the headline is μ in outcome units, so the caller interprets the
 * number as Δμ, never a fake percent. Thin wrapper over {@link windowDeltaDetail}.
 */
export const windowDelta = (
  history: ReadonlyArray<WindowPoint> | null | undefined,
  nowMs: number,
  days: number
): number | null => windowDeltaDetail(history, nowMs, days).delta

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
  /** columns consumed by the y-gutter (label + " │"); the plot cells begin here */
  gutterW: number
  /** width of the plot region (cells to the right of the gutter) */
  plotW: number
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
  const [topLabel, midLabel, bottomLabel] = axisLabels([yMax, (yMax + yMin) / 2, yMin])
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
    axis: { top: topLabel, bottom: bottomLabel },
    gutterW,
    plotW
  }
}

// ── Time (x) axis ────────────────────────────────────────────────────────────

export interface TimeAxis {
  /** the tick/base rule aligned under the plot (with the y-axis corner) */
  ticks: string
  /** the date labels aligned under their ticks (deduped) */
  labels: string
}

const isoDay = (ms: number): string => new Date(ms).toISOString().slice(0, 10)

/**
 * Build a real x-axis for the band chart: a base rule with tick marks under the
 * plot and 3–5 date labels spread across the ACTUAL time range (interpolated
 * between the first and last snapshot). Labels are deduped — a short-lived
 * series that would print the same day twice prints it once; a single-snapshot
 * (degenerate) range labels that one date centered. Both returned strings are
 * gutter-prefixed so they drop straight under `bandChart().rows`.
 *
 * Returns `null` when no snapshot carries a parseable date.
 */
export const timeAxis = (
  isoDates: ReadonlyArray<string | null | undefined>,
  { plotW, gutterW, maxLabels = 5 }: { plotW: number; gutterW: number; maxLabels?: number }
): null | TimeAxis => {
  const pw = Math.max(1, Math.floor(plotW))
  const gw = Math.max(0, Math.floor(gutterW))
  const times = isoDates
    .map(value => (value ? Date.parse(value) : Number.NaN))
    .filter((ms): ms is number => Number.isFinite(ms))

  if (!times.length) {
    return null
  }

  const minMs = Math.min(...times)
  const maxMs = Math.max(...times)

  const tickCells = Array.from({ length: pw }, () => '─')
  const labelCells = Array.from({ length: pw }, () => ' ')
  const occupied = Array.from({ length: pw }, () => false)
  const placed = new Set<string>()

  // Place a date label near `col`, deduped and non-overlapping (a 1-cell gap is
  // reserved on each side). Returns whether the label landed.
  const tryPlace = (col: number, label: string, align: 'center' | 'left' | 'right'): boolean => {
    if (placed.has(label)) {
      return false // dedup — never print the same date twice
    }
    const len = label.length
    let start = align === 'left' ? col : align === 'right' ? col - len + 1 : col - Math.floor(len / 2)
    start = Math.max(0, Math.min(pw - len, start))
    if (start < 0) {
      return false // label wider than the whole plot
    }
    for (let i = Math.max(0, start - 1); i < Math.min(pw, start + len + 1); i += 1) {
      if (occupied[i]) {
        return false
      }
    }
    for (let i = 0; i < len; i += 1) {
      labelCells[start + i] = label[i]!
      occupied[start + i] = true
    }
    tickCells[Math.max(0, Math.min(pw - 1, col))] = '┬'
    placed.add(label)
    return true
  }

  if (maxMs === minMs) {
    // Degenerate: a single snapshot (or all on one day) — one centered label.
    tryPlace(Math.floor((pw - 1) / 2), isoDay(minMs), 'center')
  } else {
    const total = Math.max(3, Math.min(maxLabels, 5))
    // Endpoints first so the true range is always anchored, then fill the middle
    // wherever it fits without colliding.
    tryPlace(0, isoDay(minMs), 'left')
    tryPlace(pw - 1, isoDay(maxMs), 'right')
    for (let i = 1; i < total - 1; i += 1) {
      const frac = i / (total - 1)
      tryPlace(Math.round(frac * (pw - 1)), isoDay(minMs + frac * (maxMs - minMs)), 'center')
    }
  }

  const corner = gw > 0 ? `${' '.repeat(gw - 1)}└` : ''
  return {
    ticks: `${corner}${tickCells.join('')}`,
    labels: `${' '.repeat(gw)}${labelCells.join('')}`
  }
}

// ── Word wrap (paragraph → capped lines) ─────────────────────────────────────

/**
 * Word-wrap `text` to `width`, capped at `maxLines`. A single word longer than
 * the width is hard-broken. When the text overflows the cap the final kept line
 * is tail-truncated with a '…' so it stays within `width` — the ONE place the
 * modal truncates prose (a title that will not fit three lines), never mid-value.
 */
export const wrapLines = (text: string, width: number, maxLines = 3): string[] => {
  const w = Math.max(1, Math.floor(width))
  const words = String(text ?? '')
    .split(/\s+/)
    .filter(Boolean)
  if (!words.length) {
    return []
  }

  const lines: string[] = []
  let current = ''

  for (const word of words) {
    if (word.length > w) {
      if (current) {
        lines.push(current)
        current = ''
      }
      let rest = word
      while (rest.length > w) {
        lines.push(rest.slice(0, w))
        rest = rest.slice(w)
      }
      current = rest
      continue
    }
    const next = current ? `${current} ${word}` : word
    if (next.length > w) {
      lines.push(current)
      current = word
    } else {
      current = next
    }
  }
  if (current) {
    lines.push(current)
  }

  if (lines.length <= maxLines) {
    return lines
  }

  const kept = lines.slice(0, maxLines)
  let tail = kept[maxLines - 1]!
  if (tail.length >= w) {
    tail = tail.slice(0, Math.max(0, w - 1))
  }
  kept[maxLines - 1] = `${tail}…`
  return kept
}

// ── Histogram (categorical / distribution outcomes) ──────────────────────────

export interface HistogramBar {
  label: string
  value: number
  // Optional 90% interval (e.g. per-candidate vote-share p05/p95). When present the
  // row appends ` [lo–hi]` so uncertainty is visible next to the point estimate.
  interval?: { hi: number; lo: number } | null
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
    const iv = bar.interval
    const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1))
    const intervalText = iv && finite(iv.lo) && finite(iv.hi) ? ` [${fmt(iv.lo)}–${fmt(iv.hi)}]` : ''
    return `${label} ${'█'.repeat(fill)}${'░'.repeat(track - fill)} ${valueText}${intervalText}`
  })
}

// ── Dot track (one value vs a reference on a shared scale) ──────────────────

/**
 * One-line position track: `····●····┊······` — a dotted [yMin, yMax] rail
 * with the value (●) and an optional reference mark (┊, e.g. the panel
 * aggregate). When the two land on the same cell the value wins, so a
 * perspective sitting exactly on the aggregate reads as ● on the rail.
 * Returns `''` when the value is not finite.
 */
export const dotTrack = (
  value: number | null | undefined,
  reference: number | null | undefined,
  { width = 20, yMin = 0, yMax = 1 }: { width?: number; yMin?: number; yMax?: number } = {}
): string => {
  if (!finite(value)) {
    return ''
  }
  const track = Math.max(3, width)
  const span = yMax - yMin || 1
  const col = (v: number): number => Math.round(clamp01((v - yMin) / span) * (track - 1))
  const cells = Array.from({ length: track }, () => '·')
  if (finite(reference)) {
    cells[col(reference)] = '┊'
  }
  cells[col(value)] = '●'
  return cells.join('')
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
