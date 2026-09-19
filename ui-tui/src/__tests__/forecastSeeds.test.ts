import { expect, it } from 'vitest'

import { seriesForecastSeed } from '../lib/forecastSeeds.js'
import type { MarketQuote } from '../lib/marketFetch.js'

it.each(['fred', 'bcb', 'nws', 'eurostat', 'yahoo'])(
  'preserves %s identity, zero values and unknown publication time',
  provider => {
    const series = { provider, symbol: 'series', name: 'Measurement', category: 'Test', unit: 'percent' }

    const quote: MarketQuote = {
      ...series,
      value: 0,
      change: null,
      changePct: null,
      asOf: 0,
      retrieved_at: '2026-09-18T00:00:00Z',
      revision_policy: 'first_release',
      dated_history: [
        { period_start: '2026-08-01', period_end: '2026-08-31', value: 0, published_at: null, status: null }
      ]
    }

    const seed = seriesForecastSeed(series, quote, '2026-09-18T01:00:00Z')
    expect(seed.observed_value).toBe(0)
    expect(seed.market_price).toBeNull()
    expect(seed.published_at).toBeNull()
    expect(seed.observed_at).toBeNull()
    expect(seed.retrieved_at).not.toBe(seed.captured_at)
    expect(seed.period_start).toBe('2026-08-01')
    expect(seed.revision_policy).toBe('first_release')
    expect(() => seriesForecastSeed(series, { ...quote, symbol: 'different' })).toThrow('does not match')
  }
)
