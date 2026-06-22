// Distribution — a filled probability density (half-block area UNDER the PDF
// curve, with credible-interval x-ranges shaded darker), a bright braille PDF
// edge, an optional braille CDF overlay, and mean/median marker lines. For
// forecast / prediction-market posteriors.

import { BrailleCanvas, brailleChar, SubRowCanvas } from '../blit.js'
import { CellBuffer } from '../buffer.js'
import { mix, parseHex, toHex } from '../color.js'
import type { RenderCtx, RenderResult, StyledRow } from '../types.js'

import { gutterText, yGutter } from './_layout.js'

export interface DistributionInterval {
  hi: number
  lo: number
  p?: number
}

export interface DistributionData {
  cdf?: number[]
  intervals?: DistributionInterval[]
  mean?: number
  median?: number
  pdf: number[]
  support: number[]
  xLabel?: string
}

const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n)

export const renderDistribution = (data: DistributionData, ctx: RenderCtx): RenderResult => {
  const { theme, width } = ctx
  const height = Math.max(4, ctx.height ?? 9)

  const support = data.support ?? []
  const pdf = data.pdf ?? []
  const pairs: [number, number][] = []

  for (let i = 0; i < Math.min(support.length, pdf.length); i++) {
    if (finite(support[i]) && finite(pdf[i])) {
      pairs.push([support[i]!, pdf[i]!])
    }
  }

  if (pairs.length < 2) {
    return { rows: [] }
  }

  pairs.sort((a, b) => a[0] - b[0])

  const xLo = pairs[0]![0]
  const xHi = pairs[pairs.length - 1]![0]
  const xSpan = xHi - xLo || 1
  const yHi = Math.max(...pairs.map(p => p[1])) || 1

  const g = yGutter(0, yHi, width)
  const subH = height * 2
  const dotW = g.plotW * 2
  const dotH = height * 4
  const colAt = (x: number): number => Math.max(0, Math.min(g.plotW - 1, Math.round(((x - xLo) / xSpan) * (g.plotW - 1))))
  const subX = (x: number): number => Math.round(((x - xLo) / xSpan) * (dotW - 1))
  const subYpdf = (y: number): number => Math.round((1 - y / yHi) * (dotH - 1))
  const subRowPdf = (y: number): number => Math.round((1 - y / yHi) * (subH - 1))

  // PDF value interpolated at a terminal column's x.
  const xAtCol = (c: number): number => xLo + (g.plotW <= 1 ? 0 : (c / (g.plotW - 1)) * xSpan)

  const pdfAtCol = (c: number): number => {
    const x = xAtCol(c)

    if (x <= pairs[0]![0]) {
      return pairs[0]![1]
    }

    for (let i = 1; i < pairs.length; i++) {
      if (x <= pairs[i]![0]) {
        const [ax, ay] = pairs[i - 1]!
        const [bx, by] = pairs[i]!
        const t = bx === ax ? 0 : (x - ax) / (bx - ax)

        return ay + (by - ay) * t
      }
    }

    return pairs[pairs.length - 1]![1]
  }

  // Intervals widest→narrowest so the narrowest (most probable) shades darkest.
  const intervals = (data.intervals ?? [])
    .filter(iv => iv && finite(iv.lo) && finite(iv.hi))
    .sort((a, b) => Math.abs(b.hi - b.lo) - Math.abs(a.hi - a.lo))

  // Dim fills that recede so the bright braille PDF edge + CDF read clearly. The
  // base density is very dim; credible-interval x-ranges are a touch brighter.
  const dim = parseHex(theme.bands[0] ?? theme.grid)
  const mid = parseHex(theme.bands[1] ?? theme.muted)
  const baseFill = toHex(mix(parseHex(theme.grid), dim, 0.4))

  const shadeForCol = (c: number): string => {
    const x = xAtCol(c)
    let rank = -1
    intervals.forEach((iv, i) => {
      if (x >= Math.min(iv.lo, iv.hi) && x <= Math.max(iv.lo, iv.hi)) {
        rank = i
      }
    })

    if (rank < 0) {
      return baseFill
    }

    const k = intervals.length <= 1 ? 0.35 : 0.2 + (rank / (intervals.length - 1)) * 0.45

    return toHex(mix(dim, mid, k))
  }

  // Fill the area under the PDF curve.
  const fill = new SubRowCanvas(g.plotW, height)

  for (let c = 0; c < g.plotW; c++) {
    const yc = pdfAtCol(c)

    if (!finite(yc)) {
      continue
    }

    fill.fillCol(c, subRowPdf(yc), subH - 1, shadeForCol(c))
  }

  // Bright PDF edge (braille).
  const pdfCanvas = new BrailleCanvas(g.plotW, height)

  for (let i = 1; i < pairs.length; i++) {
    pdfCanvas.line(subX(pairs[i - 1]![0]), subYpdf(pairs[i - 1]![1]), subX(pairs[i]![0]), subYpdf(pairs[i]![1]))
  }

  // CDF overlay (braille, scaled 0..1 to full height).
  let cdfCanvas: BrailleCanvas | null = null
  const cdf = data.cdf ?? []

  if (cdf.length) {
    cdfCanvas = new BrailleCanvas(g.plotW, height)
    const cdfMax = Math.max(...cdf.filter(finite), 1)
    const cnorm = cdfMax > 1 ? cdfMax : 1
    const cpts: [number, number][] = []

    for (let i = 0; i < Math.min(support.length, cdf.length); i++) {
      if (finite(support[i]) && finite(cdf[i])) {
        const cv = Math.max(0, Math.min(1, cdf[i]! / cnorm))
        cpts.push([subX(support[i]!), Math.round((1 - cv) * (dotH - 1))])
      }
    }

    cpts.sort((a, b) => a[0] - b[0])

    for (let i = 1; i < cpts.length; i++) {
      cdfCanvas.line(cpts[i - 1]![0], cpts[i - 1]![1], cpts[i]![0], cpts[i]![1])
    }
  }

  // Mean / median vertical markers (combined glyph on collision).
  const markers = new Map<number, string>()
  const medCol = finite(data.median) ? colAt(data.median) : null
  const meanCol = finite(data.mean) ? colAt(data.mean) : null

  if (medCol !== null) {
    markers.set(medCol, '┊')
  }

  if (meanCol !== null) {
    markers.set(meanCol, meanCol === medCol ? '╪' : '│')
  }

  const buf = new CellBuffer(g.plotW, height)

  for (let r = 0; r < height; r++) {
    for (let c = 0; c < g.plotW; c++) {
      const pMask = pdfCanvas.maskAt(c, r)

      if (pMask) {
        buf.set(c, r, brailleChar(pMask), { bold: true, color: theme.fg })

        continue
      }

      const cMask = cdfCanvas?.maskAt(c, r) ?? 0

      if (cMask) {
        buf.set(c, r, brailleChar(cMask), { color: theme.down })

        continue
      }

      if (markers.has(c)) {
        buf.set(c, r, markers.get(c)!, { color: theme.muted })

        continue
      }

      const cell = fill.cell(c, r)

      if (cell.text !== ' ') {
        buf.set(c, r, cell.text, { backgroundColor: cell.backgroundColor, color: cell.color })
      }
    }
  }

  const rows: StyledRow[] = buf.compile().map((runs, r) => [{ color: theme.muted, text: gutterText(r, height, g) }, ...runs])

  const legend: StyledRow[] = [
    [
      { color: theme.fg, text: '▔ pdf' },
      ...(cdf.length ? [{ color: theme.down, text: '   ▔ cdf' }] : []),
      ...(intervals.length ? [{ color: theme.muted, text: `   ▒ ${intervals.length > 1 ? 'intervals' : 'interval'}` }] : [])
    ]
  ]

  return { legend, rows }
}
