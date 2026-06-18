import { describe, expect, it } from 'vitest'

import { ICON, SPINNER, spinnerFrame, statusGlyph } from '../lib/icons.js'

describe('icon vocabulary', () => {
  it('every glyph is a single cell and not an emoji (no variation selector / surrogate)', () => {
    for (const g of [...Object.values(ICON), ...SPINNER]) {
      expect([...g]).toHaveLength(1) // one code point
      const code = g.codePointAt(0) as number
      expect(code).toBeLessThan(0x1f000) // below the emoji planes
      expect(g).not.toMatch(/️/u) // no emoji-presentation selector
    }
  })

  it('spinner cycles through its frames and wraps (incl. negative)', () => {
    expect(spinnerFrame(0)).toBe(SPINNER[0])
    expect(spinnerFrame(SPINNER.length)).toBe(SPINNER[0])
    expect(spinnerFrame(SPINNER.length + 1)).toBe(SPINNER[1])
    expect(spinnerFrame(-1)).toBe(SPINNER[SPINNER.length - 1])
  })

  it('status glyphs: live ● solid, idle ○ hollow, error ✗, busy animates', () => {
    expect(statusGlyph('live')).toBe('●')
    expect(statusGlyph('idle')).toBe('○')
    expect(statusGlyph('error')).toBe(ICON.fail)
    expect(statusGlyph('busy', 0)).toBe(SPINNER[0])
    expect(statusGlyph('busy', 2)).toBe(SPINNER[2])
  })
})
