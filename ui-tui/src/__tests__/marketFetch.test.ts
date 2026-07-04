import { afterEach, describe, expect, it, vi } from 'vitest'

import type { MarketSeries } from '../content/marketProviders.js'
// NOTE (Arc C): frankfurter + bea are now parsed SERVER-SIDE — their parsers and
// contract tests moved to Python (tests/forecasting/test_marketdata_providers.py).
// This file keeps the still-client parsers + the routing seam test.
import { fetchQuotes, parseBls, parseCoingecko, parseFred, parseFredCsv, parseYahoo } from '../lib/marketFetch.js'

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

// The FX-range + BEA-honesty contract now lives in Python (server-side): see
// tests/forecasting/test_marketdata_providers.py. Here we assert the ROUTING
// seam that replaced the client parsers.
// The FX-range + BEA-honesty contract now lives in Python (server-side): see
// tests/forecasting/test_marketdata_providers.py. Here we assert the ROUTING
// seam that replaced the client parsers.
describe('fetchQuotes routing (Arc C: FX + BEA go server-side)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  const opts = (over: Partial<Parameters<typeof fetchQuotes>[1]>) => ({
    getKey: () => '',
    onBatch: () => undefined,
    ...over
  })

  it('routes frankfurter series through gw.request(market.quotes), not fetch', async () => {
    const fetchFn = vi.fn()
    vi.stubGlobal('fetch', fetchFn)
    const request = vi.fn().mockResolvedValue({
      quotes: [
        { asOf: 0, category: 'FX', change: null, changePct: null, history: [], name: 'EUR per USD', prevClose: null, provider: 'frankfurter', symbol: 'EUR', unit: '', value: 0.8735 }
      ]
    })
    const batches: unknown[] = []

    await fetchQuotes([s({ category: 'FX', name: 'EUR per USD', provider: 'frankfurter', symbol: 'EUR' })], opts({ gw: { request }, onBatch: q => batches.push(...q) }))

    expect(request).toHaveBeenCalledTimes(1)
    expect(request.mock.calls[0][0]).toBe('market.quotes')
    expect(request.mock.calls[0][1]).toEqual({ series: [{ category: 'FX', name: 'EUR per USD', provider: 'frankfurter', symbol: 'EUR' }] })
    expect(batches).toHaveLength(1)
    expect((batches[0] as { value: number }).value).toBeCloseTo(0.8735)
    expect(fetchFn).not.toHaveBeenCalled() // FX never hits the network client-side
  })

  it('batches frankfurter + bea into ONE market.quotes call and passes the BEA line override', async () => {
    const request = vi.fn().mockResolvedValue({ quotes: [] })

    await fetchQuotes(
      [
        s({ category: 'FX', name: 'EUR', provider: 'frankfurter', symbol: 'EUR' }),
        { category: 'US Macro', line: '31', name: 'PCE', provider: 'bea', symbol: 'T20305', unit: '$B' } as never
      ],
      opts({ gw: { request } })
    )

    expect(request).toHaveBeenCalledTimes(1)
    const sent = (request.mock.calls[0][1] as { series: { line?: string; provider: string }[] }).series
    expect(sent.map(r => r.provider)).toEqual(['frankfurter', 'bea'])
    expect(sent.find(r => r.provider === 'bea')?.line).toBe('31')
  })

  it('skips server-side providers when no gateway is present (no fetch, no throw)', async () => {
    const fetchFn = vi.fn()
    vi.stubGlobal('fetch', fetchFn)
    const batches: unknown[] = []

    await fetchQuotes([s({ category: 'FX', provider: 'frankfurter', symbol: 'EUR' })], opts({ onBatch: q => batches.push(...q) }))

    expect(batches).toHaveLength(0)
    expect(fetchFn).not.toHaveBeenCalled()
  })

  it('leaves yahoo on the client path (fetch), NOT the gateway', async () => {
    const request = vi.fn().mockResolvedValue({ quotes: [] })
    const fetchFn = vi.fn().mockResolvedValue({
      json: async () => ({ chart: { result: [{ meta: { regularMarketPrice: 100 } }] } }),
      ok: true
    })
    vi.stubGlobal('fetch', fetchFn)

    await fetchQuotes([s({ category: 'Indices', provider: 'yahoo', symbol: '^GSPC' })], opts({ gw: { request } }))

    expect(request).not.toHaveBeenCalled() // yahoo is not server-side in C1
    expect(fetchFn).toHaveBeenCalledTimes(1)
    expect(String(fetchFn.mock.calls[0][0])).toContain('finance.yahoo.com')
  })
})
