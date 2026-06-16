import { Box, Text, useStdout } from '@hermes/ink'
import { useMemo } from 'react'

import { OUTRIDER_HEADER } from '../content/outriderHeader.js'
import type { Theme } from '../theme.js'

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

// Luminance below this (0-255) renders transparent, so the figure floats on
// the terminal background in any theme.
const THRESHOLD = 22
const MAX_WIDTH = 96 // cap so the hero never dominates a very wide terminal

// Decode the base64 luminance rows once at module load.
const NATIVE_W = OUTRIDER_HEADER.w
const NATIVE_H = OUTRIDER_HEADER.h
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

interface Span {
  b?: string
  c?: string
  t: string
}

// A theme-tinted, resolution-scaled half-block render of the outrider art.
// The stored bitmap is high-res luminance; we downscale (box-average) it to the
// width that fits the terminal, then tint each pixel through a theme-derived
// ramp. Two stacked pixels per cell via ▀/▄ for 2x vertical resolution.
export function OutriderHeader({ t }: { t: Theme }) {
  const out = useStdout().stdout
  const cols = out?.columns ?? 80
  const termRows = out?.rows ?? 24
  const primary = t.color.primary

  const lines = useMemo(() => {
    // Fit both axes: width to the terminal (capped), height to the rows left
    // after the wordmark/hints (~7) so the hero never pushes the prompt off.
    const maxWByRows = Math.max(40, (termRows - 7) * 5) // aspect ≈ 2.5 → rows ≈ width/5
    const targetW = Math.max(40, Math.min(MAX_WIDTH, maxWByRows, cols - 2))
    let targetH = Math.round((targetW * NATIVE_H) / NATIVE_W)

    if (targetH % 2) {
      targetH += 1
    }

    const rows = targetH / 2
    const ramp = buildRamp(parseHex(primary))

    // Box-average the native luminance grid for output pixel (tx, ty).
    const sample = (tx: number, ty: number): number => {
      const x0 = Math.floor((tx * NATIVE_W) / targetW)
      const x1 = Math.max(x0 + 1, Math.floor(((tx + 1) * NATIVE_W) / targetW))
      const y0 = Math.floor((ty * NATIVE_H) / targetH)
      const y1 = Math.max(y0 + 1, Math.floor(((ty + 1) * NATIVE_H) / targetH))
      let sum = 0
      let n = 0

      for (let y = y0; y < y1 && y < NATIVE_H; y++) {
        const row = LUM[y]!

        for (let x = x0; x < x1 && x < NATIVE_W; x++) {
          sum += row[x]!
          n++
        }
      }

      return n ? sum / n : 0
    }

    const result: Span[][] = []

    for (let ry = 0; ry < rows; ry++) {
      const spans: Span[] = []

      const push = (ch: string, c?: string, b?: string) => {
        const last = spans[spans.length - 1]

        if (last && last.t[0] === ch && last.c === c && last.b === b) {
          last.t += ch
        } else {
          spans.push({ b, c, t: ch })
        }
      }

      for (let x = 0; x < targetW; x++) {
        const top = sample(x, ry * 2)
        const bot = sample(x, ry * 2 + 1)
        const to = top >= THRESHOLD
        const bo = bot >= THRESHOLD

        if (to && bo) {
          push('▀', ramp[Math.round(top)], ramp[Math.round(bot)])
        } else if (to) {
          push('▀', ramp[Math.round(top)])
        } else if (bo) {
          push('▄', ramp[Math.round(bot)])
        } else {
          push(' ')
        }
      }

      result.push(spans)
    }

    return result
  }, [cols, termRows, primary])

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
