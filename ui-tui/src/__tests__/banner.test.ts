import { describe, expect, test } from 'vitest'

import { artWidth, FORECAST_HERO_WIDTH, forecastHero, logo, LOGO_WIDTH } from '../banner.js'
import type { ThemeColors } from '../theme.js'

const colors = {
  accent: '#d6b85a',
  border: '#3d7c6e',
  muted: '#63706c',
  primary: '#8fe3cf'
} as ThemeColors

const textOf = (lines: [string, string][]) => lines.map(([, text]) => text).join('\n')

describe('forecast desk banner art', () => {
  test('default logo is forecast-native', () => {
    const text = textOf(logo(colors))

    expect(text).toContain('SUPERFORECASTING AGENT')
    expect(text).toContain('CLI forecasting desk')
    expect(text).not.toContain('HERMES')
  })

  test('logo lines are equal width so the right border aligns', () => {
    const lines = logo(colors).map(([, text]) => text)
    expect(lines.length).toBe(4)
    const widths = new Set(lines.map(line => line.length))
    expect(widths).toEqual(new Set([LOGO_WIDTH]))
    // The right border glyph sits in the final column on every line.
    for (const line of lines) {
      expect(['┓', '┃', '┛']).toContain(line[line.length - 1])
    }
  })

  test('default hero is a forecast desk mark', () => {
    const text = textOf(forecastHero(colors))

    expect(text).toContain('probability')
    expect(text).toContain('ledger')
    expect(text).not.toContain('HERMES')
    expect(artWidth(forecastHero(colors))).toBe(FORECAST_HERO_WIDTH)
  })

  test('hero box rows are equal width with aligned column separators', () => {
    const lines = textOf(forecastHero(colors)).split('\n')
    // The box-drawing rows: top border, three cells, bottom border.
    const boxLines = lines.filter(line => /[┌│└]/.test(line))
    expect(boxLines.length).toBe(5)

    // Every box line is the same display width so the right edge is flush.
    const widths = new Set(boxLines.map(line => line.length))
    expect(widths.size).toBe(1)

    // The interior column rule lines up: ┬ / │ / ┴ sit at the same index on
    // every row (this is exactly what drifted before and broke the borders).
    const columnIndex = (line: string) => {
      const idx = [...line].findIndex((ch, i) => i > line.indexOf('│') && /[┬│┴]/.test(ch))
      return idx
    }
    const separatorColumns = new Set(boxLines.map(columnIndex))
    expect(separatorColumns.size).toBe(1)
  })
})
