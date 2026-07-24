import type { Theme } from '../theme.js'

// A small, intentional semantic layer over the raw theme tokens so the
// data-dense views (Markets, News, Messaging) speak in ROLES — direction,
// heading, subtle, rule, selection, badge — instead of reaching for
// ok/error/info/accent ad hoc. Everything is DERIVED from the active theme, so
// it tracks light/dark and every skin automatically; there is no second
// palette to keep in sync.

export interface Semantics {
  badge: string // tags / chips (provider, category, recency)
  cursor: string // selected-row marker / focus
  down: string // negative / loss
  faint: string // tertiary text, placeholders, empty cells
  flat: string // unchanged / not-applicable
  heading: string // column + section headers
  rule: string // dividers and separators
  selectionFg: string // text on the selected row
  star: string // watchlisted / starred
  subtle: string // secondary text
  up: string // positive / gain
}

// ── Column packing ─────────────────────────────────────────────────────────
// The shared primitive behind every dense table (Markets, Desk): clip-or-pad a
// cell value to an exact width on the chosen side, with an ellipsis when it
// overflows. Null-safe — a malformed series (missing field) must never crash a
// render, so nullish becomes an empty cell.
export const pad = (value: null | string | undefined, width: number, align: 'left' | 'right'): string => {
  const s = value == null ? '' : String(value)
  const v = s.length > width ? `${s.slice(0, Math.max(0, width - 1))}…` : s

  return align === 'right' ? v.padStart(width) : v.padEnd(width)
}

export const semantics = (t: Theme): Semantics => ({
  badge: t.color.info,
  cursor: t.color.accent,
  down: t.color.error,
  faint: t.color.border,
  flat: t.color.muted,
  heading: t.color.label,
  rule: t.color.border,
  selectionFg: t.color.text,
  star: t.color.warn,
  subtle: t.color.muted,
  up: t.color.ok
})

// ── Dual-encoded direction ────────────────────────────────────────────────
// Direction is carried by a glyph + sign (colour-blind + light-mode safe) AND
// reinforced by colour. Use both together: <Text color={dirColor(s,v)}>{dirGlyph(v)} {pct}</Text>

export type Direction = 'down' | 'flat' | 'up'

export const direction = (v: null | number | undefined): Direction =>
  v === null || v === undefined || v === 0 ? 'flat' : v > 0 ? 'up' : 'down'

// ▲/▼ are width-1 in standard terminal fonts; '·' for flat/unknown.
export const dirGlyph = (v: null | number | undefined): string => {
  const d = direction(v)

  return d === 'up' ? '▲' : d === 'down' ? '▼' : '·'
}

export const dirColor = (s: Semantics, v: null | number | undefined): string => {
  const d = direction(v)

  return d === 'up' ? s.up : d === 'down' ? s.down : s.flat
}

// ── Machine-readiness band colour ─────────────────────────────────────────────
// The 0-100 question machine-readiness composite (the RDY desk column, the summary
// readiness block, the settings-modal READINESS section) reads by BAND: ≥80 healthy
// (ok), 50-79 partial (warn), <50 under-fuelled (danger). A null/non-finite score
// (no composite — a benchmark/market question) paints subtle so it never fakes a band.
export const readinessColor = (t: Theme, score: null | number | undefined): string => {
  if (score === null || score === undefined || !Number.isFinite(score)) {
    return t.color.muted
  }

  return score >= 80 ? t.color.ok : score >= 50 ? t.color.warn : t.color.error
}

// ── Theme-aware QR colours ─────────────────────────────────────────────────
// A QR must always be dark modules on a light field to scan reliably. Pick the
// lightest / darkest of the theme's candidate colours by luminance so it stays
// on-theme yet correct in BOTH light and dark mode (the old code hard-mapped
// text→bg / statusBg→fg, which inverts under a light theme).

const parseHex = (h: string): [number, number, number] | null => {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(h.trim())

  if (!m) {
    return null
  }

  let hex = m[1]

  if (hex.length === 3) {
    hex = hex
      .split('')
      .map(c => c + c)
      .join('')
  }

  const n = parseInt(hex, 16)

  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff]
}

const channel = (c: number): number => {
  const s = c / 255

  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
}

export const relLuminance = (hex: string): null | number => {
  const rgb = parseHex(hex)

  if (!rgb) {
    return null
  }

  return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2])
}

const QR_LIGHT = '#f5f5f5'
const QR_DARK = '#1a1a2e'

export const qrColors = (t: Theme): { bg: string; fg: string } => {
  const scored = [t.color.text, t.color.statusBg, t.color.completionBg]
    .map(c => ({ c, l: relLuminance(c) }))
    .filter((x): x is { c: string; l: number } => x.l !== null)

  if (scored.length < 2) {
    return { bg: QR_LIGHT, fg: QR_DARK }
  }

  const lightest = scored.reduce((a, b) => (b.l > a.l ? b : a))
  const darkest = scored.reduce((a, b) => (b.l < a.l ? b : a))

  // Guard against a low-contrast pick (e.g. two mid greys): fall back to fixed.
  if (lightest.l - darkest.l < 0.4) {
    return { bg: QR_LIGHT, fg: QR_DARK }
  }

  return { bg: lightest.c, fg: darkest.c }
}
