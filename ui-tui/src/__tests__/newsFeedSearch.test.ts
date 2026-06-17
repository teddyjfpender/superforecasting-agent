import { describe, expect, it } from 'vitest'

import { FEED_CATALOG } from '../content/newsFeedCatalog.js'
import { ALL_CATEGORY, scoreFeed, searchFeeds } from '../lib/newsFeedSearch.js'

describe('feed catalog', () => {
  it('is non-trivial and well-formed', () => {
    expect(FEED_CATALOG.length).toBeGreaterThan(100)

    for (const f of FEED_CATALOG.slice(0, 50)) {
      expect(f.url).toMatch(/^https?:\/\//)
      expect(f.title.length).toBeGreaterThan(0)
      expect(f.category.length).toBeGreaterThan(0)
    }
  })
})

describe('searchFeeds — ranking', () => {
  it('returns the whole catalog (or category pool) for an empty query', () => {
    expect(searchFeeds('')).toHaveLength(FEED_CATALOG.length)
    const sci = searchFeeds('', 'Science')
    expect(sci.length).toBeGreaterThan(0)
    expect(sci.every(f => f.category === 'Science')).toBe(true)
  })

  it('ranks a title/category match to the top', () => {
    const res = searchFeeds('science')
    expect(res.length).toBeGreaterThan(0)
    // The Science category should dominate the head of the results.
    expect(res.slice(0, 5).some(f => f.category === 'Science')).toBe(true)
  })

  it('filters by category and query together', () => {
    const res = searchFeeds('news', 'Technology')
    expect(res.every(f => f.category === 'Technology')).toBe(true)
  })

  it('returns nothing for a query with no matches anywhere', () => {
    expect(searchFeeds('zzzxqqnotathing')).toHaveLength(0)
  })
})

describe('searchFeeds — semantic (synonym) recall', () => {
  it('surfaces Football feeds for "soccer"', () => {
    const res = searchFeeds('soccer')
    expect(res.some(f => f.category === 'Football')).toBe(true)
  })

  it('surfaces Markets/Finance/Business for "investing"', () => {
    const res = searchFeeds('investing')
    expect(res.some(f => ['Business', 'Finance', 'Markets'].includes(f.category))).toBe(true)
  })

  it('surfaces tech/programming for "AI"', () => {
    const res = searchFeeds('ai')
    expect(res.some(f => ['Programming', 'Technology'].includes(f.category))).toBe(true)
  })
})

describe('scoreFeed', () => {
  it('scores an exact title higher than a description-only hit', () => {
    const feed = { category: 'Science', description: 'about space and rockets', title: 'space', url: 'https://x.com' }
    const other = { category: 'News', description: 'covers space launches', title: 'Daily Wire', url: 'https://y.com' }
    expect(scoreFeed(feed, ['space'], [])).toBeGreaterThan(scoreFeed(other, ['space'], []))
  })

  it('awards synonym (intent) points without a literal match', () => {
    const feed = { category: 'Football', description: 'match reports', title: 'Goal', url: 'https://z.com' }
    // "soccer" never appears, but the Football synonym should still score it.
    expect(scoreFeed(feed, [], ['football'])).toBeGreaterThan(0)
  })
})

describe('exports', () => {
  it('ALL_CATEGORY is the sentinel for the unfiltered pool', () => {
    expect(searchFeeds('', ALL_CATEGORY)).toHaveLength(FEED_CATALOG.length)
  })
})
