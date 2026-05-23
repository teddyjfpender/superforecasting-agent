import { describe, expect, test } from 'vitest'

import { forecastHero, logo } from '../banner.js'
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

  test('default hero is a forecast desk mark', () => {
    const text = textOf(forecastHero(colors))

    expect(text).toContain('probability')
    expect(text).toContain('ledger')
    expect(text).not.toContain('HERMES')
  })
})
