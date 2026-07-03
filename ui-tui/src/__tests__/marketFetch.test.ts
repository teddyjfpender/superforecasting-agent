import { describe, expect, it } from 'vitest'

import type { MarketSeries } from '../content/marketProviders.js'
import { parseBea, parseBls, parseCoingecko, parseFrankfurter, parseFred, parseFredCsv, parseYahoo } from '../lib/marketFetch.js'

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

describe('parseFredCsv', () => {
  it('takes the last two real rows from the keyless CSV (oldest→newest)', () => {
    const csv = 'DATE,FEDFUNDS\n2026-03-01,5.30\n2026-04-01,.\n2026-05-01,5.10\n2026-06-01,4.90\n'
    const q = parseFredCsv(csv, s({ category: 'Rates', provider: 'fred', symbol: 'FEDFUNDS', unit: '%' }))
    expect(q.value).toBeCloseTo(4.9)
    // prior real value is 5.10 (the "." row is skipped)
    expect(q.change).toBeCloseTo(-0.2, 5)
    expect(q.asOf).toBe(Date.parse('2026-06-01'))
  })

  it('returns null for an empty/headers-only CSV', () => {
    expect(parseFredCsv('DATE,X\n', s({ provider: 'fred' })).value).toBeNull()
  })
})

describe('parseBea', () => {
  it('reads the last DataValue and maps a quarterly TimePeriod to a date', () => {
    const json = { BEAAPI: { Results: { Data: [{ DataValue: '1,000.0', TimePeriod: '2026Q1' }, { DataValue: '28,500.5', TimePeriod: '2026Q2' }] } } }
    const q = parseBea(json, s({ category: 'GDP', provider: 'bea', symbol: 'T10105', unit: '$B' }))
    expect(q.value).toBeCloseTo(28500.5)
    // 2026Q2 → April 1 (no longer the hardcoded 0)
    expect(q.asOf).toBe(Date.parse('2026-04-01'))
  })
})

describe('FX range + BEA honesty (the operator screenshots)', () => {
  const series = (over: object) => ({ category: 'FX', name: 'EUR per USD', provider: 'frankfurter', symbol: 'EUR', ...over })

  it('a Frankfurter date-range payload yields value, day change, and the 1MO history', () => {
    const json = {
      base: 'USD',
      rates: {
        '2026-06-02': { EUR: 0.86 },
        '2026-06-16': { EUR: 0.865 },
        '2026-07-02': { EUR: 0.871 },
        '2026-07-03': { EUR: 0.8735 }
      }
    }
    const [q] = parseFrankfurter(json, [series({}) as never])
    expect(q!.value).toBeCloseTo(0.8735)
    expect(q!.prevClose).toBeCloseTo(0.871)
    expect(q!.change).toBeCloseTo(0.0025, 6)
    expect(q!.changePct).toBeCloseTo(0.287, 2)
    expect(q!.history).toEqual([0.86, 0.865, 0.871, 0.8735])
  })

  it('a /latest-shaped payload still parses value-only (backward compatible)', () => {
    const [q] = parseFrankfurter({ date: '2026-07-03', rates: { EUR: 0.8735 } }, [series({}) as never])
    expect(q!.value).toBeCloseTo(0.8735)
    expect(q!.change).toBeNull()
  })

  it('BEA reads the HEADLINE line, computes the quarter change, and never fabricates 0', () => {
    const bea = { category: 'US Macro', name: 'BEA NIPA: PCE', provider: 'bea', symbol: 'T20305' }
    const json = {
      BEAAPI: { Results: { Data: [
        { DataValue: '99', LineNumber: '31', TimePeriod: '2026Q1' },
        { DataValue: '21,363,352', LineNumber: '1', TimePeriod: '2025Q4' },
        { DataValue: '21,634,948', LineNumber: '1', TimePeriod: '2026Q1' },
        { DataValue: '88', LineNumber: '31', TimePeriod: '2025Q4' }
      ] } }
    }
    const q = parseBea(json, bea as never)
    expect(q.value).toBe(21_634_948)
    expect(q.prevClose).toBe(21_363_352)
    expect(q.change).toBe(271_596)
    expect(q.changePct).toBeCloseTo(1.271, 2)

    // The operator's 0.0000 wall: an API-error payload (empty Data) must be
    // NULL — absence renders '—', never a fabricated zero.
    const err = parseBea({ BEAAPI: { Error: { APIErrorCode: '201' } } }, bea as never)
    expect(err.value).toBeNull()
    expect(err.change).toBeNull()
  })
})
