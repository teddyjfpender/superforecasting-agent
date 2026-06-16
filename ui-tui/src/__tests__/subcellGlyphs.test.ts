import { describe, expect, it } from 'vitest'

import { glyphTable } from '../lib/subcellGlyphs.js'

describe('glyphTable', () => {
  it('exposes the right sub-cell dimensions per family', () => {
    expect(glyphTable('half')).toMatchObject({ cellW: 1, cellH: 2 })
    expect(glyphTable('quad')).toMatchObject({ cellW: 2, cellH: 2 })
    expect(glyphTable('sextant')).toMatchObject({ cellW: 2, cellH: 3 })
    expect(glyphTable('octant')).toMatchObject({ cellW: 2, cellH: 4 })
  })

  it('half/quad use the classic blocks', () => {
    expect(glyphTable('half').glyphs).toEqual([' ', '▀', '▄', '█'])
    const quad = glyphTable('quad').glyphs
    expect(quad).toHaveLength(16)
    expect(quad[0]).toBe(' ')
    expect(quad[3]).toBe('▀') // TL+TR = top
    expect(quad[5]).toBe('▌') // TL+BL = left
    expect(quad[15]).toBe('█')
  })

  it('sextant maps to U+1FB00 skipping pre-existing masks', () => {
    const g = glyphTable('sextant').glyphs
    expect(g).toHaveLength(64)
    expect(g[0]).toBe(' ')
    expect(g[21]).toBe('▌') // left column
    expect(g[42]).toBe('▐') // right column
    expect(g[63]).toBe('█')
    expect(g[1]).toBe(String.fromCodePoint(0x1fb00)) // BLOCK SEXTANT-1
  })

  it('octant maps to U+1CD00 skipping the 20 pre-existing masks', () => {
    const g = glyphTable('octant').glyphs
    expect(g).toHaveLength(256)
    // Reused (pre-existing) glyphs.
    expect(g[0x00]).toBe(' ')
    expect(g[0x0f]).toBe('▀') // upper half
    expect(g[0xf0]).toBe('▄') // lower half
    expect(g[0x55]).toBe('▌') // left half
    expect(g[0xaa]).toBe('▐') // right half
    expect(g[0xff]).toBe('█')
    expect(g[0x03]).toBe('🮂') // upper one quarter
    expect(g[0xc0]).toBe('▂') // lower one quarter
    // New octants: smallest non-reused mask 0x01 -> U+1CD00, then sequential.
    expect(g[0x01]).toBe(String.fromCodePoint(0x1cd00))
    expect(g[0x02]).toBe(String.fromCodePoint(0x1cd01))
    expect(g[0x04]).toBe(String.fromCodePoint(0x1cd02))
    // Exactly 236 new code points (256 - 20 reused), ending at U+1CDEB.
    const newGlyphs = g.filter(ch => ch.codePointAt(0)! >= 0x1cd00 && ch.codePointAt(0)! <= 0x1cdeb)
    expect(newGlyphs).toHaveLength(236)
  })
})
