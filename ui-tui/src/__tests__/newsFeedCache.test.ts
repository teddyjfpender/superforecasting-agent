import { describe, expect, it } from 'vitest'

import { type ArticleCache, pruneArticleCache } from '../lib/newsFeedCache.js'
import type { Article } from '../lib/newsFeedFetch.js'

const article = (i: number): Article => ({
  feedTitle: 'F',
  feedUrl: 'u',
  link: `https://x/${i}`,
  publishedAt: i,
  summary: '',
  title: `a${i}`
})

const feed = (n: number, fetchedAt = 1000): { articles: Article[]; fetchedAt: number } => ({
  articles: Array.from({ length: n }, (_, i) => article(i)),
  fetchedAt
})

describe('pruneArticleCache', () => {
  it('drops feeds not in the keep set (unsubscribed)', () => {
    const cache: ArticleCache = {
      'a.com/rss': feed(3),
      'b.com/rss': feed(3),
      'c.com/rss': feed(3)
    }

    const out = pruneArticleCache(cache, { keep: new Set(['a.com/rss', 'c.com/rss']) })
    expect(Object.keys(out).sort()).toEqual(['a.com/rss', 'c.com/rss'])
  })

  it('normalizes URLs when matching the keep set', () => {
    const cache: ArticleCache = { 'https://A.com/rss/': feed(2) }
    const out = pruneArticleCache(cache, { keep: new Set(['a.com/rss']) })
    expect(out['a.com/rss']).toBeDefined()
  })

  it('caps articles per feed', () => {
    const out = pruneArticleCache({ 'a.com': feed(500) }, { maxPerFeed: 10 })
    expect(out['a.com'].articles).toHaveLength(10)
  })

  it('drops entries older than the age limit', () => {
    const cache: ArticleCache = { fresh: feed(1, 9_000), stale: feed(1, 1_000) }
    const out = pruneArticleCache(cache, { maxAgeMs: 5_000, now: 10_000 })
    expect(Object.keys(out)).toEqual(['fresh'])
  })

  it('caps total feeds, keeping the most-recently fetched', () => {
    const cache: ArticleCache = {}

    for (let i = 0; i < 10; i++) {
      cache[`feed${i}.com`] = feed(1, i * 100)
    }

    const out = pruneArticleCache(cache, { maxFeeds: 3 })
    expect(Object.keys(out)).toHaveLength(3)
    // newest fetchedAt (900/800/700) survive
    expect(out['feed9.com']).toBeDefined()
    expect(out['feed0.com']).toBeUndefined()
  })
})
