import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import { decodeFeedMessage, encodeFeedMessage, presentFeedShare, shareQuote, validFeedShare } from '../lib/feedShare.js'
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
      Object.assign(raw, { version: 2 })
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
    const text = 'Text\n```sfa-feed\n{"version":2}\n```'
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
