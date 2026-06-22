// Candlestick OHLC — discrete candles (gap between each), half-block bodies
// (sub-cell open/close precision), thin sub-cell wicks, an optional braille
// moving-average line, and a half-block volume sub-panel. Gain green / loss red.

import { compactNumber } from '../../forecastCharts.js'
import { type ChartMarker, overlayMarkers } from '../annotate.js'
import { BrailleCanvas, brailleChar, SubRowCanvas } from '../blit.js'
import { CellBuffer } from '../buffer.js'
import { niceDomain } from '../scale.js'
import type { RenderCtx, RenderResult, StyledRow } from '../types.js'

import { gutterText, yGutter } from './_layout.js'

export interface Candle {
  c: number
  h: number
  l: number
  o: number
  t?: number | string
}

export interface CandleData {
  candles: Candle[]
  ma?: number[]
  markers?: ChartMarker[]
  volume?: number[]
}

const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n)

const isCandle = (c: unknown): c is Candle =>
  Boolean(c) && typeof c === 'object' && ['o', 'h', 'l', 'c'].every(k => finite((c as Record<string, unknown>)[k]))

export const renderCandles = (data: CandleData, ctx: RenderCtx): RenderResult => {
  const { theme, width } = ctx
  const totalH = Math.max(5, ctx.height ?? 12)
  const all = (data.candles ?? []).filter(isCandle)

  if (all.length === 0) {
    return { rows: [] }
  }

  const hasVol = Array.isArray(data.volume) && data.volume.some(finite)
  const volH = hasVol ? 2 : 0
  const priceH = Math.max(3, totalH - volH - (hasVol ? 1 : 0))

  // Discrete candles: each occupies a `slot` (body + a 1-col gap when room).
  const probe = yGutter(0, 1, width)
  const slot = Math.max(1, Math.min(5, Math.floor(probe.plotW / all.length)))
  const bodyW = slot >= 2 ? slot - 1 : 1
  const fit = Math.max(1, Math.floor(probe.plotW / slot))
  const candles = all.slice(all.length - Math.min(all.length, fit))
  const offset = all.length - candles.length
  const ma = Array.isArray(data.ma) ? data.ma.slice(offset) : []
  const vol = hasVol ? (data.volume ?? []).slice(offset) : []

  const [yLo, yHi] = niceDomain(Math.min(...candles.map(c => c.l)), Math.max(...candles.map(c => c.h)))
  const ySpan = yHi - yLo || 1
  const g = yGutter(yLo, yHi, width)
  const subH = priceH * 2
  const subRowOf = (p: number): number => Math.max(0, Math.min(subH - 1, Math.round((1 - (p - yLo) / ySpan) * (subH - 1))))
  const colStart = (i: number): number => i * slot
  const wickColAt = (i: number): number => colStart(i) + Math.floor((bodyW - 1) / 2)

  const body = new SubRowCanvas(g.plotW, priceH)
  const maCanvas = new BrailleCanvas(g.plotW, priceH)
  const dotH = priceH * 4
  const subYdot = (p: number): number => Math.round((1 - (p - yLo) / ySpan) * (dotH - 1))

  candles.forEach((cd, i) => {
    if (colStart(i) >= g.plotW) {
      return
    }

    const color = cd.c >= cd.o ? theme.gain : theme.loss
    // Wick (thin, full high→low) drawn first; the wider body overpaints it.
    body.fillCol(wickColAt(i), subRowOf(cd.h), subRowOf(cd.l), color)
    let top = subRowOf(Math.max(cd.o, cd.c))
    let bot = subRowOf(Math.min(cd.o, cd.c))

    if (top === bot) {
      bot = Math.min(subH - 1, top + 1) // a doji still shows a 1-subrow body
    }

    for (let w = 0; w < bodyW && colStart(i) + w < g.plotW; w++) {
      body.fillCol(colStart(i) + w, top, bot, color)
    }
  })

  // Moving-average braille line across candle centers.
  if (ma.length) {
    const pts: [number, number][] = []
    candles.forEach((_, i) => {
      const m = ma[i]

      if (finite(m)) {
        pts.push([wickColAt(i) * 2, subYdot(m)])
      }
    })

    for (let i = 1; i < pts.length; i++) {
      maCanvas.line(pts[i - 1]![0], pts[i - 1]![1], pts[i]![0], pts[i]![1])
    }
  }

  const buf = new CellBuffer(g.plotW, priceH)

  for (let r = 0; r < priceH; r++) {
    for (let c = 0; c < g.plotW; c++) {
      const m = maCanvas.maskAt(c, r)

      if (m) {
        buf.set(c, r, brailleChar(m), { bold: true, color: theme.fg })

        continue
      }

      const cell = body.cell(c, r)

      if (cell.text !== ' ') {
        buf.set(c, r, cell.text, { backgroundColor: cell.backgroundColor, color: cell.color })
      }
    }
  }

  overlayMarkers(buf, data.markers, (y: number) => Math.floor(subRowOf(y) / 2), g.plotW, priceH, theme)

  const rows: StyledRow[] = buf.compile().map((runs, r) => [{ color: theme.muted, text: gutterText(r, priceH, g) }, ...runs])

  if (hasVol) {
    const maxVol = Math.max(...vol.filter(finite), 1)
    const volCanvas = new SubRowCanvas(g.plotW, volH)
    const volSub = volH * 2
    candles.forEach((cd, i) => {
      const v = vol[i]

      if (!finite(v) || colStart(i) >= g.plotW) {
        return
      }

      const top = Math.round((1 - v / maxVol) * (volSub - 1))
      const color = cd.c >= cd.o ? theme.gain : theme.loss

      for (let w = 0; w < bodyW && colStart(i) + w < g.plotW; w++) {
        volCanvas.fillCol(colStart(i) + w, top, volSub - 1, color)
      }
    })

    for (let r = 0; r < volH; r++) {
      const label = r === 0 ? 'vol' : ''
      const cells: StyledRow = []

      for (let c = 0; c < g.plotW; c++) {
        const cell = volCanvas.cell(c, r)
        cells.push(cell.text === ' ' ? { text: ' ' } : { backgroundColor: cell.backgroundColor, color: cell.color, text: cell.text })
      }

      rows.push([{ color: theme.muted, text: `${label.padStart(g.labelW)} │` }, ...cells])
    }
  }

  const last = candles[candles.length - 1]!
  const fmt = (v: number): string => compactNumber(v)

  const legend: StyledRow[] = [
    [
      { color: last.c >= last.o ? theme.gain : theme.loss, text: `▮ ${fmt(last.c)}` },
      { color: theme.muted, text: `  O ${fmt(last.o)} H ${fmt(last.h)} L ${fmt(last.l)}` },
      ...(ma.length ? [{ color: theme.fg, text: '  ⠂ MA' }] : [])
    ]
  ]

  return { legend, rows }
}
