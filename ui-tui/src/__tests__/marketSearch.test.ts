import { describe, expect, it, vi } from 'vitest'

import { searchCatalog, searchYahoo } from '../lib/marketSearch.js'
import { blockChart, sparkline } from '../lib/sparkline.js'

describe('sparkline', () => {
  it('maps a series onto block ticks, low→high', () => {
    const out = sparkline([1, 2, 3, 4, 5, 6, 7, 8])
    expect(out.length).toBe(8)
    expect(out[0]).toBe('▁')
    expect(out[out.length - 1]).toBe('█')
    expect(out).toMatch(/^[▁▂▃▄▅▆▇█]+$/u)
  })

  it('returns empty for <2 points and honours maxPoints', () => {
    expect(sparkline([5])).toBe('')
    expect(sparkline([1, 2, 3, 4, 5], 3).length).toBe(3)
  })
})

describe('blockChart', () => {
  it('renders a height×width filled area chart, top→bottom', () => {
    const lines = blockChart([1, 2, 3, 4, 5, 6], 6, 4)
    expect(lines).toHaveLength(4)
    expect(new Set(lines.map(l => l.length))).toEqual(new Set([6]))
    // top row mostly empty, bottom row mostly filled
    expect(lines[lines.length - 1]).toMatch(/█/u)
    expect(lines.join('')).toMatch(/^[ ▁▂▃▄▅▆▇█]+$/u)
  })

  it('returns [] for <2 points or zero height', () => {
    expect(blockChart([1], 10, 4)).toEqual([])
    expect(blockChart([1, 2, 3], 10, 0)).toEqual([])
  })
})

describe('searchCatalog', () => {
  it('finds a ticker by symbol and a name', () => {
    expect(searchCatalog('NVDA').some(s => s.symbol === 'NVDA')).toBe(true)
    expect(searchCatalog('bitcoin').some(s => s.symbol === 'bitcoin')).toBe(true)
  })

  it('uses intent synonyms — "gold" surfaces a commodity', () => {
    const res = searchCatalog('gold')
    expect(res.some(s => s.symbol === 'GC=F' || s.category === 'Commodities')).toBe(true)
  })

  it('returns [] for an empty query', () => {
    expect(searchCatalog('   ')).toEqual([])
  })
})

// The Yahoo search PARSER + quoteType→category mapping moved SERVER-SIDE (Arc
// C3): see tests/forecasting/test_marketdata_providers.py. Here we assert the
// transport seam — searchYahoo routes through the gateway's market.search RPC.
describe('searchYahoo routing (Arc C3: server-side via market.search)', () => {
  it('routes the query through gw.request(market.search) and maps the results', async () => {
    const request = vi.fn().mockResolvedValue({
      results: [{ category: 'Stocks', name: 'Apple Inc.', provider: 'yahoo', symbol: 'AAPL' }]
    })

    const out = await searchYahoo('apple', { request })

    expect(request).toHaveBeenCalledTimes(1)
    expect(request.mock.calls[0][0]).toBe('market.search')
    expect(request.mock.calls[0][1]).toEqual({ query: 'apple' })
    expect(out).toEqual([{ category: 'Stocks', name: 'Apple Inc.', provider: 'yahoo', symbol: 'AAPL' }])
  })

  it('returns [] with no gateway and never throws on a failed RPC', async () => {
    expect(await searchYahoo('apple')).toEqual([])
    expect(await searchYahoo('   ', { request: vi.fn() })).toEqual([])

    const request = vi.fn().mockRejectedValue(new Error('down'))
    expect(await searchYahoo('apple', { request })).toEqual([])
  })
})
