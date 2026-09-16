import { afterEach, expect, it, vi } from 'vitest'

import type { MarketSeries } from '../content/marketProviders.js'
import type { GatewayClient } from '../gatewayClient.js'
import { deskViewCache, retainEntries } from '../lib/deskViewCache.js'
import { fetchQuotes } from '../lib/marketFetch.js'
import { fetchBackendArticle, fetchBackendFeed, NEWS_STALE_MS } from '../lib/newsDesk.js'
import { normalizeFeedUrl } from '../lib/newsFeedStore.js'

const url = 'https://example.com/rss'

const xml =
  '<rss><channel><item><title>Inflation release</title><link>https://example.com/article</link><description>Monthly data</description></item></channel></rss>'

const gateway = (request = vi.fn()) => ({ request }) as unknown as GatewayClient
const series: MarketSeries = { provider: 'ibge', symbol: '1737/63', name: 'IPCA', category: 'inflation' }
afterEach(() => vi.useRealTimers())

it('retains state on a connection without leaking it into another profile or backend', () => {
  const a = gateway(),
    b = gateway()

  deskViewCache(a).articles.x = { articles: [], fetchedAt: 1 }
  expect(deskViewCache(a).articles.x?.fetchedAt).toBe(1)
  expect(deskViewCache(b).articles).toEqual({})
  expect(deskViewCache()).not.toBe(deskViewCache())
  const entries = { a: 1, b: 2, c: 3 }
  retainEntries(entries, 2)
  expect(entries).toEqual({ b: 2, c: 3 })
})
it('coalesces a market request across navigation; late replies warm only its connection', async () => {
  let resolve!: (value: unknown) => void

  const request = vi.fn(
    () =>
      new Promise(r => {
        resolve = r
      })
  )

  const gw = gateway(request)
  const abort = new AbortController()

  const oldPaint = vi.fn(),
    newPaint = vi.fn()

  const first = fetchQuotes([series], { gw, signal: abort.signal, onBatch: oldPaint })
  abort.abort()
  const second = fetchQuotes([series], { gw, onBatch: newPaint })
  expect(request).toHaveBeenCalledTimes(1)
  resolve({ quotes: [{ ...series, value: -0.32 }], statuses: [] })
  await Promise.all([first, second])
  expect(oldPaint).not.toHaveBeenCalled()
  expect(newPaint).toHaveBeenCalledTimes(1)
  expect(Object.values(deskViewCache(gw).quotes)[0]?.value).toBe(-0.32)
  expect(deskViewCache(gateway()).quotes).toEqual({})
})
it('retains successful news until expiry, refreshes explicitly, preserves stale data after failure', async () => {
  vi.useFakeTimers()
  const request = vi.fn().mockResolvedValue({ xml, url })
  const gw = gateway(request)
  const first = await fetchBackendFeed(gw, url, 'Source')
  await fetchBackendFeed(gw, url, 'Source')
  expect(request).toHaveBeenCalledTimes(1)
  await fetchBackendFeed(gw, url, 'Source', true)
  expect(request).toHaveBeenCalledTimes(2)
  const timestamp = deskViewCache(gw).articles[normalizeFeedUrl(url)]!.fetchedAt
  vi.advanceTimersByTime(NEWS_STALE_MS + 1)
  request.mockRejectedValue(new Error('quota'))
  expect(await fetchBackendFeed(gw, url, 'Source')).toEqual({ articles: first.articles, error: 'quota' })
  expect(deskViewCache(gw).articles[normalizeFeedUrl(url)]!.fetchedAt).toBe(timestamp)
})
it('coalesces news and reader requests, including completion after leaving the view', async () => {
  let resolve!: (value: unknown) => void

  const request = vi.fn(
    () =>
      new Promise(r => {
        resolve = r
      })
  )

  const gw = gateway(request)
  const first = fetchBackendFeed(gw, url, 'Source')
  const second = fetchBackendFeed(gw, url, 'Source')
  expect(request).toHaveBeenCalledTimes(1)
  resolve({ xml, url })
  await Promise.all([first, second])
  expect(deskViewCache(gw).articles[normalizeFeedUrl(url)]!.articles[0]?.title).toBe('Inflation release')

  const a = fetchBackendArticle(gw, url),
    b = fetchBackendArticle(gw, url)

  expect(request).toHaveBeenCalledTimes(2)
  resolve({ text: 'Full article', url, status: 'article', message: '' })
  await Promise.all([a, b])
  expect((await fetchBackendArticle(gw, url)).text).toBe('Full article')
  expect(request).toHaveBeenCalledTimes(2)
})

it('retains prediction browse snapshots with short TTL, explicit refresh and independent venues', async () => {
  const { retainedPMList, peekPMList } = await import('../lib/pmListCache.js')
  const request = vi.fn().mockResolvedValue({ events: [], stale: false })
  const gw = gateway(request)
  await retainedPMList(gw, 'all')
  await retainedPMList(gw, 'all')
  expect(request).toHaveBeenCalledTimes(1)
  expect(peekPMList(gw, 'all')).toBeDefined()
  await retainedPMList(gw, 'kalshi')
  await retainedPMList(gw, 'all', true)
  expect(request).toHaveBeenCalledTimes(3)
  expect(peekPMList(gateway(), 'all')).toBeUndefined()
})

it('isolates in-place reattachment and keeps late replies in the original scope', async () => {
  let resolve!: (value: unknown) => void

  const request = vi.fn(
    () =>
      new Promise(r => {
        resolve = r
      })
  )

  const gw = gateway(request)
  vi.stubEnv('SUPERFORECASTING_AGENT_TUI_GATEWAY_URL', 'ws://first.example')
  const original = deskViewCache(gw)
  const first = fetchQuotes([series], { gw, onBatch: () => {} })
  vi.stubEnv('SUPERFORECASTING_AGENT_TUI_GATEWAY_URL', 'ws://second.example')
  const replacement = deskViewCache(gw)
  expect(replacement).not.toBe(original)
  resolve({ quotes: [{ ...series, value: -0.32 }], statuses: [] })
  await first
  expect(Object.values(original.quotes)[0]?.value).toBe(-0.32)
  expect(replacement.quotes).toEqual({})
  vi.stubEnv('SUPERFORECASTING_AGENT_HOME', '/tmp/another-cache-profile')
  expect(deskViewCache(gw)).not.toBe(replacement)
  vi.unstubAllEnvs()
})

it('retries after a synchronous transport startup failure instead of retaining a settled pending request', async () => {
  const request = vi
    .fn()
    .mockImplementationOnce(() => {
      throw new Error('startup failed')
    })
    .mockResolvedValue({ xml, url })

  const gw = gateway(request)
  expect((await fetchBackendFeed(gw, url, 'Source')).error).toBe('startup failed')
  expect((await fetchBackendFeed(gw, url, 'Source', true)).error).toBeNull()
  expect(request).toHaveBeenCalledTimes(2)
})
