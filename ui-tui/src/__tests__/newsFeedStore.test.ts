import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterAll, describe, expect, it } from 'vitest'

import {
  ensureFeedUrlScheme,
  feedHost,
  isFeedUrl,
  loadSubscribedFeeds,
  normalizeFeedUrl,
  saveSubscribedFeeds,
  type SubscribedFeed
} from '../lib/newsFeedStore.js'

const tmp = mkdtempSync(join(tmpdir(), 'news-feeds-'))

afterAll(() => rmSync(tmp, { force: true, recursive: true }))

describe('url helpers', () => {
  it('normalizes protocol + trailing slash for de-dup', () => {
    expect(normalizeFeedUrl('https://Example.com/feed/')).toBe('example.com/feed')
    expect(normalizeFeedUrl('http://example.com/feed')).toBe(normalizeFeedUrl('https://example.com/feed/'))
  })

  it('detects feed-like URLs and rejects prose', () => {
    expect(isFeedUrl('https://example.com/rss.xml')).toBe(true)
    expect(isFeedUrl('example.com/feed')).toBe(true)
    expect(isFeedUrl('hacker news')).toBe(false)
    expect(isFeedUrl('ai')).toBe(false)
  })

  it('adds a scheme when missing', () => {
    expect(ensureFeedUrlScheme('example.com/feed')).toBe('https://example.com/feed')
    expect(ensureFeedUrlScheme('http://example.com')).toBe('http://example.com')
  })

  it('extracts a clean host', () => {
    expect(feedHost('https://www.theguardian.com/world/rss')).toBe('theguardian.com')
    expect(feedHost('feeds.bbci.co.uk/news/rss.xml')).toBe('feeds.bbci.co.uk')
  })
})

describe('subscription persistence', () => {
  it('round-trips feeds through the JSON file', () => {
    const file = join(tmp, 'sub.json')

    const feeds: SubscribedFeed[] = [
      { addedAt: 1, category: 'Science', title: 'Nature', url: 'https://www.nature.com/nature.rss' },
      { addedAt: 2, category: 'Custom', custom: true, title: 'mine', url: 'https://mine.example/feed' }
    ]

    expect(saveSubscribedFeeds(feeds, file)).toBe(true)

    const loaded = loadSubscribedFeeds(file)
    expect(loaded).toHaveLength(2)
    expect(loaded[0].title).toBe('Nature')
    expect(loaded[1].custom).toBe(true)
  })

  it('returns [] for a missing file', () => {
    expect(loadSubscribedFeeds(join(tmp, 'does-not-exist.json'))).toEqual([])
  })

  it('backfills a missing title from the host', () => {
    const file = join(tmp, 'backfill.json')
    saveSubscribedFeeds([{ addedAt: 0, category: 'News', title: '', url: 'https://x.example/rss' }], file)
    expect(loadSubscribedFeeds(file)[0].title).toBe('x.example')
  })
})
