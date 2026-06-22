import { describe, expect, it } from 'vitest'

import { diverging, renderFan, renderHeatmap } from '../../lib/viz/index.js'
import type { ChartTheme, RenderCtx, StyledRow, TerminalCaps } from '../../lib/viz/index.js'

const THEME: ChartTheme = {
  bands: ['#222222', '#555555'],
  down: '#0000ff',
  fg: '#ffffff',
  grid: '#444444',
  heat: diverging('#0000ff', '#888888', '#ff0000'),
  muted: '#888888',
  up: '#ff0000'
}

const caps = (over?: Partial<TerminalCaps>): TerminalCaps => ({ blitterMax: 'braille', colorMode: 'truecolor', imageProtocol: 'none', ...over })
const ctx = (width: number, over?: Partial<TerminalCaps>, height?: number): RenderCtx => ({ caps: caps(over), height, theme: THEME, width })
const text = (row: StyledRow): string => row.map(r => r.text).join('')
const isBraille = (s: string): boolean => [...s].some(c => c.codePointAt(0)! >= 0x2800 && c.codePointAt(0)! <= 0x28ff)

describe('renderHeatmap', () => {
  const matrix = [
    [1, -1],
    [-1, 1]
  ]

  it('truecolor: half-block rows with fg+bg colors', () => {
    const r = renderHeatmap({ diverging: true, matrix }, ctx(24))
    expect(r.rows.length).toBe(1) // 2 matrix rows → 1 half-block row
    const run = r.rows[0]!.find(x => x.text.includes('▀'))!
    expect(run).toBeTruthy()
    expect(run.color).toMatch(/^#/)
    expect(run.backgroundColor).toMatch(/^#/)
    expect(r.legend?.length).toBeTruthy()
  })

  it('256: emits ansi256(n) colors (Risk-3 direct quantization)', () => {
    const r = renderHeatmap({ diverging: true, matrix }, ctx(24, { colorMode: '256' }))
    const run = r.rows[0]!.find(x => x.color)!
    expect(run.color).toMatch(/^ansi256\(\d+\)$/)
  })

  it('16: dual-encodes sign as fg color + magnitude as intensity glyph', () => {
    const r = renderHeatmap({ diverging: true, matrix }, ctx(24, { blitterMax: '1x1', colorMode: '16' }))
    expect(r.rows.length).toBe(2) // 1 matrix row per text row at 16-color
    const glyphs = new Set([...text(r.rows[0]!)])

    for (const g of glyphs) {
      expect(' ░▒▓█'.includes(g)).toBe(true)
    }

    const colors = new Set(r.rows.flat().map(x => x.color))
    expect(colors.has('#ff0000') || colors.has('#0000ff')).toBe(true) // up/down sign
  })

  it('empty matrix → no rows', () => {
    expect(renderHeatmap({ matrix: [] }, ctx(24)).rows).toEqual([])
  })
})

describe('renderFan', () => {
  const median = [0.2, 0.4, 0.5, 0.55, 0.6]
  const bands = [{ lower: [0.1, 0.2, 0.3, 0.3, 0.35], p_hi: 90, p_lo: 10, upper: [0.3, 0.6, 0.7, 0.8, 0.85] }]

  it('no paths → half-block cone + braille median', () => {
    const r = renderFan({ bands, median }, ctx(48, undefined, 8))
    expect(r.rows.length).toBe(8)
    const joined = r.rows.map(text).join('\n')
    expect(isBraille(joined)).toBe(true) // median drawn as braille
    expect([...joined].some(c => '▀▄█'.includes(c))).toBe(true) // half-block cone fill
  })

  it('with paths → braille Monte-Carlo cone', () => {
    const paths = Array.from({ length: 8 }, (_, k) => median.map((m, i) => m + (k - 4) * 0.02 * (i + 1)))
    const r = renderFan({ bands, median, paths }, ctx(56, undefined, 8))
    expect(r.rows.length).toBe(8)
    expect(r.rows.some(row => isBraille(text(row)))).toBe(true) // median/paths drawn as braille
  })
})
