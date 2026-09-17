import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import {
  decodeFeedMessage,
  encodeFeedMessage,
  presentFeedShare,
  sharePredictionMarket,
  shareQuote,
  validFeedShare
} from '../lib/feedShare.js'
import { feedChartLines } from '../lib/feedShareChart.js'
import { parseEnvelope } from '../lib/signalClient.js'
import type { FeedShare } from '../protocol/generated.js'

const fixture = (): FeedShare =>
  JSON.parse(readFileSync(new URL('../../../tests/fixtures/feed_share/v1.json', import.meta.url), 'utf8'))

describe('portable feed snapshots', () => {
  it('round-trips through a real Signal receive envelope including Unicode and missing readings', () => {
    const share = fixture()
    const wire = encodeFeedMessage('IPCA release', share)

    const message = parseEnvelope({
      source: '+15550001111',
      timestamp: 1,
      dataMessage: { message: wire, timestamp: 1 }
    })

    expect(decodeFeedMessage(message!.text)).toEqual({ text: 'IPCA release', share })
    expect(decodeFeedMessage(encodeFeedMessage('', share)).share).toEqual(share)
  })
  it.each([
    'version',
    'boolean_version',
    'duplicate',
    'overlap',
    'outside',
    'nan',
    'string',
    'control',
    'secret_url',
    'extra'
  ])('rejects %s like the Python contract', mutation => {
    const raw = fixture()
    const feed = raw.feeds[0]!

    if (mutation === 'version') {
      Object.assign(raw, { version: 3 })
    }

    if (mutation === 'boolean_version') {
      Object.assign(raw, { version: true })
    }

    if (mutation === 'duplicate') {
      raw.feeds.push(feed)
    }

    if (mutation === 'overlap') {
      feed.points[1]!.start = '2026-06-30'
    }

    if (mutation === 'outside') {
      raw.horizon.end = '2026-07-31'
    }

    if (mutation === 'nan') {
      feed.points[0]!.value = NaN
    }

    if (mutation === 'string') {
      Object.assign(feed.points[0]!, { value: '0.16' })
    }

    if (mutation === 'control') {
      feed.name = '\x1b[2J'
    }

    if (mutation === 'secret_url') {
      feed.source_url = 'https://example.com/?api_key=secret'
    }

    if (mutation === 'extra') {
      Object.assign(raw, { execute: 'something' })
    }

    expect(validFeedShare(raw)).toBe(false)
    expect(() => encodeFeedMessage('Hi', raw)).toThrow()
  })
  it('bounds decoding and leaves future or malformed versions as ordinary text', () => {
    const text = 'Text\n```sfa-feed\n{"version":3}\n```'
    expect(decodeFeedMessage(text)).toEqual({ text, share: null })
    expect(decodeFeedMessage('x'.repeat(50_000)).share).toBeNull()
    expect(decodeFeedMessage('Text\n```sfa-feed\n{\n```').share).toBeNull()
  })
  it('changes horizon without mutating the captured selection', () => {
    const share = fixture()
    const presented = presentFeedShare(share, 'line-chart', 2)
    expect(presented.horizon.start).toBe('2026-07-01')
    expect(share.feeds[0]!.points).toHaveLength(3)
    expect(validFeedShare(presented)).toBe(true)
  })
  it('never invents dates for undated price history or forwards URL tokens', () => {
    const quote = {
      provider: 'yahoo',
      symbol: 'X',
      name: 'X',
      unit: 'USD',
      category: 'stocks',
      asOf: 0,
      value: 12,
      change: null,
      changePct: null,
      history: [1, 2],
      source_url: 'https://example.com/data?token=secret'
    }

    expect(shareQuote(quote)).toBeNull()
    const share = shareQuote({ ...quote, asOf: Date.parse('2026-09-16') })!
    expect(share.feeds[0]!.source_url).toBe('https://example.com/data')
    expect(share.feeds[0]!.points).toHaveLength(1)
  })
  it('normalizes timestamped closes without inventing or collapsing observations', () => {
    const quote = (dates: string[]) => ({
      provider: 'yahoo',
      symbol: '^GSPC',
      name: 'S&P 500',
      category: 'indices',
      asOf: 0,
      value: 12,
      change: null,
      changePct: null,
      dated_history: dates.map(period => ({
        period_start: period,
        period_end: period,
        value: 12,
        published_at: null,
        status: null
      }))
    })

    const raw = quote(['2026-09-14T14:00:00+00:00', '2026-09-15T23:00:00-04:00'])
    const share = shareQuote(raw)!
    expect(share?.feeds[0]?.points.map(point => point.start)).toEqual([
      '2026-09-14T14:00:00.000Z',
      '2026-09-16T03:00:00.000Z'
    ])
    expect(raw.dated_history[0]?.period_start).toBe('2026-09-14T14:00:00+00:00')
    expect(validFeedShare(share)).toBe(true)

    for (const invalid of ['2026-02-30T14:00:00Z', '2026-09-14T14:00:00', 'not a date', '2026-09-14T24:00:00Z']) {
      expect(shareQuote(quote([invalid]))).toBeNull()
    }

    expect(shareQuote(quote(['2026-09-14T14:00:00Z', '2026-09-14T15:00:00Z']))?.version).toBe(2)
    expect(shareQuote(quote(['2026-09-14T14:00:00Z', '2026-09-14T14:00:00Z']))).toBeNull()
  })
  it('renders zero-based signed charts, missing gaps and bounded hostile values', () => {
    const points = fixture().feeds[0]!.points
    const lines = feedChartLines(points, 'bar-chart', 25)
    expect(lines.join('\n')).toContain('-0.32 min')
    expect(lines).toHaveLength(7)
    expect(lines.slice(1, -1).some(row => row[12] === '█')).toBe(false)
    expect(
      feedChartLines(
        [
          { ...points[0]!, value: Number.MAX_VALUE },
          { ...points[2]!, value: -Number.MAX_VALUE }
        ],
        'line-chart',
        20
      )
    ).toHaveLength(7)
  })
})

it('uses calendar spacing for sparse observations instead of implying uniform cadence', () => {
  const points = [1, 2, 31].map(day => ({
    start: `2026-01-${String(day).padStart(2, '0')}`,
    end: `2026-01-${String(day).padStart(2, '0')}`,
    value: 1
  }))

  const chart = feedChartLines(points, 'bar-chart', 31)
  expect(chart[1]![0]).toBe('█')
  expect(chart[1]![1]).toBe('█')
  expect(chart[1]![15]).toBe(' ')
  expect(chart[1]![30]).toBe('█')
})

it('round-trips exact intraday timestamps and enforces version and precision boundaries', () => {
  const share = JSON.parse(readFileSync(new URL('../../../tests/fixtures/feed_share/v2.json', import.meta.url), 'utf8'))
  expect(decodeFeedMessage(encodeFeedMessage('YES prices', share)).share).toEqual(share)
  expect(validFeedShare({ ...share, version: 1 })).toBe(false)
  share.feeds[0].points[0].start = '2026-09-16'
  expect(validFeedShare(share)).toBe(false)
})

it.each(['polymarket', 'kalshi'])('shares %s contract history as raw YES percentages', venue => {
  const event = { venue, title: 'Example event', url: null } as Parameters<typeof sharePredictionMarket>[0]

  const outcome = { market_id: 'contract-yes', label: 'Selected outcome', prob: 0.6 } as Parameters<
    typeof sharePredictionMarket
  >[1]

  const history = [
    { ts: 1789567200, p: 0.38 },
    { ts: 1789569000, p: 0.44 }
  ]

  const share = sharePredictionMarket(event, outcome, history)!
  expect(share.version).toBe(2)
  expect(share.feeds[0]?.points.map(p => p.value)).toEqual([38, 44])
  expect(share.feeds[0]?.symbol).toBe('contract-yes')
  expect(share.feeds[0]?.kind).toBe('raw YES price')
  expect(sharePredictionMarket(event, outcome, [])).toBeNull()
  expect(sharePredictionMarket(event, outcome, [{ ts: 1, p: 1.1 }])).toBeNull()
  expect(sharePredictionMarket(event, outcome, [history[1]!, history[0]!])).toBeNull()
})

it.each([
  ['fred', '2026-01-01', '2026-01-31'],
  ['bls', '2026-01-01', '2026-01-31'],
  ['bea', '2026-01-01', '2026-03-31'],
  ['worldbank', '2025-01-01', '2025-12-31'],
  ['ecb', '2026-01-01', '2026-01-01'],
  ['bcb', '2026-01-01', '2026-01-01'],
  ['ibge', '2026-01-01', '2026-01-31'],
  ['openmeteo', '2026-09-16T14:00:00+00:00', '2026-09-16T14:00:00+00:00']
])('preserves %s observation periods and missing values', (provider, start, end) => {
  const share = shareQuote({
    provider,
    symbol: 'fixture',
    name: 'Fixture',
    category: 'test',
    asOf: 0,
    value: null,
    change: null,
    changePct: null,
    dated_history: [{ period_start: start, period_end: end, value: null, published_at: null, status: null }]
  })!

  expect(validFeedShare(share)).toBe(true)
  expect(share.feeds[0]?.points[0]).toEqual({
    start: start.length === 10 ? start : new Date(start).toISOString(),
    end: end.length === 10 ? end : new Date(end).toISOString(),
    value: null
  })
})

it.each([
  ['2026-02-30T12:00:00Z', false],
  ['2026-09-16T24:00:00Z', false],
  ['2026-09-16T12:00:00', false],
  ['September 16, 2026 12:00:00Z', false],
  ['2026-09-16T12:00:00+00:99', false],
  ['2026-09-16T12:00:00.123456+04:00', true],
  ['2026-09-16T12:00:00Z', true]
])('validates retrieval timestamp %s consistently with Python', (timestamp, valid) => {
  const share = fixture()
  share.feeds[0]!.retrieved_at = timestamp
  expect(validFeedShare(share)).toBe(valid)
})
