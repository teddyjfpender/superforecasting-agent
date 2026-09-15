import { expect, it } from 'vitest'

import { changeReference } from '../lib/marketChange.js'
import type { MarketQuote } from '../lib/marketFetch.js'

const quote: MarketQuote = {
  asOf: 0,
  category: 'Economics',
  change: 2,
  changePct: 20,
  name: 'Output',
  provider: 'test',
  symbol: 'X',
  value: 12
}

it('labels sparse observations by their actual periods', () => {
  expect(
    changeReference({
      ...quote,
      dated_history: [
        { period_start: '2023-01-01', period_end: '2023-12-31', value: 10, published_at: null, status: null },
        { period_start: '2024-01-01', period_end: '2024-12-31', value: null, published_at: null, status: null },
        { period_start: '2025-01-01', period_end: '2025-12-31', value: 12, published_at: null, status: null }
      ]
    })
  ).toBe('CHG: 2023-01-01 → 2025-01-01')
})

it('distinguishes forecast absence, missing baseline, and zero baseline', () => {
  expect(changeReference({ ...quote, kind: 'forecast', change: null, changePct: null })).toContain('same valid period')
  expect(changeReference({ ...quote, change: null })).toContain('no comparable prior value')
  expect(changeReference({ ...quote, changePct: null })).toContain('zero baseline')
  expect(changeReference({ ...quote, provider: 'coingecko' })).toContain('24 hours')
})
