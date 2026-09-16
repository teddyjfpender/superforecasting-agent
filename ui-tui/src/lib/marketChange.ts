import type { MarketQuote } from './marketFetch.js'

/** Describe the source comparison without treating monthly data as daily prices. */
export function changeReference(quote: MarketQuote): string {
  if (quote.kind === 'forecast') {
    return 'CHG unavailable: no prior forecast for the same valid period.'
  }

  if (quote.value == null) {
    return 'CHG unavailable: no latest measurement.'
  }

  if (quote.change == null) {
    return 'CHG unavailable: source supplied no comparable prior value.'
  }

  if (quote.comparison) {
    const c = quote.comparison
    const basis = c.basis === 'last_transition' ? 'Last observed move*' : quote.change === 0 ? 'Unchanged' : 'CHG'
    const unit = quote.unit?.includes('%') ? ' · absolute Δ in pp' : ''

    return `${basis}: ${c.previous_period} → ${c.current_period}${unit}${c.previous_value === 0 && quote.changePct === null ? ' · percentage unavailable (zero baseline)' : ''}`
  }

  const observations = quote.dated_history?.filter(point => point.value != null) ?? []
  const previous = observations.at(-2)
  const latest = observations.at(-1)

  const period =
    previous && latest && latest.value === quote.value
      ? `CHG: ${previous.period_start} → ${latest.period_start}`
      : quote.provider === 'coingecko'
        ? 'CHG vs 24 hours ago'
        : quote.prevClose != null
          ? 'CHG vs prior close'
          : 'CHG vs previous available observation'

  return `${period}${quote.changePct == null ? ' · percentage unavailable (zero baseline)' : ''}`
}

/** Compact precision without rounding real movements to an apparent zero. */
export function formatMarketChange(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return '—'
  }

  if (value === 0) {
    return '0'
  }

  const magnitude = Math.abs(value)

  const number =
    magnitude < 0.0001 ? magnitude.toExponential(2) : magnitude.toLocaleString('en-US', { maximumFractionDigits: 4 })

  return `${value > 0 ? '+' : '-'}${number}`
}

export function lastMovement(quote: MarketQuote): string | null {
  const movement = quote.last_movement

  if (quote.change !== 0 || !movement) {
    return null
  }

  const unit = quote.unit?.includes('%') ? ' pp' : quote.unit ? ` ${quote.unit}` : ''

  return `Last movement: ${formatMarketChange(movement.current_value - movement.previous_value)}${unit} on ${movement.current_period} (vs ${movement.previous_period})`
}

/** A marked historical move for flat observation series; never alter the quote. */
export function displayedChange(quote: MarketQuote): {
  change: number | null
  percent: number | null
  historical: boolean
} {
  const move = quote.last_movement

  if (quote.change === 0 && move && ['observation', 'estimate', 'reanalysis'].includes(quote.kind ?? '')) {
    const change = move.current_value - move.previous_value

    if (Number.isFinite(change) && change !== 0) {
      return {
        change,
        percent: move.previous_value === 0 ? null : (change / Math.abs(move.previous_value)) * 100,
        historical: true
      }
    }
  }

  return { change: quote.change, percent: quote.changePct, historical: quote.comparison?.basis === 'last_transition' }
}
