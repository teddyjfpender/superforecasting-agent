import { afterEach, describe, expect, it, vi } from 'vitest'

import type { MarketSeries } from '../content/marketProviders.js'
// NOTE (Arc C): frankfurter + bea (C1) and coingecko + fred + bls + stooq (C2)
// are now parsed SERVER-SIDE — their parsers and contract tests moved to Python
// (tests/forecasting/test_marketdata_providers.py). This file keeps the only
// still-client parser (yahoo, C3) + the routing seam test.
import { fetchQuotes, parseYahoo } from '../lib/marketFetch.js'

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

// The coingecko / fred / bls / stooq contracts (like FX + BEA) now live in
// Python (server-side): see tests/forecasting/test_marketdata_providers.py. Here
// we assert the ROUTING seam that replaced the client parsers.
describe('fetchQuotes routing (Arc C2: FX + BEA + coingecko/fred/bls/stooq go server-side)', () => {
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

  it('routes coingecko/fred/bls/stooq through ONE market.quotes call, never fetch (C2)', async () => {
    const fetchFn = vi.fn()
    vi.stubGlobal('fetch', fetchFn)
    const request = vi.fn().mockResolvedValue({ quotes: [] })

    await fetchQuotes(
      [
        s({ category: 'Crypto', name: 'Bitcoin', provider: 'coingecko', symbol: 'bitcoin' }),
        s({ category: 'Rates', name: 'Fed Funds', provider: 'fred', symbol: 'FEDFUNDS', unit: '%' }),
        s({ category: 'Inflation', name: 'CPI-U', provider: 'bls', symbol: 'CUUR0000SA0' }),
        s({ category: 'Stocks', name: 'Apple', provider: 'stooq', symbol: 'aapl.us' })
      ],
      opts({ gw: { request } })
    )

    // ONE batched RPC carries all four; none of them touch the network client-side.
    expect(request).toHaveBeenCalledTimes(1)
    const sent = (request.mock.calls[0][1] as { series: { provider: string }[] }).series
    expect(sent.map(r => r.provider)).toEqual(['coingecko', 'fred', 'bls', 'stooq'])
    expect(fetchFn).not.toHaveBeenCalled()
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
