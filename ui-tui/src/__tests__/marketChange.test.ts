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

it('preserves tiny movements and displays genuine zero plainly', async () => {
  const { formatMarketChange, lastMovement } = await import('../lib/marketChange.js')
  expect(formatMarketChange(0)).toBe('0')
  expect(formatMarketChange(0.00000012)).toBe('+1.20e-7')
  expect(formatMarketChange(-0.00001)).toBe('-1.00e-5')
  expect(formatMarketChange(null)).toBe('—')
  expect(
    lastMovement({
      ...quote,
      change: 0,
      unit: '%',
      last_movement: {
        basis: 'last_transition',
        previous_period: '2020-01-01',
        previous_value: 2,
        current_period: '2020-02-01',
        current_value: 3
      }
    })
  ).toContain('+1 pp on 2020-02-01')
})
