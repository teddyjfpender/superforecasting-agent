// Sub-cell block-glyph families for rendering a bitmap into terminal cells at
// higher-than-one-pixel-per-cell resolution.
//
// A terminal can only place one character per cell, so to make "pixels" smaller
// we pack more sub-pixels into each cell using Unicode block glyphs. Each family
// divides a cell into a (cellW x cellH) grid of sub-pixels; a glyph paints an
// arbitrary subset (the "mask") in the foreground colour and the rest in the
// background colour. More sub-pixels per cell = higher spatial resolution, at
// the cost of newer-font glyph coverage.
//
// Bit convention (shared by every family): bit index = row * cellW + col, with
// row 0 = top and col 0 = left. So a mask is an integer in [0, 2^(cellW*cellH)).

export type GlyphFamily = 'half' | 'quad' | 'sextant' | 'octant'

export interface GlyphTable {
  cellH: number
  cellW: number
  // glyphs[mask] -> the character painting exactly that sub-pixel subset as fg.
  glyphs: string[]
}

// 1x2 — the classic upper-half block. Universal support; only doubles vertical
// resolution (one pixel per cell horizontally). bit0 = top, bit1 = bottom.
const HALF: string[] = [' ', '▀', '▄', '█']

// 2x2 — quadrant blocks (Block Elements, universal). bit0=TL bit1=TR bit2=BL bit3=BR.
const QUAD: string[] = [
  ' ', '▘', '▝', '▀', '▖', '▌', '▞', '▛',
  '▗', '▚', '▐', '▜', '▄', '▙', '▟', '█'
]

// 2x3 — sextants (U+1FB00 "Symbols for Legacy Computing", Unicode 13, 2020).
// The 60 new code points are assigned in increasing mask value, skipping the
// four masks that already had glyphs: 0=blank, 21=left half (▌), 42=right half
// (▐), 63=full (█).
const buildSextant = (): string[] => {
  const g = new Array<string>(64)
  let idx = 0

  for (let v = 0; v < 64; v++) {
    if (v === 0) {
      g[v] = ' '
    } else if (v === 21) {
      g[v] = '▌'
    } else if (v === 42) {
      g[v] = '▐'
    } else if (v === 63) {
      g[v] = '█'
    } else {
      g[v] = String.fromCodePoint(0x1fb00 + idx)
      idx++
    }
  }

  return g
}

// 2x4 — octants (U+1CD00 "Symbols for Legacy Computing Supplement", Unicode 16,
// 2024). True half-size square sub-pixels, but the newest glyphs of the set —
// older fonts render tofu. The 236 new code points are assigned in increasing
// mask value, skipping the 20 masks that already had glyphs (verified against
// the Unicode character database): the 16 quadrant-family rectangles plus the
// four full-width quarter-height bands.
const buildOctant = (): string[] => {
  // mask -> pre-existing character (bit0=r0c0 … bit7=r3c1).
  const reused: Record<number, string> = {
    0x00: ' ',
    0x03: '🮂', // upper one quarter (rows 0)
    0x05: '▘', // quadrant UL
    0x0a: '▝', // quadrant UR
    0x0f: '▀', // upper half (rows 0-1)
    0x3f: '🮅', // upper three quarters (rows 0-2)
    0x50: '▖', // quadrant LL
    0x55: '▌', // left half
    0x5a: '▞', // UR + LL
    0x5f: '▛', // UL + UR + LL
    0xa0: '▗', // quadrant LR
    0xa5: '▚', // UL + LR
    0xaa: '▐', // right half
    0xaf: '▜', // UL + UR + LR
    0xc0: '▂', // lower one quarter (row 3)
    0xf0: '▄', // lower half (rows 2-3)
    0xf5: '▙', // UL + LL + LR
    0xfa: '▟', // UR + LL + LR
    0xfc: '▆', // lower three quarters (rows 1-3)
    0xff: '█' // full
  }

  const g = new Array<string>(256)
  let idx = 0

  for (let v = 0; v < 256; v++) {
    if (v in reused) {
      g[v] = reused[v]!
    } else {
      g[v] = String.fromCodePoint(0x1cd00 + idx)
      idx++
    }
  }

  return g
}

const TABLES: Record<GlyphFamily, GlyphTable> = {
  half: { cellH: 2, cellW: 1, glyphs: HALF },
  octant: { cellH: 4, cellW: 2, glyphs: buildOctant() },
  quad: { cellH: 2, cellW: 2, glyphs: QUAD },
  sextant: { cellH: 3, cellW: 2, glyphs: buildSextant() }
}

export const glyphTable = (family: GlyphFamily): GlyphTable => TABLES[family]
