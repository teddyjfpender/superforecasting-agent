import { describe, expect, it } from 'vitest'

import { dirColor, direction, dirGlyph, qrColors, relLuminance, semantics } from '../lib/visualSemantics.js'
import { DARK_THEME, LIGHT_THEME } from '../theme.js'

// Local WCAG contrast so the test doesn't depend on theme internals.
const contrast = (a: number, b: number): number => {
  const hi = Math.max(a, b)
  const lo = Math.min(a, b)

  return (hi + 0.05) / (lo + 0.05)
}

describe('direction (dual-encoded)', () => {
  it('classifies up / down / flat by sign', () => {
    expect(direction(1.2)).toBe('up')
    expect(direction(-0.3)).toBe('down')
    expect(direction(0)).toBe('flat')
    expect(direction(null)).toBe('flat')
  })

  it('glyph carries direction independent of colour', () => {
    expect(dirGlyph(1)).toBe('▲')
    expect(dirGlyph(-1)).toBe('▼')
    expect(dirGlyph(0)).toBe('·')
  })

  it('colour reinforces direction', () => {
    const s = semantics(DARK_THEME)
    expect(dirColor(s, 1)).toBe(s.up)
    expect(dirColor(s, -1)).toBe(s.down)
    expect(dirColor(s, 0)).toBe(s.flat)
  })
})

describe('semantic legibility', () => {
  for (const [name, theme, bgLum] of [
    ['dark', DARK_THEME, 0],
    ['light', LIGHT_THEME, 1]
  ] as const) {
    it(`${name}: up/down are distinct and legible against the ${name} field`, () => {
      const s = semantics(theme)
      expect(s.up).not.toBe(s.down)
      const up = relLuminance(s.up)
      const down = relLuminance(s.down)
      expect(up).not.toBeNull()
      expect(down).not.toBeNull()
      // each reads against the terminal background (≥ 2.3:1 — terminal text floor)
      expect(contrast(up as number, bgLum)).toBeGreaterThan(2.3)
      expect(contrast(down as number, bgLum)).toBeGreaterThan(2.3)
    })

    it(`${name}: headings/subtle text clear the background`, () => {
      const s = semantics(theme)

      for (const role of [s.heading, s.subtle]) {
        const l = relLuminance(role)

        if (l !== null) {
          expect(contrast(l, bgLum)).toBeGreaterThan(2.0)
        }
      }
    })
  }
})

describe('qrColors', () => {
  for (const [name, theme] of [
    ['dark', DARK_THEME],
    ['light', LIGHT_THEME]
  ] as const) {
    it(`${name}: always picks a light field + dark modules (scannable)`, () => {
      const { bg, fg } = qrColors(theme)
      const lb = relLuminance(bg)
      const lf = relLuminance(fg)
      expect(lb).not.toBeNull()
      expect(lf).not.toBeNull()
      expect(lb as number).toBeGreaterThan(lf as number) // bg lighter than modules
      expect(contrast(lb as number, lf as number)).toBeGreaterThan(4) // comfortably scannable
    })
  }
})
