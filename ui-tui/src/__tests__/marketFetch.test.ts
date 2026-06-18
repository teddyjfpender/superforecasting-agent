import { describe, expect, it } from 'vitest'

import type { MarketSeries } from '../content/marketProviders.js'
import { parseBls, parseCoingecko, parseFrankfurter, parseFred, parseYahoo } from '../lib/marketFetch.js'

const s = (over: Partial<MarketSeries>): MarketSeries => ({
  category: 'Indices',
  name: 'X',
  provider: 'yahoo',
  symbol: 'X',
  ...over
})

describe('parseYahoo', () => {
  it('reads price, computes change vs previous close, keeps volume + time', () => {
    const chart = {
      chart: {
        result: [
          {
            meta: {
              chartPreviousClose: 7511.35,
              regularMarketPrice: 7420.1,
              regularMarketTime: 1781729434,
              regularMarketVolume: 3339473000,
              shortName: 'S&P 500'
            }
          }
        ]
      }
    }

    const q = parseYahoo(chart, s({ name: 'S&P 500', symbol: '^GSPC' }))
    expect(q.value).toBeCloseTo(7420.1)
    expect(q.change).toBeCloseTo(-91.25, 2)
    expect(q.changePct).toBeCloseTo(-1.215, 2)
    expect(q.volume).toBe(3339473000)
    expect(q.asOf).toBe(1781729434000)
    expect(q.name).toBe('S&P 500')
  })

  it('returns null value for a malformed response', () => {
    expect(parseYahoo({}, s({})).value).toBeNull()
  })
})

describe('parseFrankfurter', () => {
  it('maps each currency rate to a quote (USD base)', () => {
    const json = { base: 'USD', date: '2026-06-17', rates: { EUR: 0.86274, JPY: 160.31 } }
    const out = parseFrankfurter(json, [s({ category: 'FX', provider: 'frankfurter', symbol: 'EUR' }), s({ category: 'FX', provider: 'frankfurter', symbol: 'JPY' })])
    expect(out[0].value).toBeCloseTo(0.86274)
    expect(out[1].value).toBeCloseTo(160.31)
    expect(out[0].asOf).toBe(Date.parse('2026-06-17'))
  })
})

describe('parseCoingecko', () => {
  it('reads usd price + 24h change', () => {
    const json = { bitcoin: { usd: 64239, usd_24h_change: -1.05 } }
    const q = parseCoingecko(json, [s({ category: 'Crypto', provider: 'coingecko', symbol: 'bitcoin' })])[0]
    expect(q.value).toBe(64239)
    expect(q.changePct).toBeCloseTo(-1.05)
    expect(q.change).toBeCloseTo(64239 * -0.0105, 0)
  })
})

describe('parseFred', () => {
  it('takes the latest observation and change vs the prior one', () => {
    const json = { observations: [{ date: '2026-05-01', value: '4.2' }, { date: '2026-04-01', value: '4.0' }] }
    const q = parseFred(json, s({ category: 'Employment', provider: 'fred', symbol: 'UNRATE', unit: '%' }))
    expect(q.value).toBeCloseTo(4.2)
    expect(q.change).toBeCloseTo(0.2, 5)
    expect(q.asOf).toBe(Date.parse('2026-05-01'))
  })

  it('handles FRED missing values ("." ) as null', () => {
    const json = { observations: [{ date: '2026-05-01', value: '.' }] }
    expect(parseFred(json, s({ provider: 'fred' })).value).toBeNull()
  })
})

describe('parseBls', () => {
  it('reads the latest data point and change', () => {
    const json = {
      Results: { series: [{ data: [{ period: 'M05', value: '320.1', year: '2026' }, { period: 'M04', value: '319.0', year: '2026' }] }] }
    }

    const q = parseBls(json, s({ category: 'Inflation', provider: 'bls', symbol: 'CUUR0000SA0' }))
    expect(q.value).toBeCloseTo(320.1)
    expect(q.change).toBeCloseTo(1.1, 5)
  })
})
