import type { ThemeColors } from './theme.js'

const RICH_RE = /\[(?:bold\s+)?(?:dim\s+)?(#(?:[0-9a-fA-F]{3,8}))\]([\s\S]*?)(\[\/\])/g

export function parseRichMarkup(markup: string): Line[] {
  const lines: Line[] = []

  for (const raw of markup.split('\n')) {
    const trimmed = raw.trimEnd()

    if (!trimmed) {
      lines.push(['', ' '])

      continue
    }

    const matches = [...trimmed.matchAll(RICH_RE)]

    if (!matches.length) {
      lines.push(['', trimmed])

      continue
    }

    let cursor = 0

    for (const m of matches) {
      const before = trimmed.slice(cursor, m.index)

      if (before) {
        lines.push(['', before])
      }

      lines.push([m[1]!, m[2]!])
      cursor = m.index! + m[0].length
    }

    if (cursor < trimmed.length) {
      lines.push(['', trimmed.slice(cursor)])
    }
  }

  return lines
}

// All four lines are exactly LOGO_WIDTH (88) columns so the right ┃ border
// lines up with the ┓/┛ corners. The text rows were previously 84/85 wide,
// leaving the right border floating a few columns inside the box.
const LOGO_ART = [
  '┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓',
  '┃ SUPERFORECASTING AGENT                                                               ┃',
  '┃ CLI forecasting desk · ledger · calibration · backtests · alerts                     ┃',
  '┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛'
]

// Every box line is exactly FORECAST_HERO_WIDTH (45) columns with matching
// cell widths (21 | 18) so the ┌┬┐ / │…│…│ / └┴┘ separators line up cleanly.
// Earlier art mixed 20/18 borders with 21/17 row cells, so the column rule and
// right edge drifted by a column and some terminals truncated the box.
const FORECAST_HERO_ART = [
  '     as-of timeline         probability',
  '   ┌─────────────────────┬──────────────────┐',
  '   │ evidence freshness  │ 0.10 ▁▂▃▅▇ 0.90  │',
  '   │ reference classes   │ base rate + view │',
  '   │ model runs          │ ensemble update  │',
  '   └─────────────────────┴──────────────────┘',
  '      ledger · score · postmortem · learn'
]

// Palette is [primary(mint), accent(mint), border(teal), muted(neutral)] — see
// colorize(). The masthead and hero keep ONE mint line each so green reads as a
// brand accent, not a wall: the title row stays primary; rules go teal; the
// tagline + data rows go neutral muted.
const LOGO_GRADIENT = [2, 0, 3, 2] as const
const FORECAST_HERO_GRADIENT = [3, 2, 3, 3, 3, 2, 3] as const

const colorize = (art: string[], gradient: readonly number[], c: ThemeColors): Line[] => {
  const p = [c.primary, c.accent, c.border, c.muted]

  return art.map((text, i) => [p[gradient[i]!] ?? c.muted, text])
}

export const LOGO_WIDTH = 88
export const FORECAST_HERO_WIDTH = 45

export const logo = (c: ThemeColors, customLogo?: string): Line[] =>
  customLogo ? parseRichMarkup(customLogo) : colorize(LOGO_ART, LOGO_GRADIENT, c)

export const forecastHero = (c: ThemeColors, customHero?: string): Line[] =>
  customHero ? parseRichMarkup(customHero) : colorize(FORECAST_HERO_ART, FORECAST_HERO_GRADIENT, c)

export const artWidth = (lines: Line[]) => lines.reduce((m, [, t]) => Math.max(m, t.length), 0)

type Line = [string, string]
