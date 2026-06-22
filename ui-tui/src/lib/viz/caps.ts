// Terminal capability resolution + blitter selection — SYNC, no async probe in
// v1 (env heuristic mirroring chalk/supports-color + the fork's colorize logic).
//
// blitterMax defaults to 'quad' (ubiquitous Block Elements, verified width-1).
// HERMES_VIZ_BLITTER is the load-bearing override (the only reliable font-coverage
// signal over a pty). A terminal-identity heuristic may raise the ceiling to
// 'braille' only — never to sextant/octant (Unicode-13/16 font-tofu risk).

import type { Blitter, ChartKind, ColorMode, ImageProtocol, TerminalCaps } from './types.js'

const env = (k: string): string => process.env[k] ?? ''

const resolveColorMode = (): ColorMode => {
  if (env('NO_COLOR') || env('FORCE_COLOR') === '0') {
    return '16'
  }

  const colorterm = env('COLORTERM').toLowerCase()
  const truecolor = colorterm === 'truecolor' || colorterm === '24bit'
  // tmux + Apple Terminal cannot be trusted for 24-bit even if COLORTERM lies
  // (mirrors colorize.ts clamps), so they cap at 256.
  const clamped = Boolean(env('TMUX')) || env('TERM_PROGRAM') === 'Apple_Terminal'

  if (truecolor && !clamped) {
    return 'truecolor'
  }

  const term = env('TERM')

  if (truecolor || term.includes('256color') || env('TERM_PROGRAM')) {
    return '256'
  }

  if (!term || term === 'dumb') {
    return '16'
  }

  return '256'
}

const LADDER: Blitter[] = ['1x1', 'half', 'quad', 'sextant', 'braille']
const rank = (b: Blitter): number => LADDER.indexOf(b)
// The lower (safer) of two rungs.
export const capBlitter = (ceiling: Blitter, want: Blitter): Blitter =>
  rank(want) <= rank(ceiling) ? want : ceiling

const resolveBlitterMax = (): Blitter => {
  const override = env('HERMES_VIZ_BLITTER').toLowerCase()

  if ((['1x1', 'half', 'quad', 'sextant', 'braille'] as string[]).includes(override)) {
    return override as Blitter
  }

  // Identity heuristic: raise to braille only on terminals known to render it
  // cleanly. Never auto-promote to sextant/octant.
  const term = env('TERM')

  const brailleOk =
    Boolean(env('KITTY_WINDOW_ID')) ||
    term.includes('kitty') ||
    term.includes('ghostty') ||
    term.startsWith('foot') ||
    Number(env('VTE_VERSION')) >= 6800 ||
    env('TERM_PROGRAM') === 'WezTerm' ||
    env('TERM_PROGRAM') === 'iTerm.app'

  return brailleOk ? 'braille' : 'quad'
}

// Pixel-image protocol from sync env signals. Gated behind HERMES_PIXEL_IMAGES
// (Tier B is opt-in); returns 'none' unless the flag is set AND a protocol is
// detected. Priority kitty > iterm2 > sixel.
const imagesEnabled = (): boolean => Boolean(env('HERMES_PIXEL_IMAGES')) && env('HERMES_PIXEL_IMAGES') !== '0'

const resolveImageProtocol = (): ImageProtocol => {
  if (!imagesEnabled()) {
    return 'none'
  }

  const term = env('TERM')
  const prog = env('TERM_PROGRAM')

  if (env('KITTY_WINDOW_ID') || term.includes('kitty') || term.includes('ghostty') || env('GHOSTTY_RESOURCES_DIR') || prog === 'WezTerm') {
    return 'kitty'
  }

  if (prog === 'iTerm.app' || env('ITERM_SESSION_ID')) {
    return 'iterm2'
  }

  // Plain `xterm` only does sixel when built with --enable-sixel (TERM usually
  // still reads `xterm`), so it is NOT assumed — the DA1 probe is its accurate
  // path. foot/mlterm/contour ship sixel by default.
  if (term.includes('sixel') || term.startsWith('foot') || term.startsWith('mlterm') || term.startsWith('contour')) {
    return 'sixel'
  }

  return 'none'
}

export const resolveCaps = (override?: Partial<TerminalCaps>): TerminalCaps => ({
  blitterMax: override?.blitterMax ?? resolveBlitterMax(),
  colorMode: override?.colorMode ?? resolveColorMode(),
  imageProtocol: override?.imageProtocol ?? resolveImageProtocol()
})

// ── Async escape-query probe (opt-in refinement) ────────────────────────────
// PURE: takes an injected transport so it's unit-testable and never opens its
// own reader on the live stdin (that would fight Ink's input handling). Callers
// that want escape-query accuracy wire a transport; the app otherwise relies on
// the sync env heuristic above.
export interface ProbeTransport {
  // Write a query string to the terminal.
  write: (s: string) => void
  // Resolve with whatever the terminal sent back within `timeoutMs` ('' on timeout).
  read: (timeoutMs: number) => Promise<string>
}

const DA1 = '\x1b[c' // Primary Device Attributes — sixel support reports attribute ;4

export const probeCaps = async (transport: ProbeTransport, timeoutMs = 150): Promise<Partial<TerminalCaps>> => {
  try {
    transport.write(DA1)
    const resp = await transport.read(timeoutMs)

    if (!resp) {
      return {}
    }

    const out: Partial<TerminalCaps> = {}
    // DA1 reply: CSI ? 62 ; 4 ; ... c  — attribute 4 = sixel graphics. (Match the
    // `[?…c` body; the leading ESC is a control char ESLint disallows in regex.)
    // Numeric compare so a zero-padded attribute like '04' still counts.
    const da = /\[\?([0-9;]+)c/.exec(resp)

    if (da && da[1]!.split(';').some(a => Number(a) === 4) && imagesEnabled()) {
      out.imageProtocol = 'sixel'
    }

    // A graphics-capable terminal also renders braille cleanly.
    if (out.imageProtocol) {
      out.blitterMax = 'braille'
    }

    return out
  } catch {
    return {}
  }
}

// Pick the blitter for a chart kind given capabilities.
export const pickBlitter = (kind: ChartKind, caps: TerminalCaps): Blitter => {
  const { blitterMax, colorMode } = caps

  switch (kind) {
    case 'heatmap':

    case 'sparkgrid':
      // half-block = 2 truecolor pixels/cell; at 16-color the chart uses the
      // glyph-intensity path instead (so '1x1' is fine here).
      return colorMode === '16' ? '1x1' : capBlitter(blitterMax, 'half')

    case 'distribution':

    case 'fan':
      return capBlitter(blitterMax, 'braille')

    case 'candles':

    case 'depth':
      // need color + shape, never 1-color braille → block family
      return capBlitter(blitterMax, 'quad')

    default:
      return capBlitter(blitterMax, 'quad')
  }
}
