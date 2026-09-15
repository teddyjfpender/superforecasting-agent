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
