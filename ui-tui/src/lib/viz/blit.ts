// Blitters: turn sub-cell pixels into width-1 terminal glyphs.
//
// Braille (2×4 dots, U+2800-28FF) is added here for sparse line/scatter (1 fg
// color/cell). The filled block families (half/quad/sextant/octant, 2 colors
// via fg+bg) already exist in subcellGlyphs.ts; we reuse them for areas/heatmaps.

import { glyphTable } from '../subcellGlyphs.js'

// Dot-bit value per (row, col) in a braille cell. row0=top, col0=left.
// Unicode braille numbers dots 1-8; these are their bit values laid out 2×4.
export const BRAILLE_BIT: number[][] = [
  [0x01, 0x08],
  [0x02, 0x10],
  [0x04, 0x20],
  [0x40, 0x80]
]
const BRAILLE_BASE = 0x2800

export const brailleChar = (mask: number): string => String.fromCodePoint(BRAILLE_BASE + (mask & 0xff))

// A monochrome braille canvas: a (cols*2) × (rows*4) dot grid, compiled to one
// braille glyph per cell. The caller applies a single fg color per cell.
export class BrailleCanvas {
  readonly dotH: number
  readonly dotW: number
  private readonly masks: Uint8Array

  constructor(readonly cols: number, readonly rows: number) {
    this.dotW = cols * 2
    this.dotH = rows * 4
    this.masks = new Uint8Array(cols * rows)
  }

  // Set the dot at sub-pixel (sx, sy); out-of-range is ignored (clipping).
  plot(sx: number, sy: number): void {
    if (sx < 0 || sy < 0 || sx >= this.dotW || sy >= this.dotH) {
      return
    }

    const cx = sx >> 1
    const cy = sy >> 2
    this.masks[cy * this.cols + cx]! |= BRAILLE_BIT[sy & 3]![sx & 1]!
  }

  // Bresenham line in dot space.
  line(x0: number, y0: number, x1: number, y1: number): void {
    let [ax, ay] = [Math.round(x0), Math.round(y0)]
    const [bx, by] = [Math.round(x1), Math.round(y1)]
    const dx = Math.abs(bx - ax)
    const dy = -Math.abs(by - ay)
    const sx = ax < bx ? 1 : -1
    const sy = ay < by ? 1 : -1
    let err = dx + dy

    for (;;) {
      this.plot(ax, ay)

      if (ax === bx && ay === by) {
        break
      }

      const e2 = 2 * err

      if (e2 >= dy) {
        err += dy
        ax += sx
      }

      if (e2 <= dx) {
        err += dx
        ay += sy
      }
    }
  }

  maskAt(col: number, row: number): number {
    return this.masks[row * this.cols + col] ?? 0
  }
}

// A half-block fill canvas: a (cols) × (rows*2) grid of colored sub-pixels that
// compiles to one ▀/▄/█ glyph per cell (2× vertical resolution, fg=top sub-row,
// bg=bottom sub-row). The smooth-edged workhorse for areas/cones/candle bodies.
export class SubRowCanvas {
  readonly subH: number
  private readonly colors: (string | undefined)[]

  constructor(readonly cols: number, readonly rows: number) {
    this.subH = rows * 2
    this.colors = new Array<string | undefined>(cols * this.subH).fill(undefined)
  }

  set(c: number, sr: number, color: string): void {
    if (c < 0 || sr < 0 || c >= this.cols || sr >= this.subH) {
      return
    }

    this.colors[sr * this.cols + c] = color
  }

  // Fill the inclusive sub-row span [srTop, srBot] of column c.
  fillCol(c: number, srTop: number, srBot: number, color: string): void {
    const a = Math.max(0, Math.min(srTop, srBot))
    const b = Math.min(this.subH - 1, Math.max(srTop, srBot))

    for (let sr = a; sr <= b; sr++) {
      this.set(c, sr, color)
    }
  }

  colorAt(c: number, sr: number): string | undefined {
    if (c < 0 || sr < 0 || c >= this.cols || sr >= this.subH) {
      return undefined
    }

    return this.colors[sr * this.cols + c]
  }

  // The compiled half-block glyph + style for terminal cell (c, r).
  cell(c: number, r: number): { backgroundColor?: string; color?: string; text: string } {
    return halfBlock(this.colorAt(c, r * 2), this.colorAt(c, r * 2 + 1))
  }
}

// Upper-half-block cell: paints the top sub-pixel via fg and bottom via bg, so a
// single cell shows two vertically-stacked truecolor pixels. Either may be
// undefined (transparent → terminal background).
export const halfBlock = (top?: string, bottom?: string): { backgroundColor?: string; color?: string; text: string } => {
  if (!top && !bottom) {
    return { text: ' ' }
  }

  if (top && !bottom) {
    return { color: top, text: '▀' }
  }

  if (!top && bottom) {
    return { color: bottom, text: '▄' }
  }

  return { backgroundColor: bottom, color: top, text: '▀' }
}

// Eighth-block vertical bar fill level (0..8) → glyph (for bar charts / gauges).
const EIGHTHS = [' ', '▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'] as const
export const eighthBlock = (level0to8: number): string =>
  EIGHTHS[Math.max(0, Math.min(8, Math.round(level0to8)))]!

// Re-export the existing filled-glyph tables for areas/quadrant fallbacks.
export { glyphTable }
