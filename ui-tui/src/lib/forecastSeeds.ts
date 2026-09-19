/** Capture the selected source identity; never infer a belief from its price. */
import type { MarketSeries } from '../content/marketProviders.js'
import type { ForecastMarketSeed } from '../protocol/generated.js'

import type { MarketQuote } from './marketFetch.js'
import type { PMDisplayRow } from './pmRows.js'

const timestamp = (value: number | null | undefined): string | null =>
  value && Number.isFinite(value) && !Number.isNaN(new Date(value).getTime()) ? new Date(value).toISOString() : null

const common = (capturedAt: string) => ({
  captured_at: capturedAt,
  retrieved_at: null,
  observed_at: null,
  published_at: null,
  close_time: null,
  event_id: null,
  outcome_id: null,
  outcome_label: null,
  units: null,
  revision_policy: null,
  period_start: null,
  period_end: null,
  market_price: null,
  observed_value: null,
  source_url: null
})

export function seriesForecastSeed(
  series: MarketSeries,
  quote?: MarketQuote,
  capturedAt = new Date().toISOString()
): ForecastMarketSeed {
  if (quote && (quote.provider !== series.provider || quote.symbol !== series.symbol)) {
    throw new Error('The quote does not match the selected series; refresh before creating a forecast.')
  }

  const latest = quote?.dated_history?.at(-1)
  const period = latest?.value != null && latest.value === quote?.value ? latest : null

  return {
    ...common(capturedAt),
    kind: 'series',
    provider: series.provider,
    symbol: series.symbol,
    title: `What will ${series.name || series.symbol} be?`,
    source_url: quote?.source_url ?? null,
    units: quote?.unit ?? series.unit ?? null,
    retrieved_at: quote?.retrieved_at ?? null,
    observed_at: timestamp(quote?.asOf),
    published_at: quote?.published_at ?? null,
    revision_policy: quote?.revision_policy ?? null,
    observed_value: quote?.value ?? null,
    period_start: period?.period_start ?? null,
    period_end: period?.period_end ?? null
  }
}

export function predictionForecastSeed(row: PMDisplayRow, capturedAt = new Date().toISOString()): ForecastMarketSeed {
  const item = row.kind === 'headline' ? row.item : row.parent

  if (row.kind === 'headline' && !item.distribution.binary) {
    throw new Error('Press Space to expand this event, select a specific outcome, then press F.')
  }

  const outcome = row.kind === 'outcome' ? row.outcome : item.distribution.outcomes[0]

  if (!outcome?.market_id) {
    throw new Error('This outcome has no stable market identifier yet; refresh and retry.')
  }

  const market = item.event.markets.find(candidate => candidate.market_id === outcome.market_id)

  return {
    ...common(capturedAt),
    kind: 'prediction_market',
    provider: item.event.venue,
    symbol: outcome.market_id,
    event_id: item.event.event_id,
    outcome_id: outcome.market_id,
    outcome_label: outcome.label,
    title: market?.question || `${item.event.title} — ${outcome.label}`,
    source_url: market?.url ?? item.event.url,
    close_time: market?.close_time ?? item.event.close_time,
    market_price: market?.yes_mid ?? null
  }
}
