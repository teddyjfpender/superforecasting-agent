import { describe, expect, it } from 'vitest'

import {
  applyBookTick,
  bookMarketId,
  fmtCents,
  fmtClose,
  fmtPMVol,
  fmtProb,
  type PMListItem,
  type PMMarketDTO,
  type PMOrderBookDTO,
  seriesTickerFor,
  tickEstimate,
  venueLabel
} from '../lib/pmData.js'
import { filterPMItems, flattenPMRows, pmExpandable, pmRowId, pmSortValue } from '../lib/pmRows.js'
import { hbar } from '../lib/sparkline.js'

const outcome = (label: string, prob: number, id: string) => ({
  label,
  liquid: true,
  market_id: id,
  prob,
  raw_prob: prob - 0.02,
  volume: 1000,
  yes_ask: prob + 0.01,
  yes_bid: prob - 0.01
})

const categorical = (): PMListItem => ({
  distribution: {
    binary: false,
    close_time: '2099-01-01T00:00:00Z',
    event_id: 'evt-1',
    headline: { close_time: '2099-01-01T00:00:00Z', n: 3, top_label: 'Alpha', top_prob: 0.5, total_volume: 30000 },
    normalized: true,
    notes: [],
    outcomes: [outcome('Alpha', 0.5, 'm-a'), outcome('Bravo', 0.3, 'm-b'), outcome('Charlie', 0.2, 'm-c')],
    overround: 0.03,
    title: 'Who wins Alpha Cup?',
    total_volume: 30000,
    url: 'https://polymarket.com/event/alpha',
    venue: 'polymarket'
  },
  event: {
    category: 'Sports',
    close_time: '2099-01-01T00:00:00Z',
    event_id: 'evt-1',
    is_binary: false,
    markets: [],
    mutually_exclusive: true,
    slug: 'alpha',
    title: 'Who wins Alpha Cup?',
    url: 'https://polymarket.com/event/alpha',
    venue: 'polymarket',
    volume: 30000
  }
})

const binary = (): PMListItem => ({
  distribution: {
    binary: true,
    close_time: '2099-02-01T00:00:00Z',
    event_id: 'FED',
    headline: { close_time: '2099-02-01T00:00:00Z', n: 1, top_label: 'Yes', top_prob: 0.13, total_volume: 5000 },
    normalized: true,
    notes: [],
    outcomes: [outcome('Yes', 0.13, 'FED-Y')],
    overround: 0,
    title: 'Fed hikes in July?',
    total_volume: 5000,
    url: 'https://kalshi.com/markets/FED',
    venue: 'kalshi'
  },
  event: {
    category: 'Economics',
    close_time: '2099-02-01T00:00:00Z',
    event_id: 'FED',
    is_binary: true,
    markets: [],
    mutually_exclusive: true,
    slug: 'FED',
    title: 'Fed hikes in July?',
    url: 'https://kalshi.com/markets/FED',
    venue: 'kalshi',
    volume: 5000
  }
})

describe('pm formatting', () => {
  it('probability, cents, and volume format honestly with an em-dash fallback', () => {
    // Probabilities are ALWAYS 2dp so a sub-1% market never collapses to "0%".
    expect(fmtProb(0.44)).toBe('44.00%')
    expect(fmtProb(0.3264)).toBe('32.64%')
    expect(fmtProb(0.0085)).toBe('0.85%')
    expect(fmtProb(0.98)).toBe('98.00%')
    expect(fmtProb(1)).toBe('100.00%')
    expect(fmtProb(null)).toBe('—')
    expect(fmtCents(0.42)).toBe('42¢')
    expect(fmtCents(null)).toBe('—')
    expect(fmtPMVol(1_500_000)).toBe('$1.5M')
    expect(fmtPMVol(2500)).toBe('$3K')
    expect(fmtPMVol(null)).toBe('—')
  })

  it('close time is relative while open, "closed" in the past', () => {
    expect(fmtClose(null)).toBe('—')
    expect(fmtClose(new Date(Date.now() - 60_000).toISOString())).toBe('closed')
    expect(fmtClose(new Date(Date.now() + 3 * 3600_000).toISOString())).toBe('3h')
  })

  it('venue labels are proper-cased', () => {
    expect(venueLabel('polymarket')).toBe('Polymarket')
    expect(venueLabel('kalshi')).toBe('Kalshi')
  })
})

describe('hbar', () => {
  it('fills proportionally with a partial final eighth-block', () => {
    expect(hbar(1, 4)).toBe('████')
    expect(hbar(0, 4)).toBe('')
    expect(hbar(0.5, 4)).toBe('██')
    // clamps out-of-range fractions rather than overflowing the width
    expect(hbar(2, 3)).toBe('███')
    expect(hbar(-1, 3)).toBe('')
  })
})

describe('bookMarketId + seriesTickerFor', () => {
  it('polymarket books key on the YES token id, kalshi on the market ticker', () => {
    const poly: PMMarketDTO = {
      close_time: null,
      event_id: 'e',
      label: 'Alpha',
      last_price: null,
      market_id: 'cond-alpha',
      open_interest: null,
      question: '',
      status: null,
      token_ids: ['tok-yes', 'tok-no'],
      url: null,
      venue: 'polymarket',
      volume: null,
      yes_ask: null,
      yes_bid: null,
      yes_mid: null
    }

    expect(bookMarketId('polymarket', poly, 'cond-alpha')).toBe('tok-yes')
    expect(bookMarketId('kalshi', { ...poly, venue: 'kalshi', market_id: 'FED-Y', token_ids: [] }, 'FED-Y')).toBe('FED-Y')
    // fallback when the market (and its tokens) aren't loaded yet
    expect(bookMarketId('polymarket', undefined, 'cond-alpha')).toBe('cond-alpha')
  })

  it('series ticker comes from the event slug for kalshi only', () => {
    expect(seriesTickerFor('kalshi', binary().event)).toBe('FED')
    expect(seriesTickerFor('polymarket', categorical().event)).toBeNull()
  })
})

describe('applyBookTick / tickEstimate', () => {
  const book = (): PMOrderBookDTO => ({
    asks: [{ price: 0.58, size: 90 }],
    best_ask: 0.58,
    best_bid: 0.55,
    bids: [{ price: 0.55, size: 120 }],
    market_id: 'tok-yes',
    mid: 0.565,
    tick_size: 0.01,
    timestamp: 1,
    venue: 'polymarket'
  })

  it('folds a matching book delta: ladders update, mid is the server estimate ONLY', () => {
    const next = applyBookTick(book(), {
      estimate: 0.585,
      kind: 'book',
      market_id: 'tok-yes',
      payload: { asks: [[0.6, 40]], bids: [[0.57, 200]] },
      venue: 'polymarket'
    })

    expect(next?.best_bid).toBe(0.57)
    expect(next?.best_ask).toBe(0.6)
    // The mid is the honest server estimate — NOT re-derived from the ladder.
    expect(next?.mid).toBeCloseTo(0.585, 4)
  })

  it('a book delta with a NULL estimate folds ladders but keeps the last honest mid', () => {
    // The raw ladder (0.3, 0.7) would yield a phantom 0.5 mid — the Putin-50%
    // bug. With a null estimate the mid stays the prior honest 0.565.
    const next = applyBookTick(book(), {
      estimate: null,
      kind: 'book',
      market_id: 'tok-yes',
      payload: { asks: [[0.7, 40]], bids: [[0.3, 200]] },
      venue: 'polymarket'
    })

    expect(next?.best_bid).toBe(0.3)
    expect(next?.mid).toBe(0.565)
  })

  it('a non-matching market id is a no-op (same reference)', () => {
    const b = book()
    expect(applyBookTick(b, { estimate: 0.9, kind: 'book', market_id: 'other', venue: 'polymarket' })).toBe(b)
  })

  it('tickEstimate folds ONLY the server estimate — never derived from the raw book', () => {
    // A real estimate passes through untouched…
    expect(
      tickEstimate({ estimate: 0.13, kind: 'price_change', market_id: 'x', payload: { price: 0.99 }, venue: 'polymarket' })
    ).toBe(0.13)
    // …a null estimate is null EVEN when the raw book could yield a mid (proof
    // by absence: no code derives a price from the payload, so 50% is impossible).
    expect(
      tickEstimate({ estimate: null, kind: 'book', market_id: 'x', payload: { asks: [[0.6, 1]], bids: [[0.4, 1]] }, venue: 'polymarket' })
    ).toBeNull()
    // …a missing / NaN estimate is null (defensive).
    expect(tickEstimate({ kind: 'noise', market_id: 'x', payload: {}, venue: 'polymarket' })).toBeNull()
    expect(tickEstimate({ estimate: Number.NaN, kind: 'book', market_id: 'x', venue: 'polymarket' })).toBeNull()
  })
})

describe('pmRows flatten / sort / filter', () => {
  it('a categorical event expands to indented sub-rows; a binary event stays a single row', () => {
    const items = [categorical(), binary()]
    const collapsed = flattenPMRows(items, new Set())
    expect(collapsed).toHaveLength(2)
    expect(collapsed.every(r => r.kind === 'headline')).toBe(true)

    const expanded = flattenPMRows(items, new Set([pmRowId(categorical())]))
    // headline + 3 outcomes + binary headline = 5
    expect(expanded).toHaveLength(5)
    expect(expanded.filter(r => r.kind === 'outcome')).toHaveLength(3)
    // the binary event never expands even if its id is in the set
    const binId = pmRowId(binary())
    expect(flattenPMRows([binary()], new Set([binId])).filter(r => r.kind === 'outcome')).toHaveLength(0)
    expect(pmExpandable(categorical())).toBe(true)
    expect(pmExpandable(binary())).toBe(false)
  })

  it('sort values pull from the headline / distribution', () => {
    const c = categorical()
    expect(pmSortValue(c, 'title')).toBe('Who wins Alpha Cup?')
    expect(pmSortValue(c, 'prob')).toBe(0.5)
    expect(pmSortValue(c, 'vol')).toBe(30000)
    expect(typeof pmSortValue(c, 'close')).toBe('number')
  })

  it('the / filter ranks by title/category/venue and drops non-matches', () => {
    const items = [categorical(), binary()]
    expect(filterPMItems(items, '')).toHaveLength(2)
    const fed = filterPMItems(items, 'fed')
    expect(fed).toHaveLength(1)
    expect(fed[0].event.event_id).toBe('FED')
  })
})
