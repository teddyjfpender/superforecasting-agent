import { stringWidth } from '@hermes/ink'
import { describe, expect, it } from 'vitest'

import { diverging, renderFan, renderHeatmap } from '../../lib/viz/index.js'
import type { ChartTheme, RenderCtx, StyledRow, TerminalCaps } from '../../lib/viz/index.js'

// Chart data is LLM-emitted JSON, so malformed shapes (ragged matrices, wide-char
// labels, null band arrays, all-NaN values) must degrade — never crash or desync.

const THEME: ChartTheme = {
  bands: ['#222222', '#555555'],
  down: '#0000ff',
  fg: '#ffffff',
  grid: '#444444',
  heat: diverging('#0000ff', '#888888', '#ff0000'),
  muted: '#888888',
  up: '#ff0000'
}

const ctx = (over?: Partial<TerminalCaps>, width = 60): RenderCtx => ({ caps: { blitterMax: 'braille', colorMode: 'truecolor', imageProtocol: 'none', ...over }, height: 8, theme: THEME, width })
const text = (row: StyledRow): string => row.map(r => r.text).join('')

// Rows must never overflow the budget. (The stricter "plot has no width-2 glyph"
// invariant lives in width.test.ts; row LABELS may legitimately be wide, and are
// padded to an exact visual width so the plot still aligns.)
const widthSafe = (rows: StyledRow[], w: number): void => {
  for (const row of rows) {
    expect(stringWidth(text(row))).toBeLessThanOrEqual(w)
  }
}

const gutterAligned = (rows: StyledRow[]): void => {
  const widths = rows.map(r => (r[0] ? stringWidth(r[0].text) : 0))
  expect(new Set(widths).size).toBeLessThanOrEqual(1) // every gutter same visual width
}

const noBadColor = (rows: StyledRow[]): void => {
  for (const run of rows.flat()) {
    if (run.color) {
      expect(run.color).toMatch(/^(#[0-9a-fA-F]{6}|ansi256\(\d+\))$/)
    }

    if (run.backgroundColor) {
      expect(run.backgroundColor).toMatch(/^(#[0-9a-fA-F]{6}|ansi256\(\d+\))$/)
    }
  }
}

describe('heatmap robustness (malformed agent input)', () => {
  it('ragged + non-numeric matrix → no NaN color, width-safe', () => {
    const matrix = [
      [1, -1, 0.5],
      [0.2, Number.NaN], // short row + NaN
      [-0.3, 0.7, null as unknown as number, 9]
    ]

    const r = renderHeatmap({ diverging: true, matrix }, ctx())
    noBadColor([...r.rows, ...(r.legend ?? [])])
    widthSafe(r.rows, 60)
  })

  it('wide-char (CJK/emoji) row labels do not desync the gutter', () => {
    const r = renderHeatmap(
      { matrix: [[1, 0], [0, 1]], rowLabels: ['日本語ロング', '😀emoji'] },
      ctx({ colorMode: '256' }, 40)
    )

    noBadColor(r.rows)
    widthSafe(r.rows, 40)
    gutterAligned(r.rows)
  })

  it('256-color diverging: extreme + and - map to distinct colors (sign survives)', () => {
    const r = renderHeatmap({ diverging: true, matrix: [[1, -1]] }, ctx({ colorMode: '256' }, 24))
    const colors = r.rows.flat().flatMap(x => [x.color, x.backgroundColor]).filter(Boolean)
    expect(new Set(colors).size).toBeGreaterThanOrEqual(2) // +1 and -1 are not merged
  })
})

describe('fan robustness (malformed agent input)', () => {
  it('null band arrays do not crash', () => {
    const median = [0.4, 0.5, 0.6]
    const bands = [{ lower: null as unknown as number[], upper: undefined as unknown as number[] }]
    const r = renderFan({ bands, median }, ctx())
    expect(Array.isArray(r.rows)).toBe(true)
    widthSafe(r.rows, 60)
  })

  it('paths present but all non-numeric → does not crash', () => {
    const median = [0.4, 0.5, 0.6]
    const paths = [[Number.NaN, Number.NaN, Number.NaN]]
    const r = renderFan({ median, paths }, ctx())
    expect(Array.isArray(r.rows)).toBe(true)
    widthSafe(r.rows, 60)
  })
})
