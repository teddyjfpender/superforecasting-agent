// Scatter / regression — braille points (2×4 subcell resolution, far crisper
// than one ● per cell) over a braille fit line. Powers the presentation
// `scatter` + `regression` blocks; the caller renders the R²/coeff stat line.

import { compactNumber } from '../../forecastCharts.js'
import { type ChartMarker, overlayMarkers } from '../annotate.js'
import { BrailleCanvas, brailleChar } from '../blit.js'
import { CellBuffer } from '../buffer.js'
import type { RenderCtx, RenderResult, StyledRow } from '../types.js'

import { gutterText, yGutter } from './_layout.js'

export interface ScatterPoint {
  x: number
  y: number
}

export interface ScatterData {
  fitLine?: ScatterPoint[]
  markers?: ChartMarker[]
  points: ScatterPoint[]
  xLabel?: string
  yLabel?: string
}

const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n)

const xy = (arr: unknown): ScatterPoint[] =>
  Array.isArray(arr)
    ? arr
        .filter((p): p is Record<string, unknown> => Boolean(p) && typeof p === 'object')
        .map(p => ({ x: Number(p.x), y: Number(p.y) }))
        .filter(p => finite(p.x) && finite(p.y))
    : []

export const renderScatter = (data: ScatterData, ctx: RenderCtx): RenderResult => {
  const { theme, width } = ctx
  const height = Math.max(4, ctx.height ?? 12)
  const pts = xy(data.points)
  const fit = xy(data.fitLine)

  if (pts.length === 0 && fit.length === 0) {
    return { rows: [] }
  }

  const xs = [...pts, ...fit].map(p => p.x)
  const ys = [...pts, ...fit].map(p => p.y)
  const xMin = Math.min(...xs)
  const xMax = Math.max(...xs)
  const yMin = Math.min(...ys)
  const yMax = Math.max(...ys)
  const xSpan = xMax - xMin || 1
  const ySpan = yMax - yMin || 1

  const g = yGutter(yMin, yMax, width)
  const dotW = g.plotW * 2
  const dotH = height * 4
  const subX = (x: number): number => Math.round(((x - xMin) / xSpan) * (dotW - 1))
  const subY = (y: number): number => Math.round((1 - (y - yMin) / ySpan) * (dotH - 1))

  // Fit line: sample each sub-column across the line's x-range (interpolated) so
  // it reads continuous regardless of how many fit points were supplied.
  const fitCanvas = new BrailleCanvas(g.plotW, height)

  if (fit.length >= 2) {
    const sorted = [...fit].sort((a, b) => a.x - b.x)
    let prev: [number, number] | null = null

    for (let sx = 0; sx < dotW; sx++) {
      const x = xMin + (sx / Math.max(1, dotW - 1)) * xSpan

      if (x < sorted[0]!.x || x > sorted[sorted.length - 1]!.x) {
        continue
      }

      let y = sorted[0]!.y

      for (let i = 1; i < sorted.length; i++) {
        if (x <= sorted[i]!.x) {
          const a = sorted[i - 1]!
          const b = sorted[i]!
          const t = b.x === a.x ? 0 : (x - a.x) / (b.x - a.x)
          y = a.y + t * (b.y - a.y)

          break
        }
      }

      const sy = subY(y)

      if (prev) {
        fitCanvas.line(prev[0], prev[1], sx, sy)
      }

      prev = [sx, sy]
    }
  }

  // Fat marker: a 3×3 dot cluster per point so sparse data reads clearly (a lone
  // braille dot is only 1/8 of a cell). Dense data merges into a solid band.
  const pointsCanvas = new BrailleCanvas(g.plotW, height)

  for (const p of pts) {
    const cx = subX(p.x)
    const cy = subY(p.y)

    for (let dx = -1; dx <= 1; dx++) {
      for (let dy = -1; dy <= 1; dy++) {
        pointsCanvas.plot(cx + dx, cy + dy)
      }
    }
  }

  const buf = new CellBuffer(g.plotW, height)

  for (let r = 0; r < height; r++) {
    for (let c = 0; c < g.plotW; c++) {
      const pm = pointsCanvas.maskAt(c, r)
      const fm = fitCanvas.maskAt(c, r)

      if (pm) {
        buf.set(c, r, brailleChar(pm), { bold: true, color: theme.up })
      } else if (fm) {
        buf.set(c, r, brailleChar(fm), { color: theme.muted, dim: true })
      }
    }
  }

  overlayMarkers(buf, data.markers, (y: number) => Math.floor(subY(y) / 4), g.plotW, height, theme)

  const rows: StyledRow[] = buf.compile().map((runs, r) => [{ color: theme.muted, text: gutterText(r, height, g) }, ...runs])

  // X axis: min/max spread under the plot, aligned to the gutter.
  const xlo = compactNumber(xMin)
  const xhi = compactNumber(xMax)
  const pad = Math.max(1, g.plotW - xlo.length - xhi.length)
  const axisBottom: StyledRow = [{ color: theme.muted, text: `${' '.repeat(g.labelW + 2)}${xlo}${' '.repeat(pad)}${xhi}` }]

  return { axisBottom, rows }
}
