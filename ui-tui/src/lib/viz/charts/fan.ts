// Fan / Monte-Carlo cone. A smooth half-block confidence cone (2× vertical
// resolution, nested bands shade darker toward the center) with a bright braille
// median and optional faint braille sample paths on top. No paths AND no bands
// degrades to a plain braille median line.

import { axisLabels } from '../../forecastCharts.js'
import { type ChartMarker, overlayMarkers } from '../annotate.js'
import { BrailleCanvas, brailleChar, SubRowCanvas } from '../blit.js'
import { CellBuffer } from '../buffer.js'
import { mix, parseHex, toHex } from '../color.js'
import { lttb, niceDomain } from '../scale.js'
import type { RenderCtx, RenderResult, StyledRow } from '../types.js'

export interface FanBand {
  lower: number[]
  p_hi?: number
  p_lo?: number
  upper: number[]
}

export interface FanData {
  bands?: FanBand[]
  markers?: ChartMarker[]
  median: number[]
  paths?: number[][]
  x?: number[]
}

const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n)

// Linear sample of an array at fraction f∈[0,1].
const interpAt = (arr: number[], f: number): number => {
  if (!arr.length) {
    return NaN
  }

  const idx = Math.max(0, Math.min(arr.length - 1, f * (arr.length - 1)))
  const i0 = Math.floor(idx)
  const i1 = Math.min(arr.length - 1, i0 + 1)
  const a = arr[i0]
  const b = arr[i1]

  if (!finite(a) || !finite(b)) {
    return finite(a) ? a : finite(b) ? b : NaN
  }

  return a + (b - a) * (idx - i0)
}

export const renderFan = (data: FanData, ctx: RenderCtx): RenderResult => {
  const { theme, width } = ctx
  const height = Math.max(4, ctx.height ?? 8)
  const median = (data.median ?? []).filter(finite)

  const bands = (data.bands ?? [])
    .filter(b => b && (Array.isArray(b.lower) || Array.isArray(b.upper)))
    .map(b => ({ lower: (Array.isArray(b.lower) ? b.lower : []).filter(finite), upper: (Array.isArray(b.upper) ? b.upper : []).filter(finite) }))
    .filter(b => b.lower.length && b.upper.length)
    // Widest first → drawn first (faintest); narrower bands overpaint, darker.
    .sort((a, b) => b.upper[0]! - b.lower[0]! - (a.upper[0]! - a.lower[0]!))

  const paths = (data.paths ?? []).filter(p => Array.isArray(p) && p.some(finite)).slice(0, 12)

  const allY = [...median, ...bands.flatMap(b => [...b.lower, ...b.upper]), ...paths.flat()].filter(finite)

  if (!allY.length) {
    return { rows: [] }
  }

  const [yLo, yHi] = niceDomain(Math.min(...allY), Math.max(...allY))
  const ySpan = yHi - yLo || 1

  const [topLabel, midLabel, botLabel] = axisLabels([yHi, (yHi + yLo) / 2, yLo])
  const labelW = Math.max(4, topLabel!.length, midLabel!.length, botLabel!.length)
  const gutterW = labelW + 2
  const plotW = Math.max(1, width - gutterW)
  const subH = height * 2
  const dotW = plotW * 2
  const dotH = height * 4
  const subRowOf = (y: number): number => Math.round((1 - (y - yLo) / ySpan) * (subH - 1))
  const subX = (i: number, len: number): number => (len <= 1 ? 0 : Math.round((i / (len - 1)) * (dotW - 1)))
  const subYdot = (y: number): number => Math.round((1 - (y - yLo) / ySpan) * (dotH - 1))

  // Confidence cone: a DIM continuous half-block fill (recedes into the
  // background) bounded by a crisp braille outline, so it reads as a smooth
  // shaded region rather than heavy gray staircase blocks.
  const cone = new SubRowCanvas(plotW, height)
  const dim = parseHex(theme.bands[0] ?? theme.grid)
  const mid = parseHex(theme.bands[1] ?? theme.muted)
  bands.forEach((band, rank) => {
    // Keep fills subtle: single band ≈ dim; nested bands step a little brighter
    // toward the centre but never enough to fight the median/outline.
    const k = bands.length <= 1 ? 0.18 : 0.1 + (rank / (bands.length - 1)) * 0.45
    const shade = toHex(mix(dim, mid, k))

    for (let c = 0; c < plotW; c++) {
      const f = plotW <= 1 ? 0 : c / (plotW - 1)
      const up = interpAt(band.upper, f)
      const lo = interpAt(band.lower, f)

      if (finite(up) && finite(lo)) {
        cone.fillCol(c, subRowOf(up), subRowOf(lo), shade)
      }
    }
  })

  const drawBraille = (canvas: BrailleCanvas, ys: number[]): void => {
    const pts: [number, number][] = ys.map((y, i) => [subX(i, ys.length), subYdot(y)])
    const reduced = pts.length > dotW ? lttb(pts, dotW) : pts

    for (let i = 1; i < reduced.length; i++) {
      canvas.line(reduced[i - 1]![0], reduced[i - 1]![1], reduced[i]![0], reduced[i]![1])
    }
  }

  // Smooth braille outline of the OUTERMOST band (4× vertical res → a clean
  // curved boundary, not a stair-stepped block edge).
  const edgeCanvas = new BrailleCanvas(plotW, height)
  const outer = bands[0]

  if (outer) {
    drawBraille(edgeCanvas, outer.upper)
    drawBraille(edgeCanvas, outer.lower)
  }

  // Spaghetti paths are noise once a cone is drawn — only show them as the
  // spread representation when there is NO band.
  const showPaths = paths.length > 0 && bands.length === 0
  const pathsCanvas = new BrailleCanvas(plotW, height)

  if (showPaths) {
    for (const p of paths) {
      drawBraille(pathsCanvas, p.filter(finite))
    }
  }

  const medianCanvas = new BrailleCanvas(plotW, height)

  if (median.length) {
    drawBraille(medianCanvas, median)
  }

  const buf = new CellBuffer(plotW, height)

  for (let r = 0; r < height; r++) {
    for (let c = 0; c < plotW; c++) {
      const mMask = medianCanvas.maskAt(c, r)

      if (mMask) {
        buf.set(c, r, brailleChar(mMask), { bold: true, color: theme.fg })

        continue
      }

      const eMask = edgeCanvas.maskAt(c, r)

      if (eMask) {
        buf.set(c, r, brailleChar(eMask), { color: theme.muted })

        continue
      }

      const pMask = showPaths ? pathsCanvas.maskAt(c, r) : 0

      if (pMask) {
        buf.set(c, r, brailleChar(pMask), { color: theme.muted, dim: true })

        continue
      }

      const cell = cone.cell(c, r)

      if (cell.text !== ' ') {
        buf.set(c, r, cell.text, { backgroundColor: cell.backgroundColor, color: cell.color })
      }
    }
  }

  overlayMarkers(buf, data.markers, (y: number) => Math.floor(subRowOf(y) / 2), plotW, height, theme)

  const rows: StyledRow[] = buf.compile().map((runs, r) => {
    const label = r === 0 ? topLabel! : r === height - 1 ? botLabel! : r === Math.floor((height - 1) / 2) ? midLabel! : ''

    return [{ color: theme.muted, text: `${label.padStart(labelW)} │` }, ...runs]
  })

  const legend: StyledRow[] = [
    [
      { color: theme.fg, text: '▔ median' },
      ...(bands.length ? [{ color: theme.muted, text: `   ░ ${(data.bands?.length ?? 0) > 1 ? `${data.bands!.length}-band ` : ''}cone` }] : []),
      ...(showPaths ? [{ color: theme.muted, text: `   ⠂ ${paths.length} paths` }] : [])
    ]
  ]

  return { legend, rows }
}
