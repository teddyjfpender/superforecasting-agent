// Terminal chart renderers new to Market Models: a scatter-plot-with-fit-line
// (for `regression`/`scatter` blocks) and an ASCII table. Pure (no Ink) so
// they're unit-tested like forecastCharts. All glyphs are single-cell (the
// emoji-width lesson from infoModal applies). Other block types reuse the
// existing primitives in forecastCharts.ts / sparkline.ts.

import { axisLabels, compactNumber } from './forecastCharts.js'

export interface XY {
  x: number
  y: number
}

export interface ScatterPlot {
  axis: { bottom: string }
  rows: string[]
}

const POINT = '●'
const OVERLAP = '◆'
const LINE = '·'

const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n)

/**
 * Scatter plot with an optional regression fit line.
 *
 * Builds an `height × plotW` grid over the combined x/y domain of the points and
 * the fit line. The fit line is drawn first with `·`; data points overwrite with
 * `●`; a second point sharing a cell becomes `◆` (a density hint). A y-gutter of
 * axis labels mirrors `bandChart`. R²/coefficients are printed by the caller as
 * adjacent text, not inside the grid.
 */
export const scatterPlot = (
  points: ReadonlyArray<XY>,
  fitLine?: ReadonlyArray<XY>,
  { width = 56, height = 12 }: { height?: number; width?: number } = {}
): ScatterPlot => {
  const pts = (points ?? []).filter(p => finite(p?.x) && finite(p?.y))
  const line = (fitLine ?? []).filter(p => finite(p?.x) && finite(p?.y))

  if (pts.length === 0 && line.length === 0) {
    return { axis: { bottom: '' }, rows: [] }
  }

  const xs = [...pts, ...line].map(p => p.x)
  const ys = [...pts, ...line].map(p => p.y)
  const xMin = Math.min(...xs)
  const xMax = Math.max(...xs)
  const yMin = Math.min(...ys)
  const yMax = Math.max(...ys)
  const xSpan = xMax - xMin || 1
  const ySpan = yMax - yMin || 1

  const h = Math.max(3, height)
  const [topLabel, midLabel, bottomLabel] = axisLabels([yMax, (yMax + yMin) / 2, yMin])
  const labelW = Math.max(4, topLabel.length, midLabel.length, bottomLabel.length)
  const gutterW = labelW + 2
  const plotW = Math.max(1, width - gutterW)

  const grid: string[][] = Array.from({ length: h }, () => Array.from({ length: plotW }, () => ' '))
  const col = (x: number): number => Math.round(((x - xMin) / xSpan) * (plotW - 1))
  const row = (y: number): number => Math.round((1 - (y - yMin) / ySpan) * (h - 1))

  // Fit line: sample each column across the line's x-range so it reads continuous.
  if (line.length >= 2) {
    const sorted = [...line].sort((a, b) => a.x - b.x)

    for (let c = 0; c < plotW; c += 1) {
      const x = xMin + (c / Math.max(1, plotW - 1)) * xSpan

      if (x < sorted[0]!.x || x > sorted[sorted.length - 1]!.x) {
        continue
      }

      // linear interp between the two enclosing fit points
      let y = sorted[0]!.y

      for (let i = 1; i < sorted.length; i += 1) {
        if (x <= sorted[i]!.x) {
          const a = sorted[i - 1]!
          const b = sorted[i]!
          const t = b.x === a.x ? 0 : (x - a.x) / (b.x - a.x)
          y = a.y + t * (b.y - a.y)

          break
        }
      }

      const r = row(y)

      if (r >= 0 && r < h) {
        grid[r]![c] = LINE
      }
    }
  }

  for (const p of pts) {
    const c = Math.max(0, Math.min(plotW - 1, col(p.x)))
    const r = Math.max(0, Math.min(h - 1, row(p.y)))
    grid[r]![c] = grid[r]![c] === POINT || grid[r]![c] === OVERLAP ? OVERLAP : POINT
  }

  const rows = grid.map((cells, r) => {
    const label = r === 0 ? topLabel : r === h - 1 ? bottomLabel : r === Math.floor((h - 1) / 2) ? midLabel : ''

    return `${label.padStart(labelW)} │ ${cells.join('')}`
  })

  const bottom = `${' '.repeat(labelW)}   ${compactNumber(xMin)}${' '.repeat(Math.max(1, plotW - compactNumber(xMin).length - compactNumber(xMax).length))}${compactNumber(xMax)}`

  return { axis: { bottom }, rows }
}

export interface TableColumn {
  align?: 'left' | 'right'
  key: string
  label: string
}

/**
 * Render a fixed-width ASCII table: header + rule + rows, each clipped to
 * `width`. When too narrow, drops the lowest-priority (right-most) columns
 * rather than wrapping (mirrors the priority-drop in marketsView). Numbers are
 * formatted via `compactNumber`.
 */
export const asciiTable = (
  columns: ReadonlyArray<TableColumn>,
  rows: ReadonlyArray<Record<string, number | string>>,
  { maxRows = 50, width = 72 }: { maxRows?: number; width?: number } = {}
): string[] => {
  const cols = (columns ?? []).filter(c => c && typeof c.key === 'string')

  if (cols.length === 0) {
    return []
  }

  const dataRows = (rows ?? []).slice(0, maxRows)

  const cell = (col: TableColumn, value: unknown): string => {
    if (typeof value === 'number') {
      return compactNumber(value)
    }

    return value == null ? '' : String(value)
  }

  // Natural width per column = max(label, widest cell), capped so the table fits.
  const widths = cols.map(c => {
    const body = Math.max(c.label.length, ...dataRows.map(r => cell(c, r[c.key]).length), 3)

    return Math.min(body, 28)
  })

  // Drop right-most columns until the total fits the width budget.
  let shown = cols.length
  const total = () => widths.slice(0, shown).reduce((a, b) => a + b, 0) + (shown - 1) * 2

  while (shown > 1 && total() > width) {
    shown -= 1
  }

  const used = cols.slice(0, shown)
  const usedW = widths.slice(0, shown)

  const fmt = (text: string, w: number, align?: 'left' | 'right'): string => {
    const clipped = text.length > w ? `${text.slice(0, Math.max(0, w - 1))}…` : text

    return align === 'right' ? clipped.padStart(w) : clipped.padEnd(w)
  }

  const header = used.map((c, i) => fmt(c.label, usedW[i]!, c.align)).join('  ')
  const rule = used.map((_, i) => '─'.repeat(usedW[i]!)).join('  ')
  const body = dataRows.map(r => used.map((c, i) => fmt(cell(c, r[c.key]), usedW[i]!, c.align)).join('  '))

  return [header, rule, ...body]
}
