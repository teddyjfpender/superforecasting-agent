// A curated, monochrome ICON vocabulary for the data views.
//
// These are deliberately NOT emoji. Emoji (🔎 📎 …) are width-2, render in
// colour, and vary across platforms/fonts — they break alignment in dense
// tables and look out of place in a themed TUI. Every glyph here is a single
// cell BMP symbol that inherits the current text colour, so it aligns in a
// monospace grid and is tinted by the semantics layer (e.g. a green ● for live,
// an amber spinner for "working").
//
// They exist to make system status + micro-interactions legible — Nielsen's
// "visibility of system status": progress spinners, live/idle/error state,
// success / failure, freshness, selection, direction, and affordances.

export const ICON = {
  attach: '❏', // attachment / document
  bullet: '•',
  cursor: '▸', // selected row / focus
  down: '▼', // negative move (paired with sign + colour)
  external: '↗', // opens elsewhere (browser)
  fail: '✗', // failure / error
  flat: '·', // unchanged / n.a.
  fresh: '◆', // new / recent
  ok: '✓', // success / enabled
  search: '⌕', // search affordance
  star: '★', // watchlisted
  starOff: '☆', // not watchlisted
  stale: '◇', // old
  up: '▲', // positive move
  warn: '▲' // attention
} as const

// Spinner frames: a filling circle that reads as motion even at a slow tick.
export const SPINNER = ['◐', '◓', '◑', '◒'] as const

export const spinnerFrame = (tick: number): string => {
  const n = SPINNER.length

  return SPINNER[((tick % n) + n) % n]
}

export type StatusKind = 'busy' | 'error' | 'idle' | 'live'

// The status dot for a connection / data source. `busy` animates a spinner so
// the user can SEE the system working; the caller colours it via semantics
// (live→up, busy→star, idle→subtle, error→down).
export const statusGlyph = (kind: StatusKind, tick = 0): string => {
  switch (kind) {
    case 'busy':
      return spinnerFrame(tick)

    case 'error':
      return ICON.fail

    case 'live':
      return '●'

    default:
      return '○'
  }
}
