import { Box, Text, useStdout } from '@superforecasting/ink'
import { useMemo } from 'react'

import { OUTRIDER_HEADER } from '../content/outriderHeader.js'
import { type GlyphFamily, glyphTable } from '../lib/subcellGlyphs.js'
import { BRAND_GRADIENT, BRAND_GRADIENT_LIGHT, detectLightMode, type Theme } from '../theme.js'

// Off-switch: any TUI alias triple set falsey disables the desk header.
const DISABLED = (() => {
  for (const key of [
    'SUPERFORECASTING_AGENT_TUI_DESK_ANIMATION',
    'FORECAST_TUI_DESK_ANIMATION',
    'HERMES_TUI_DESK_ANIMATION'
  ]) {
    const v = (process.env[key] ?? '').trim().toLowerCase()

    if (v === '0' || v === 'off' || v === 'false' || v === 'no') {
      return true
    }
  }

  return false
})()

// Glyph family controls how many sub-pixels we pack per terminal cell — i.e.
// how small the "pixels" are. Finer glyphs = sharper, but need newer fonts:
//   octant  (2x4) — sharpest (true half-size square pixels), Unicode 16 (2024).
//                   Many fonts ship it only PARTIALLY, so a few cells tofu.
//   sextant (2x3) — ~3x the detail of half, Unicode 13 (2020), mature/complete
//                   coverage in modern coding fonts. The compat-first default.
//   quad    (2x2) — classic Block Elements, universal, 2x horizontal only.
//   half    (1x2) — the original look.
// Override with ..._TUI_HEADER_GLYPHS=octant (etc.) if your font is complete.
const GLYPH_FAMILY: GlyphFamily = (() => {
  for (const key of [
    'SUPERFORECASTING_AGENT_TUI_HEADER_GLYPHS',
    'FORECAST_TUI_HEADER_GLYPHS',
    'HERMES_TUI_HEADER_GLYPHS'
  ]) {
    const v = (process.env[key] ?? '').trim().toLowerCase()

    if (v === 'half' || v === 'quad' || v === 'sextant' || v === 'octant') {
      return v
    }
  }

  return 'sextant'
})()

// Luminance below this (0-255) renders transparent, so the figure floats on
// the terminal background in any theme.
const THRESHOLD = 22
const MAX_WIDTH = 96 // cap so the hero never dominates a very wide terminal

// Decode the base64 luminance rows once at module load.
const NATIVE_W = OUTRIDER_HEADER.w
const NATIVE_H = OUTRIDER_HEADER.h
const ASPECT = NATIVE_H / NATIVE_W
const LUM: Uint8Array[] = OUTRIDER_HEADER.rows.map(r => Uint8Array.from(Buffer.from(r, 'base64')))

const parseHex = (hex: string): [number, number, number] => {
  const m = /^#?([0-9a-fA-F]{6})$/.exec(hex.trim())

  if (!m) {
    return [255, 255, 255]
  }

  const n = parseInt(m[1]!, 16)

  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

const toHex = (r: number, g: number, b: number): string => {
  const c = (v: number) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')

  return `#${c(r)}${c(g)}${c(b)}`
}

// 256-entry ramp from a theme hue: dark→hue for shadows/mids, hue→white for
// the brightest highlights — so the figure glows in whatever colour the theme
// uses for `primary`.
const buildRamp = (hue: [number, number, number]): string[] => {
  const [pr, pg, pb] = hue
  const ramp: string[] = []

  for (let l = 0; l < 256; l++) {
    const t = l / 255

    if (t < 0.8) {
      const k = t / 0.8
      ramp.push(toHex(pr * k, pg * k, pb * k))
    } else {
      const k = (t - 0.8) / 0.2
      ramp.push(toHex(pr + (255 - pr) * k, pg + (255 - pg) * k, pb + (255 - pb) * k))
    }
  }

  return ramp
}

// Brand gradient stops parsed once. `gradientAt(frac)` linearly interpolates
// the blue→purple→pink ramp at a 0..1 horizontal position, so the hero's hue
// sweeps across the figure (each column gets its own luminance ramp built from
// its gradient colour).
// On a LIGHT terminal the figure floats on white, so use the saturated
// light-mode gradient (the pastel dark gradient would wash out). Resolved once
// at module load, matching how theme.ts derives DEFAULT_LIGHT_MODE.
const GRAD_STOPS: [number, number, number][] = (detectLightMode() ? BRAND_GRADIENT_LIGHT : BRAND_GRADIENT).map(parseHex)

const gradientAt = (frac: number): [number, number, number] => {
  const segs = GRAD_STOPS.length - 1

  if (segs <= 0) {
    return GRAD_STOPS[0] ?? [255, 255, 255]
  }

  const pos = Math.max(0, Math.min(1, frac)) * segs
  const i = Math.min(segs - 1, Math.floor(pos))
  const f = pos - i
  const a = GRAD_STOPS[i]!
  const b = GRAD_STOPS[i + 1]!

  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f]
}

interface Span {
  b?: string
  c?: string
  t: string
}

// A theme-tinted, resolution-scaled sub-cell render of the outrider art.
//
// The stored bitmap is high-res luminance. We downscale (box-average) it to a
// sub-pixel grid sized to the chosen glyph family (cellW x cellH per cell),
// then for each cell pick the glyph + 2 colours that best approximate its
// sub-pixels: an optimal 1-D two-means split partitions the sub-pixels into a
// bright (foreground) group and a dim (background) group, and the glyph whose
// mask matches the bright group is drawn. Dim groups below THRESHOLD render
// transparent so the figure floats on the terminal background in any theme.
export function OutriderHeader({ maxCols }: { maxCols?: number; t?: Theme }) {
  const out = useStdout().stdout
  // Bound the orb by the available column (the two-pane Home gives it less than
  // the full terminal), not the whole terminal — otherwise it overflows the
  // conversation column and clobbers the rail.
  const cols = Math.min(out?.columns ?? 80, maxCols ?? out?.columns ?? 80)
  const termRows = out?.rows ?? 24

  const lines = useMemo(() => {
    const { cellW, cellH, glyphs } = glyphTable(GLYPH_FAMILY)

    // Fit both axes without distortion. A terminal cell is ~1 wide x 2 tall, so
    // the rendered aspect depends on both the image aspect AND the cell shape:
    // sub-pixel width = cellPxW/cellW, sub-pixel height = cellPxH/cellH, with
    // cellPxH/cellPxW = CELL_ASPECT (~2). Working that through, the cell-grid
    // ratio is independent of the glyph family: outRows = outCols * ASPECT /
    // CELL_ASPECT. (For half/octant cellH = 2*cellW so this matched the old
    // formula; for sextant/quad it did not — the figure stretched vertically.)
    const CELL_ASPECT = 2
    const rowsPerCol = ASPECT / CELL_ASPECT
    // Width is bounded by the terminal (capped) AND by the rows left after the
    // wordmark/hints (~7) so the hero never pushes the prompt off.
    const rowBudget = Math.max(8, termRows - 7)
    const colsFromRows = Math.floor(rowBudget / rowsPerCol)
    const outCols = Math.max(40, Math.min(MAX_WIDTH, colsFromRows, cols - 2))
    const outRows = Math.max(1, Math.round(outCols * rowsPerCol))

    const subW = outCols * cellW
    const subH = outRows * cellH

    // One luminance ramp per column, each built from the brand gradient's colour
    // at that horizontal position — so the hero sweeps blue → purple → pink.
    const ramps = Array.from({ length: outCols }, (_, cx) =>
      buildRamp(gradientAt(outCols <= 1 ? 0 : cx / (outCols - 1)))
    )

    // Box-average the native luminance grid for sub-pixel (sx, sy); below
    // THRESHOLD reads as 0 (transparent black) so edges stay crisp.
    const sample = (sx: number, sy: number): number => {
      const x0 = Math.floor((sx * NATIVE_W) / subW)
      const x1 = Math.max(x0 + 1, Math.floor(((sx + 1) * NATIVE_W) / subW))
      const y0 = Math.floor((sy * NATIVE_H) / subH)
      const y1 = Math.max(y0 + 1, Math.floor(((sy + 1) * NATIVE_H) / subH))
      let sum = 0
      let n = 0

      for (let y = y0; y < y1 && y < NATIVE_H; y++) {
        const row = LUM[y]!

        for (let x = x0; x < x1 && x < NATIVE_W; x++) {
          sum += row[x]!
          n++
        }
      }

      const avg = n ? sum / n : 0

      return avg >= THRESHOLD ? avg : 0
    }

    const N = cellW * cellH
    const result: Span[][] = []

    for (let ry = 0; ry < outRows; ry++) {
      const spans: Span[] = []

      const push = (ch: string, c?: string, b?: string) => {
        const last = spans[spans.length - 1]

        if (last && last.t[0] === ch && last.c === c && last.b === b) {
          last.t += ch
        } else {
          spans.push({ b, c, t: ch })
        }
      }

      for (let cx = 0; cx < outCols; cx++) {
        // Gather this cell's sub-pixel luminances (bit index = row*cellW+col).
        const sub: number[] = []
        let total = 0

        for (let dy = 0; dy < cellH; dy++) {
          for (let dx = 0; dx < cellW; dx++) {
            const v = sample(cx * cellW + dx, ry * cellH + dy)
            sub.push(v)
            total += v
          }
        }

        if (total === 0) {
          push(' ')

          continue
        }

        // Optimal two-means split: sort sub-pixels, then try every cut point.
        // The brighter tail becomes the foreground group; everything below the
        // cut is background. Minimises within-group variance in O(N log N).
        const order = sub.map((_, i) => i).sort((a, b) => sub[a]! - sub[b]!)
        let sumsq = 0

        for (const v of sub) {
          sumsq += v * v
        }

        let bgSum = 0
        let bestK = 0
        let bestErr = Infinity

        for (let k = 0; k <= N; k++) {
          const fgSum = total - bgSum
          const bgMean = k ? bgSum / k : 0
          const fgMean = k < N ? fgSum / (N - k) : 0
          const err = sumsq - bgMean * bgSum - fgMean * fgSum

          if (err < bestErr - 1e-6) {
            bestErr = err
            bestK = k
          }

          if (k < N) {
            bgSum += sub[order[k]!]!
          }
        }

        // Build the foreground mask (sub-pixels order[bestK..N-1]) and means.
        let mask = 0
        let fgSum = 0

        for (let i = bestK; i < N; i++) {
          mask |= 1 << order[i]!
          fgSum += sub[order[i]!]!
        }

        const fgCount = N - bestK
        const fgMean = fgCount ? fgSum / fgCount : 0
        const bgCount = bestK
        const bgMean = bgCount ? (total - fgSum) / bgCount : 0

        if (fgMean < THRESHOLD) {
          push(' ')

          continue
        }

        const ramp = ramps[cx]!
        const fg = ramp[Math.round(fgMean)]
        const bg = bgMean >= THRESHOLD ? ramp[Math.round(bgMean)] : undefined
        push(glyphs[mask]!, fg, bg)
      }

      result.push(spans)
    }

    return result
  }, [cols, termRows])

  if (DISABLED) {
    return null
  }

  return (
    <Box flexDirection="column">
      {lines.map((spans, y) => (
        <Text key={y} wrap="truncate-end">
          {spans.map((sp, i) =>
            sp.c || sp.b ? (
              <Text backgroundColor={sp.b} color={sp.c} key={i}>
                {sp.t}
              </Text>
            ) : (
              <Text key={i}>{sp.t}</Text>
            )
          )}
        </Text>
      ))}
    </Box>
  )
}
