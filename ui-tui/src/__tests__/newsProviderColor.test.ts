import { describe, expect, it } from 'vitest'

import {
  autoProviderColor,
  hashName,
  nextProviderColor,
  PROVIDER_HUES_DARK,
  PROVIDER_HUES_LIGHT,
  providerColor,
  providerPalette
} from '../lib/newsProviderColor.js'
import { DARK_THEME, LIGHT_THEME } from '../theme.js'

describe('newsProviderColor', () => {
  it('hashes a name deterministically (padding/case-insensitive)', () => {
    expect(hashName('nws')).toBe(hashName('nws'))
    expect(autoProviderColor('NWS  ', DARK_THEME)).toBe(autoProviderColor('nws', DARK_THEME))
  })

  it('different providers usually get different hues', () => {
    const names = ['NWS', 'NHC', 'Reuters', 'Bloomberg', 'arXiv', 'Hacker News']
    const colors = names.map(n => autoProviderColor(n, DARK_THEME))
    // at least most are distinct (palette has 12 hues)
    expect(new Set(colors).size).toBeGreaterThanOrEqual(names.length - 1)
  })

  it('picks the dark palette on a dark theme and light on a light theme', () => {
    expect(PROVIDER_HUES_DARK).toContain(autoProviderColor('Reuters', DARK_THEME))
    expect(PROVIDER_HUES_LIGHT).toContain(autoProviderColor('Reuters', LIGHT_THEME))
    expect(providerPalette(DARK_THEME)).toBe(PROVIDER_HUES_DARK)
    expect(providerPalette(LIGHT_THEME)).toBe(PROVIDER_HUES_LIGHT)
  })

  it('a user override wins over the hash', () => {
    expect(providerColor('NWS', DARK_THEME, { nws: '#123456' })).toBe('#123456')
    expect(providerColor('NWS', DARK_THEME, {})).toBe(autoProviderColor('NWS', DARK_THEME))
  })

  it('cycling advances through the palette and wraps', () => {
    const palette = PROVIDER_HUES_DARK
    const a = autoProviderColor('NWS', DARK_THEME)
    const b = nextProviderColor('NWS', DARK_THEME, a)
    expect(palette.indexOf(b)).toBe((palette.indexOf(a) + 1) % palette.length)
    // wraps from the last hue back to the first
    expect(nextProviderColor('NWS', DARK_THEME, palette[palette.length - 1])).toBe(palette[0])
  })
})
