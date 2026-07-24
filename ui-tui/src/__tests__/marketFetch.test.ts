import { afterEach, describe, expect, it, vi } from 'vitest'

import type { MarketSeries } from '../content/marketProviders.js'
// Arc C is DONE (C3): EVERY provider — including yahoo, the last client parser —
// is now parsed SERVER-SIDE. Their parsers + contract tests live in Python
// (tests/forecasting/test_marketdata_providers.py) where the estimator-honesty
// taxonomy can finally see the quote math. This file keeps ONLY the transport
// seam: fetchQuotes batches every server-side series into ONE market.quotes RPC
// and never touches `fetch` itself.
import { DEFAULT_SERVER_SIDE, fetchQuotes } from '../lib/marketFetch.js'

const s = (over: Partial<MarketSeries>): MarketSeries => ({
  category: 'Indices',
  name: 'X',
  provider: 'yahoo',
  symbol: 'X',
  ...over
})

describe('DEFAULT_SERVER_SIDE', () => {
  it('routes ALL seven providers server-side (yahoo joined at C3)', () => {
    expect([...DEFAULT_SERVER_SIDE].sort()).toEqual(
      ['bea', 'bls', 'coingecko', 'frankfurter', 'fred', 'stooq', 'yahoo'].sort()
    )
  })
})

describe('fetchQuotes routing (Arc C3: every provider goes through market.quotes)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  const opts = (over: Partial<Parameters<typeof fetchQuotes>[1]>) => ({
    getKey: () => '',
    onBatch: () => undefined,
    ...over
  })

  it('batches EVERY provider (incl. yahoo) into ONE market.quotes call, never fetch', async () => {
    const fetchFn = vi.fn()
    vi.stubGlobal('fetch', fetchFn)

    const request = vi.fn().mockResolvedValue({
      quotes: [
        { asOf: 0, category: 'Indices', change: null, changePct: null, currency: null, dayHigh: null, dayLow: null, exchange: null, history: [], name: 'S&P 500', prevClose: null, provider: 'yahoo', symbol: '^GSPC', unit: '', value: 7420.1, volume: null, week52High: null, week52Low: null }
      ]
    })

    const batches: unknown[] = []

    await fetchQuotes(
      [
        s({ category: 'Indices', name: 'S&P 500', provider: 'yahoo', symbol: '^GSPC' }),
        s({ category: 'FX', name: 'EUR', provider: 'frankfurter', symbol: 'EUR' }),
        s({ category: 'Crypto', name: 'Bitcoin', provider: 'coingecko', symbol: 'bitcoin' }),
        s({ category: 'Rates', name: 'Fed Funds', provider: 'fred', symbol: 'FEDFUNDS', unit: '%' }),
        s({ category: 'Inflation', name: 'CPI-U', provider: 'bls', symbol: 'CUUR0000SA0' }),
        s({ category: 'Stocks', name: 'Apple', provider: 'stooq', symbol: 'aapl.us' }),
        { category: 'US Macro', line: '31', name: 'PCE', provider: 'bea', symbol: 'T20305', unit: '$B' } as never
      ],
      opts({ gw: { request }, onBatch: q => batches.push(...q) })
    )

    // ONE batched RPC carries all seven providers; NONE touch the network.
    expect(request).toHaveBeenCalledTimes(1)
    expect(request.mock.calls[0][0]).toBe('market.quotes')
    const sent = (request.mock.calls[0][1] as { series: { line?: string; provider: string }[] }).series
    expect(sent.map(r => r.provider)).toEqual(['yahoo', 'frankfurter', 'coingecko', 'fred', 'bls', 'stooq', 'bea'])
    expect(sent.find(r => r.provider === 'bea')?.line).toBe('31') // BEA line override carried
    expect(batches).toHaveLength(1)
    expect((batches[0] as { value: number }).value).toBeCloseTo(7420.1)
    expect(fetchFn).not.toHaveBeenCalled()
  })

  it('the per-provider flag reverts a provider — dropping yahoo excludes it from the batch', async () => {
    const request = vi.fn().mockResolvedValue({ quotes: [] })

    await fetchQuotes(
      [
        s({ category: 'Indices', provider: 'yahoo', symbol: '^GSPC' }),
        s({ category: 'FX', provider: 'frankfurter', symbol: 'EUR' })
      ],
      // Operator reverts yahoo (not in serverSide) → only frankfurter is sent.
      opts({ gw: { request }, serverSide: ['frankfurter'] })
    )

    expect(request).toHaveBeenCalledTimes(1)
    const sent = (request.mock.calls[0][1] as { series: { provider: string }[] }).series
    expect(sent.map(r => r.provider)).toEqual(['frankfurter'])
  })

  it('skips everything when no gateway is present (no fetch, no throw)', async () => {
    const fetchFn = vi.fn()
    vi.stubGlobal('fetch', fetchFn)
    const batches: unknown[] = []

    await fetchQuotes([s({ category: 'Indices', provider: 'yahoo', symbol: '^GSPC' })], opts({ onBatch: q => batches.push(...q) }))

    expect(batches).toHaveLength(0)
    expect(fetchFn).not.toHaveBeenCalled()
  })

  it('a failing RPC never blanks the tape (no throw, no batch)', async () => {
    const request = vi.fn().mockRejectedValue(new Error('gateway down'))
    const batches: unknown[] = []

    await expect(
      fetchQuotes([s({ category: 'FX', provider: 'frankfurter', symbol: 'EUR' })], opts({ gw: { request }, onBatch: q => batches.push(...q) }))
    ).resolves.toBeUndefined()
    expect(batches).toHaveLength(0)
  })
})
