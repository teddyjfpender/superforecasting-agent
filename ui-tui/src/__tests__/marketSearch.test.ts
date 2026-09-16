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

const catalog = [
  { provider: 'yahoo', symbol: 'NVDA', name: 'NVIDIA', category: 'Stocks' },
  { provider: 'coingecko', symbol: 'bitcoin', name: 'Bitcoin', category: 'Crypto' },
  { provider: 'yahoo', symbol: 'GC=F', name: 'Gold', category: 'Commodities' },
  {
    provider: 'worldbank',
    symbol: 'BRA/CPI',
    name: 'Inflation',
    category: 'Inflation',
    search_terms: 'Brazil Latin America'
  }
]

describe('searchCatalog', () => {
  it('finds a ticker by symbol and a name', () => {
    expect(searchCatalog('NVDA', catalog).some(s => s.symbol === 'NVDA')).toBe(true)
    expect(searchCatalog('bitcoin', catalog).some(s => s.symbol === 'bitcoin')).toBe(true)
  })

  it('uses intent synonyms — "gold" surfaces a commodity', () => {
    const res = searchCatalog('gold', catalog)
    expect(res.some(s => s.symbol === 'GC=F' || s.category === 'Commodities')).toBe(true)
  })

  it('uses the connected catalog and country metadata', () => {
    expect(searchCatalog('Brazil', catalog).map(s => s.provider)).toEqual(['worldbank'])
    expect(searchCatalog('NVDA', [])).toEqual([])
  })

  it('returns [] for an empty query', () => {
    expect(searchCatalog('   ', catalog)).toEqual([])
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

  it('returns [] with no gateway and preserves RPC failures', async () => {
    expect(await searchYahoo('apple')).toEqual([])
    expect(await searchYahoo('   ', { request: vi.fn() })).toEqual([])

    const request = vi.fn().mockRejectedValue(new Error('down'))
    await expect(searchYahoo('apple', { request })).rejects.toThrow('down')
  })
})

it('requires country and intent together rather than returning every match of either term', () => {
  expect(searchCatalog('Brazil prices', catalog).map(s => s.provider)).toEqual([])
  expect(searchCatalog('Brazil inflation', catalog).map(s => s.provider)).toEqual(['worldbank'])
  expect(searchCatalog('Brazil bitcoin', catalog)).toEqual([])
})

it('federated lookup preserves remote identity and unit without inventing catalog provenance', async () => {
  const { discoverMarkets } = await import('../lib/marketSearch.js')

  const request = vi.fn().mockResolvedValue({
    results: [
      {
        provider: 'worldbank',
        symbol: 'ZMB/SP.POP.TOTL',
        name: 'Zambia population',
        category: 'demographics',
        unit: '',
        catalog_id: null
      }
    ],
    statuses: []
  })

  const results = await discoverMarkets('Zambia population', { request })
  expect(request).toHaveBeenCalledWith('market.discover', { query: 'Zambia population' })
  expect(results).toEqual([
    { provider: 'worldbank', symbol: 'ZMB/SP.POP.TOTL', name: 'Zambia population', category: 'demographics', unit: '' }
  ])
})

it('country abbreviations do not match substrings or other United countries', () => {
  const rows = ['United States', 'Australia', 'United Arab Emirates'].map(name => ({
    provider: 'worldbank',
    symbol: name,
    name: `${name} unemployment`,
    category: 'Employment'
  }))

  expect(searchCatalog('US jobs', rows).map(r => r.symbol)).toEqual(['United States'])
})
