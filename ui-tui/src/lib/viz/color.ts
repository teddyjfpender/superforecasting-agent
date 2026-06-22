// Color utilities for the viz engine: hex parsing, mixing, diverging/sequential
// colormaps, and the 256-color quantizer.
//
// Risk-3 guard (from the design): at 256-color depth we emit `ansi256(n)`
// STRINGS directly (colorize.ts passes these through untouched) rather than hex,
// so chalk's RGB→6×6×6-cube nearest-match can't merge adjacent heat buckets or
// HSL-snap the near-zero correlation midband to gray. Truecolor emits hex.

import type { ColorMode } from './types.js'

export type RGB = [number, number, number]

const clamp = (v: number, lo: number, hi: number): number => Math.max(lo, Math.min(hi, v))

export const parseHex = (hex: string): RGB => {
  const h = hex.replace('#', '')
  const n = h.length === 3 ? h.split('').map(c => c + c).join('') : h
  const int = parseInt(n || '000000', 16)

  return [(int >> 16) & 0xff, (int >> 8) & 0xff, int & 0xff]
}

export const toHex = (rgb: RGB): string =>
  `#${rgb.map(c => clamp(Math.round(c), 0, 255).toString(16).padStart(2, '0')).join('')}`

export const mix = (a: RGB, b: RGB, t: number): RGB => {
  const k = clamp(t, 0, 1)

  return [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k]
}

// Diverging colormap: neg ↔ mid ↔ pos, with t=0.5 = mid. For correlation
// matrices (blue ↔ neutral ↔ red), so sign reads at a glance.
export const diverging = (neg: string, mid: string, pos: string): ((t: number) => string) => {
  const n = parseHex(neg)
  const m = parseHex(mid)
  const p = parseHex(pos)

  return (t: number) => {
    const k = clamp(t, 0, 1)

    return toHex(k < 0.5 ? mix(n, m, k * 2) : mix(m, p, (k - 0.5) * 2))
  }
}

// Sequential colormap: lo → hi.
export const sequential = (lo: string, hi: string): ((t: number) => string) => {
  const a = parseHex(lo)
  const b = parseHex(hi)

  return (t: number) => toHex(mix(a, b, t))
}

// Standard xterm RGB → 256-color index (16-231 color cube + 232-255 grayscale).
export const rgbToAnsi256 = ([r, g, b]: RGB): number => {
  if (r === g && g === b) {
    if (r < 8) {
      return 16
    }

    if (r > 248) {
      return 231
    }

    return Math.round(((r - 8) / 247) * 24) + 232
  }

  const q = (c: number): number => Math.round((c / 255) * 5)

  return 16 + 36 * q(r) + 6 * q(g) + q(b)
}

// Quantize a hex color to the active depth's emit-string:
//   truecolor → hex (chalk emits 24-bit)
//   256       → 'ansi256(n)' (bypasses chalk's cube nearest-match — Risk 3)
//   16        → hex (chart should prefer the glyph-intensity path at 16; if a
//               color is still needed chalk maps it to the nearest basic color)
export const quantize = (hex: string, mode: ColorMode): string =>
  mode === '256' ? `ansi256(${rgbToAnsi256(parseHex(hex))})` : hex

// Glyph-intensity ramp for the 16-color heatmap fallback (no per-cell color):
// map t in [0,1] to a shade glyph. All width-1.
const INTENSITY = [' ', '░', '▒', '▓', '█'] as const

export const intensityGlyph = (t: number): string =>
  INTENSITY[clamp(Math.round(clamp(t, 0, 1) * (INTENSITY.length - 1)), 0, INTENSITY.length - 1)]!
