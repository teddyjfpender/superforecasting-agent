// Heatmap — the flagship. Truecolor half-block packs two matrix rows into one
// terminal cell (fg = upper pixel, bg = lower pixel); at 256-color it emits
// `ansi256(n)` directly (Risk-3 guard); at 16-color it dual-encodes sign as
// fg color (up/down) and magnitude as a glyph-intensity ramp. Rows are
// coalesced via CellBuffer so a multi-color row is ONE <Text>, not one-per-cell.

import { stringWidth } from '@superforecasting/ink'

import { halfBlock } from '../blit.js'
import { CellBuffer } from '../buffer.js'
import { intensityGlyph, quantize } from '../color.js'
import type { RenderCtx, RenderResult, StyledRow } from '../types.js'

export interface HeatmapData {
  colLabels?: string[]
  diverging?: boolean // symmetric domain around 0 (correlation matrices)
  matrix: number[][]
  max?: number
  min?: number
  rowLabels?: string[]
  title?: string
}

const clamp = (v: number, lo: number, hi: number): number => Math.max(lo, Math.min(hi, v))

// Clip + pad a (possibly agent-supplied, possibly wide-char) label to an exact
// VISUAL width so the gutter never desyncs the plot (the emoji-width bug class).
const padVisual = (s: string, w: number): string => {
  let out = ''
  let used = 0

  for (const ch of s) {
    const cw = stringWidth(ch) || 1

    if (used + cw > w) {
      break
    }

    out += ch
    used += cw
  }

  return out + ' '.repeat(Math.max(0, w - used))
}

// Box-average a matrix down to (targetR × targetC). Up-sampling returns as-is
// (the caller widens columns separately for legibility).
const resample = (m: number[][], targetR: number, targetC: number): number[][] => {
  const R = m.length
  const C = m[0]?.length ?? 0

  if (R <= targetR && C <= targetC) {
    return m
  }

  const out: number[][] = []

  for (let r = 0; r < targetR; r++) {
    const r0 = Math.floor((r * R) / targetR)
    const r1 = Math.max(r0 + 1, Math.floor(((r + 1) * R) / targetR))
    const row: number[] = []

    for (let c = 0; c < targetC; c++) {
      const c0 = Math.floor((c * C) / targetC)
      const c1 = Math.max(c0 + 1, Math.floor(((c + 1) * C) / targetC))
      let sum = 0
      let n = 0

      for (let y = r0; y < r1 && y < R; y++) {
        for (let x = c0; x < c1 && x < C; x++) {
          const v = m[y]?.[x]

          if (Number.isFinite(v)) {
            sum += v as number
            n++
          }
        }
      }

      row.push(n ? sum / n : 0)
    }

    out.push(row)
  }

  return out
}

export const renderHeatmap = (data: HeatmapData, ctx: RenderCtx): RenderResult => {
  const { caps, theme, width } = ctx
  const matrix = (data.matrix ?? []).filter(Array.isArray)

  if (matrix.length === 0 || (matrix[0]?.length ?? 0) === 0) {
    return { rows: [] }
  }

  // Domain.
  let lo = data.min ?? Infinity
  let hi = data.max ?? -Infinity

  if (data.min === undefined || data.max === undefined) {
    for (const row of matrix) {
      for (const v of row) {
        if (Number.isFinite(v)) {
          lo = Math.min(lo, v)
          hi = Math.max(hi, v)
        }
      }
    }
  }

  if (!Number.isFinite(lo) || !Number.isFinite(hi)) {
    return { rows: [] }
  }

  if (data.diverging) {
    const m = Math.max(Math.abs(lo), Math.abs(hi)) || 1
    lo = -m
    hi = m
  }

  const span = hi - lo || 1
  // Coerce non-finite / ragged-matrix holes to the domain floor so a malformed
  // (agent-emitted) matrix never produces a NaN → invalid color string.
  const norm = (v: unknown): number => clamp(((Number.isFinite(v) ? (v as number) : lo) - lo) / span, 0, 1)

  // Layout: left gutter for row labels, plot to the right (visual-width sized).
  const rowLabels = (data.rowLabels ?? []).map(s => String(s ?? ''))
  const labelW = rowLabels.length ? Math.min(12, Math.max(...rowLabels.map(s => stringWidth(s)), 0)) : 0
  const gutterW = labelW ? labelW + 1 : 0
  const plotW = Math.max(1, width - gutterW)

  const sixteen = caps.colorMode === '16'
  const C = matrix[0]!.length
  const R = matrix.length

  // Fit columns to plot width; widen narrow matrices for legible square-ish cells.
  const outC = C <= plotW ? C * Math.max(1, Math.floor(plotW / C)) : plotW
  const matCols = Math.min(C, plotW)
  const m = resample(matrix, sixteen ? Math.min(R, ctx.height ?? R) : R, matCols)
  const mR = m.length
  const mC = m[0]!.length
  const colOf = (tc: number): number => Math.min(mC - 1, Math.floor((tc / outC) * mC))

  // textRows: half-block packs 2 matrix rows/row; 16-color uses 1/row.
  const textRows = sixteen ? mR : Math.ceil(mR / 2)
  const buf = new CellBuffer(outC, textRows)

  for (let tr = 0; tr < textRows; tr++) {
    const cells: { bg?: string; fg?: string; t: string }[] = []

    if (sixteen) {
      const matRow = m[tr]!

      for (let tc = 0; tc < outC; tc++) {
        const t = norm(matRow[colOf(tc)])
        // Diverging: magnitude = distance from the neutral midpoint (sign in fg).
        // Sequential: magnitude = the value itself.
        const mag = data.diverging ? Math.abs(t - 0.5) * 2 : t
        cells.push({ fg: data.diverging ? (t >= 0.5 ? theme.up : theme.down) : theme.fg, t: intensityGlyph(mag) })
      }
    } else {
      const topRow = m[tr * 2]!
      const botRow = tr * 2 + 1 < mR ? m[tr * 2 + 1]! : null

      for (let tc = 0; tc < outC; tc++) {
        const ci = colOf(tc)
        const top = quantize(theme.heat(norm(topRow[ci])), caps.colorMode)
        const bottom = botRow ? quantize(theme.heat(norm(botRow[ci])), caps.colorMode) : undefined
        const hb = halfBlock(top, bottom)
        cells.push({ bg: hb.backgroundColor, fg: hb.color, t: hb.text })
      }
    }

    buf.setRow(tr, cells)
  }

  const plotRows = buf.compile()

  // Prepend the row-label gutter (one cheap run per row).
  const rows: StyledRow[] = plotRows.map((runs, tr) => {
    if (!gutterW) {
      return runs
    }

    const srcRow = sixteen ? tr : tr * 2
    const label = padVisual(rowLabels[srcRow] ?? '', labelW)

    return [{ color: theme.muted, text: `${label} ` }, ...runs]
  })

  // Legend: a gradient bar + lo/mid/hi labels.
  const legendW = Math.min(16, plotW)
  const legendCells: { bg?: string; fg?: string; t: string }[] = []

  for (let i = 0; i < legendW; i++) {
    const t = legendW <= 1 ? 0 : i / (legendW - 1)

    if (sixteen) {
      legendCells.push({ fg: data.diverging ? (t >= 0.5 ? theme.up : theme.down) : theme.fg, t: intensityGlyph(data.diverging ? Math.abs(t - 0.5) * 2 : t) })
    } else {
      const c = quantize(theme.heat(t), caps.colorMode)
      legendCells.push({ bg: c, t: ' ' })
    }
  }

  const lb = new CellBuffer(legendW, 1)
  lb.setRow(0, legendCells)
  const fmt = (v: number): string => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2))

  const legend: StyledRow[] = [
    [...lb.compile()[0]!],
    [{ color: theme.muted, text: `${fmt(lo)}  ↔  ${fmt((lo + hi) / 2)}  ↔  ${fmt(hi)}` }]
  ]

  return { legend, rows }
}
