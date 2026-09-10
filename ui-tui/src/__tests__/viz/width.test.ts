import { stringWidth } from '@superforecasting/ink'
import { describe, expect, it } from 'vitest'

import { diverging, renderFan, renderHeatmap } from '../../lib/viz/index.js'
import type { ChartTheme, ColorMode, RenderCtx, StyledRow, TerminalCaps } from '../../lib/viz/index.js'

// The highest-value invariant: every emitted row is composed ONLY of width-1
// glyphs (no width-2 desync, the emoji-width bug class) and never overflows the
// width budget. We assert stringWidth(row) === codepoint count === fits width.

const THEME: ChartTheme = {
  bands: ['#222222', '#555555'],
  down: '#0000ff',
  fg: '#ffffff',
  grid: '#444444',
  heat: diverging('#0000ff', '#888888', '#ff0000'),
  muted: '#888888',
  up: '#ff0000'
}

const text = (row: StyledRow): string => row.map(r => r.text).join('')
const codepoints = (s: string): number => [...s].length

const MODES: { blitter: TerminalCaps['blitterMax']; mode: ColorMode }[] = [
  { blitter: 'braille', mode: 'truecolor' },
  { blitter: 'quad', mode: '256' },
  { blitter: '1x1', mode: '16' }
]

const matrix = (r: number, c: number): number[][] =>
  Array.from({ length: r }, (_, i) => Array.from({ length: c }, (_, j) => Math.sin(i * 0.7) * Math.cos(j * 0.5)))

const median = Array.from({ length: 40 }, (_, i) => 0.5 + 0.3 * Math.sin(i / 6))
const band = [{ lower: median.map(m => m - 0.15), upper: median.map(m => m + 0.15) }]
const paths = Array.from({ length: 12 }, (_, k) => median.map((m, i) => m + (k - 6) * 0.01 * Math.sin(i / 3)))

describe('width safety — every row is width-1 glyphs and fits the budget', () => {
  for (const w of [24, 40, 56, 80, 120]) {
    for (const { blitter, mode } of MODES) {
      const ctx: RenderCtx = { caps: { blitterMax: blitter, colorMode: mode, imageProtocol: 'none' }, height: 8, theme: THEME, width: w }

      it(`heatmap @w=${w} ${mode}`, () => {
        const r = renderHeatmap({ diverging: true, matrix: matrix(9, 13), rowLabels: ['alpha', 'beta', 'gamma'] }, ctx)

        for (const row of [...r.rows, ...(r.legend ?? [])]) {
          const t = text(row)
          expect(stringWidth(t)).toBe(codepoints(t)) // no width-2 glyph
          expect(stringWidth(t)).toBeLessThanOrEqual(w)
        }
      })

      it(`fan(paths) @w=${w} ${mode}`, () => {
        const r = renderFan({ bands: band, median, paths }, ctx)

        for (const row of r.rows) {
          const t = text(row)
          expect(stringWidth(t)).toBe(codepoints(t))
          expect(stringWidth(t)).toBeLessThanOrEqual(w)
        }
      })

      it(`fan(no paths) @w=${w} ${mode}`, () => {
        const r = renderFan({ bands: band, median }, ctx)

        for (const row of r.rows) {
          const t = text(row)
          expect(stringWidth(t)).toBe(codepoints(t))
          expect(stringWidth(t)).toBeLessThanOrEqual(w)
        }
      })
    }
  }
})

describe('perf shape — heatmap coalescing bounds run count', () => {
  it('120×40 truecolor heatmap: each row has at most `cols` runs (coalesced, not per-cell nodes)', () => {
    const ctx: RenderCtx = { caps: { blitterMax: 'braille', colorMode: 'truecolor', imageProtocol: 'none' }, height: 40, theme: THEME, width: 120 }
    const r = renderHeatmap({ diverging: true, matrix: matrix(80, 120) }, ctx)
    expect(r.rows.length).toBeGreaterThan(0)

    for (const row of r.rows) {
      expect(row.length).toBeLessThanOrEqual(120)
    }
  })
})
