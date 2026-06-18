import { describe, expect, it } from 'vitest'

import { parseYahooSearch, searchCatalog, yahooTypeToCategory } from '../lib/marketSearch.js'
import { sparkline } from '../lib/sparkline.js'

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

describe('yahoo search parsing', () => {
  it('maps quote types to categories', () => {
    expect(yahooTypeToCategory('EQUITY')).toBe('Stocks')
    expect(yahooTypeToCategory('CRYPTOCURRENCY')).toBe('Crypto')
    expect(yahooTypeToCategory('INDEX')).toBe('Indices')
    expect(yahooTypeToCategory('FUTURE')).toBe('Commodities')
    expect(yahooTypeToCategory('CURRENCY')).toBe('FX')
  })

  it('parses the search response into series', () => {
    const json = {
      quotes: [
        { exchange: 'NMS', quoteType: 'EQUITY', shortname: 'Apple Inc.', symbol: 'AAPL' },
        { quoteType: 'CRYPTOCURRENCY', shortname: 'Bitcoin USD', symbol: 'BTC-USD' },
        { nope: true }
      ]
    }

    const out = parseYahooSearch(json)
    expect(out).toHaveLength(2)
    expect(out[0]).toEqual({ category: 'Stocks', name: 'Apple Inc.', provider: 'yahoo', symbol: 'AAPL' })
    expect(out[1].category).toBe('Crypto')
  })
})
