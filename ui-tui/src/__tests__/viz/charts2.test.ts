import { stringWidth } from '@superforecasting/ink'
import { describe, expect, it } from 'vitest'

import { diverging, renderCandles, renderDepth, renderDistribution, renderScatter, renderSparkgrid } from '../../lib/viz/index.js'
import type { ChartTheme, ColorMode, RenderCtx, StyledRow, TerminalCaps } from '../../lib/viz/index.js'

const THEME: ChartTheme = {
  bands: ['#222222', '#555555'],
  down: '#0000ff',
  fg: '#ffffff',
  gain: '#00cc66',
  grid: '#444444',
  heat: diverging('#0000ff', '#888888', '#ff0000'),
  loss: '#ff3344',
  muted: '#888888',
  up: '#ff0000'
}

const ctx = (width = 60, over?: Partial<TerminalCaps>, height?: number): RenderCtx => ({
  caps: { blitterMax: 'braille', colorMode: 'truecolor', imageProtocol: 'none', ...over },
  height,
  theme: THEME,
  width
})

const text = (row: StyledRow): string => row.map(r => r.text).join('')
const isBraille = (s: string): boolean => [...s].some(c => c.codePointAt(0)! >= 0x2800 && c.codePointAt(0)! <= 0x28ff)
const colors = (rows: StyledRow[]): Set<string | undefined> => new Set(rows.flat().flatMap(r => [r.color, r.backgroundColor]).filter(Boolean))

// Width invariant shared by all charts (run per fixture below).
const MODES: ColorMode[] = ['truecolor', '256', '16']

const widthSafe = (rows: StyledRow[], w: number): void => {
  for (const row of rows) {
    expect(stringWidth(text(row))).toBeLessThanOrEqual(w)
  }
}

describe('renderDistribution', () => {
  const support = Array.from({ length: 50 }, (_, i) => -3 + (6 * i) / 49)
  const pdf = support.map(x => Math.exp(-(x * x) / 2))
  const cdf = pdf.map((_, i) => pdf.slice(0, i + 1).reduce((a, b) => a + b, 0) / pdf.reduce((a, b) => a + b, 0))

  it('renders a braille PDF with CDF + interval bands + markers', () => {
    const r = renderDistribution({ cdf, intervals: [{ hi: 1.28, lo: -1.28, p: 0.8 }], mean: 0, median: 0, pdf, support }, ctx(60, undefined, 9))
    expect(r.rows.length).toBe(9)
    expect(r.rows.some(row => isBraille(text(row)))).toBe(true)
    expect(text(r.rows.flat ? r.rows[Math.floor(9 / 2)]! : r.rows[0]!)).toContain('│') // mean marker (or gutter)
    expect(r.legend?.[0]?.some(run => run.text.includes('pdf'))).toBe(true)
  })

  it('width-safe across widths/modes; too-few points → empty', () => {
    for (const w of [24, 48, 80]) {
      for (const mode of MODES) {
        widthSafe(renderDistribution({ pdf, support }, ctx(w, { colorMode: mode }, 8)).rows, w)
      }
    }

    expect(renderDistribution({ pdf: [1], support: [0] }, ctx()).rows).toEqual([])
  })
})

describe('renderCandles', () => {
  const candles = Array.from({ length: 24 }, (_, i) => {
    const o = 100 + Math.sin(i / 3) * 5
    const c = o + (i % 2 ? 1.5 : -1.2)

    return { c, h: Math.max(o, c) + 1, l: Math.min(o, c) - 1, o }
  })

  it('renders half-block bodies + wicks with gain/loss colors', () => {
    const r = renderCandles({ candles }, ctx(60, undefined, 12))
    const joined = r.rows.map(text).join('\n')
    expect([...joined].some(c => '▀▄█'.includes(c))).toBe(true) // half-block bodies/wicks
    expect(colors(r.rows).has('#00cc66') && colors(r.rows).has('#ff3344')).toBe(true) // gain + loss
  })

  it('volume sub-panel + MA add rows/markers; width-safe', () => {
    const volume = candles.map((_, i) => 1000 + i * 50)
    const ma = candles.map(c => c.c)
    const r = renderCandles({ candles, ma, volume }, ctx(60, undefined, 12))
    expect(r.rows.some(row => text(row).includes('vol'))).toBe(true)

    for (const w of [24, 48, 80]) {
      widthSafe(renderCandles({ candles, ma, volume }, ctx(w, undefined, 12)).rows, w)
    }
  })

  it('empty → no rows', () => {
    expect(renderCandles({ candles: [] }, ctx()).rows).toEqual([])
  })
})

describe('renderDepth', () => {
  const bids = Array.from({ length: 10 }, (_, i) => ({ price: 100 - i * 0.5, size: 5 + i }))
  const asks = Array.from({ length: 10 }, (_, i) => ({ price: 101 + i * 0.5, size: 5 + i }))

  it('renders mirrored bid/ask areas + mid marker', () => {
    const r = renderDepth({ asks, bids, mid: 100.5 }, ctx(60, undefined, 9))
    const joined = r.rows.map(text).join('\n')
    expect(joined).toContain('█')
    expect(joined).toContain('┊') // mid marker
    expect(colors(r.rows).has('#00cc66') && colors(r.rows).has('#ff3344')).toBe(true) // bids gain + asks loss
  })

  it('width-safe; empty → no rows', () => {
    for (const w of [24, 48, 80]) {
      widthSafe(renderDepth({ asks, bids }, ctx(w, undefined, 9)).rows, w)
    }

    expect(renderDepth({ asks: [], bids: [] }, ctx()).rows).toEqual([])
  })
})

describe('renderSparkgrid', () => {
  const cells = Array.from({ length: 6 }, (_, i) => ({
    delta: i % 2 ? 0.03 : -0.01,
    label: `SYM${i}`,
    value: 100 + i * 10,
    values: Array.from({ length: 12 }, (_, j) => 100 + Math.sin(j / 2 + i))
  }))

  it('lays out a grid with labels, sparklines, and colored deltas', () => {
    const r = renderSparkgrid({ cells, columns: 2 }, ctx(80))
    expect(r.rows.length).toBe(3) // 6 cells / 2 cols
    const joined = r.rows.map(text).join('\n')
    expect(joined).toContain('SYM0')
    expect([...joined].some(c => '▁▂▃▄▅▆▇█'.includes(c))).toBe(true) // sparkline glyphs
    expect(colors(r.rows).has('#00cc66') && colors(r.rows).has('#ff3344')).toBe(true) // up + down deltas
  })

  it('width-safe across widths; empty → no rows', () => {
    for (const w of [40, 60, 100]) {
      widthSafe(renderSparkgrid({ cells }, ctx(w)).rows, w)
    }

    expect(renderSparkgrid({ cells: [] }, ctx()).rows).toEqual([])
  })

  it('wide-char labels/units + oversized values stay width-safe (visual-width clamp)', () => {
    const hostile = [
      { delta: 0.5, label: '日本語ロングラベル', unit: '％', value: 999999999, values: [1, 2, 3] },
      { delta: -0.5, label: '😀'.repeat(10), unit: 'verylongunit', value: 12345678, values: [3, 2, 1] }
    ]

    for (const w of [24, 40, 80]) {
      widthSafe(renderSparkgrid({ cells: hostile, columns: 2 }, ctx(w)).rows, w)
    }
  })
})

describe('renderScatter', () => {
  const points = [
    { x: 1, y: 1.1 },
    { x: 2, y: 1.9 },
    { x: 3, y: 3.2 },
    { x: 4, y: 3.9 }
  ]

  const fitLine = [
    { x: 1, y: 1 },
    { x: 4, y: 4 }
  ]

  it('renders braille points + a braille fit line with an x-axis', () => {
    const r = renderScatter({ fitLine, points }, ctx(60, undefined, 12))
    expect(r.rows.length).toBe(12)
    expect(r.rows.some(row => isBraille(text(row)))).toBe(true)
    expect(r.axisBottom?.length).toBeTruthy()
  })

  it('width-safe across widths; empty → no rows', () => {
    for (const w of [24, 48, 80]) {
      const r = renderScatter({ fitLine, points }, ctx(w, undefined, 10))
      widthSafe(r.rows, w)

      if (r.axisBottom) {
        widthSafe([r.axisBottom], w)
      }
    }

    expect(renderScatter({ points: [] }, ctx()).rows).toEqual([])
  })

  it('coerces malformed points (NaN/non-object) without crashing', () => {
    const bad = [{ x: 1, y: 2 }, { x: Number.NaN, y: 3 }, null, { x: 'z', y: 4 }] as unknown as { x: number; y: number }[]
    const r = renderScatter({ points: bad }, ctx(40, undefined, 8))
    widthSafe(r.rows, 40)
  })
})

describe('distribution markers + cdf robustness', () => {
  const support = Array.from({ length: 30 }, (_, i) => i)
  const pdf = support.map(x => Math.exp(-((x - 15) ** 2) / 20))

  it('mean==median column → combined ╪ marker (neither dropped)', () => {
    const r = renderDistribution({ mean: 15, median: 15, pdf, support }, ctx(60, undefined, 9))
    expect(r.rows.map(text).join('\n')).toContain('╪')
  })

  it('unnormalized (count-style) cdf is normalized, not clamped flat', () => {
    const cdf = support.map((_, i) => (i + 1) * 100) // 100..3000, not 0..1
    const r = renderDistribution({ cdf, pdf, support }, ctx(60, undefined, 9))
    // CDF braille should appear across multiple rows, not pinned to the top row.
    const cdfRows = r.rows.filter(row => isBraille(text(row)))
    expect(cdfRows.length).toBeGreaterThan(1)
  })
})
