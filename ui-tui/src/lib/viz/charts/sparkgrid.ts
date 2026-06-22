// SparklineGrid — a dashboard grid of labeled mini-charts (sparkline + last
// value + colored delta) for a watchlist / portfolio. Composes the existing
// sparkline + compactNumber + deltaGlyph primitives; no new glyph machinery.

import { stringWidth } from '@hermes/ink'

import { compactNumber, deltaGlyph } from '../../forecastCharts.js'
import { sparkline } from '../../sparkline.js'
import type { RenderCtx, RenderResult, StyledRow, StyledRun } from '../types.js'

// Truncate + pad a cell's runs to EXACTLY w visual columns, so agent-supplied
// labels/units (incl. wide chars) can never overflow the cell or desync columns.
const clampCell = (runs: StyledRun[], w: number): StyledRun[] => {
  const out: StyledRun[] = []
  let used = 0

  for (const run of runs) {
    if (used >= w) {
      break
    }

    let t = ''

    for (const ch of run.text) {
      const cw = stringWidth(ch) || 1

      if (used + cw > w) {
        break
      }

      t += ch
      used += cw
    }

    if (t) {
      out.push({ ...run, text: t })
    }
  }

  if (used < w) {
    out.push({ text: ' '.repeat(w - used) })
  }

  return out
}

export interface SparkCell {
  delta?: number
  label: string
  unit?: string
  value?: number
  values?: number[]
}

export interface SparkGridData {
  cells: SparkCell[]
  columns?: number
}

const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n)
const clip = (s: string, w: number): string => (s.length > w ? `${s.slice(0, Math.max(0, w - 1))}…` : s)

export const renderSparkgrid = (data: SparkGridData, ctx: RenderCtx): RenderResult => {
  const { theme, width } = ctx
  const cells = (data.cells ?? []).filter(c => c && typeof c.label === 'string')

  if (!cells.length) {
    return { rows: [] }
  }

  // Column count bounded so every cell is ≥ minCellW AND the row fits `width`
  // (the Math.max-floor min could otherwise overflow at small widths).
  const gap = 2
  const minCellW = 12
  const maxCols = Math.max(1, Math.floor((width + gap) / (minCellW + gap)))
  const requested = data.columns ?? Math.max(1, Math.floor((width + gap) / (26 + gap)))
  const columns = Math.max(1, Math.min(requested, maxCols, cells.length))
  const cellW = Math.max(1, Math.floor((width - gap * (columns - 1)) / columns))

  // Layout inside a cell: "label  spark  value Δ" — value+delta right-aligned.
  const valueText = (c: SparkCell): string => {
    const v = finite(c.value) ? compactNumber(c.value) : ''
    const d = finite(c.delta) ? `${deltaGlyph(c.delta)}` : ''

    return [v + (c.unit ? c.unit : ''), d].filter(Boolean).join(' ')
  }

  const cellRuns = (c: SparkCell): StyledRun[] => {
    const right = valueText(c)
    const rightW = right.length
    const deltaColor = finite(c.delta) ? (c.delta >= 0 ? theme.gain : theme.loss) : theme.muted
    // Reserve label ≈ 40% of cell, spark fills the middle.
    const labelW = Math.max(4, Math.floor(cellW * 0.4))
    const sparkW = Math.max(0, cellW - labelW - 1 - rightW - 1)
    const label = clip(c.label, labelW).padEnd(labelW)
    const spark = sparkW > 0 && (c.values?.length ?? 0) > 1 ? sparkline(c.values!, sparkW).padEnd(sparkW) : ' '.repeat(sparkW)

    const runs: StyledRun[] = [
      { color: theme.fg, text: `${label} ` },
      { color: theme.muted, text: spark }
    ]

    if (right) {
      // pad so the cell is exactly cellW wide
      const used = labelW + 1 + sparkW
      const padLeft = Math.max(1, cellW - used - rightW)
      runs.push({ color: theme.muted, text: ' '.repeat(padLeft) })
      const v = finite(c.value) ? compactNumber(c.value) + (c.unit ?? '') : ''

      if (v) {
        runs.push({ color: theme.fg, text: v })
      }

      if (finite(c.delta)) {
        runs.push({ color: deltaColor, text: ` ${deltaGlyph(c.delta)}` })
      }
    } else {
      runs.push({ color: theme.muted, text: ' '.repeat(Math.max(0, cellW - labelW - 1 - sparkW)) })
    }

    // Final guard: pin the cell to exactly cellW visual columns regardless of
    // label/unit/value content (wide chars, oversized numbers).
    return clampCell(runs, cellW)
  }

  const rows: StyledRow[] = []

  for (let i = 0; i < cells.length; i += columns) {
    const rowCells = cells.slice(i, i + columns)
    const row: StyledRow = []
    rowCells.forEach((c, j) => {
      if (j > 0) {
        row.push({ text: ' '.repeat(gap) })
      }

      row.push(...cellRuns(c))
    })
    rows.push(row)
  }

  return { rows }
}
