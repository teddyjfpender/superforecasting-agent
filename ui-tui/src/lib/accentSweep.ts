import type { Theme } from '../theme.js'

// A subtle "alive" micro-interaction (inspired by the Gemini CLI's responding
// spinner): while the agent is working, the prominent spinner glyph smoothly
// sweeps its colour through the brand accent family. Pure + tick-driven so it
// piggybacks an existing animation timer — no extra interval, no re-render churn.

const HEX = /^#?([0-9a-fA-F]{6})$/

function rgb(hex: string): [number, number, number] | null {
  const m = HEX.exec(hex.trim())

  if (!m) {
    return null
  }

  const n = parseInt(m[1]!, 16)

  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function mix(a: string, b: string, t: number): null | string {
  const pa = rgb(a)
  const pb = rgb(b)

  if (!pa || !pb) {
    return null
  }

  const ch = (i: 0 | 1 | 2) => Math.max(0, Math.min(255, Math.round(pa[i] + (pb[i] - pa[i]) * t)))

  return `#${ch(0).toString(16).padStart(2, '0')}${ch(1).toString(16).padStart(2, '0')}${ch(2).toString(16).padStart(2, '0')}`
}

// The accent family the spinner cycles through: brand accent → info → ok → warn
// → error → back. Cohesive because they are the theme's own accents.
export function sweepStops(t: Theme): string[] {
  return [t.color.accent, t.color.info, t.color.ok, t.color.warn, t.color.error]
}

const TICKS_PER_STOP = 6

// Interpolate a colour across `stops` as `tick` advances, looping smoothly. Falls
// back to the nearest stop if any stop is non-hex (e.g. ansi256 on legacy
// terminals), so the spinner never breaks — it just stops sweeping.
export function sweepColor(stops: string[], tick: number): string {
  if (stops.length === 0) {
    return '#FFFFFF'
  }

  if (stops.length === 1) {
    return stops[0]!
  }

  const period = stops.length * TICKS_PER_STOP
  const pos = (((tick % period) + period) % period) / TICKS_PER_STOP
  const i = Math.floor(pos) % stops.length
  const f = pos - Math.floor(pos)

  return mix(stops[i]!, stops[(i + 1) % stops.length]!, f) ?? stops[i]!
}
