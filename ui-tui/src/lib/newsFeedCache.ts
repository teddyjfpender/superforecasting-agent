import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { forecastHomeDir } from './forecastHome.js'
import type { Article } from './newsFeedFetch.js'
import { normalizeFeedUrl } from './newsFeedStore.js'

// On-disk cache of fetched articles, keyed by normalized feed URL, so reopening
// News paints instantly while a background refresh runs. Best-effort: any
// failure just means a cold start.

export interface CachedFeed {
  articles: Article[]
  error?: string
  fetchedAt: number
}

export type ArticleCache = Record<string, CachedFeed>

const cacheFile = (dir = forecastHomeDir()) => join(dir, 'news_cache.json')

// Bounds so the cache can't grow without limit: at most 200 articles per feed,
// at most 400 feeds total, and (optionally) drop entries older than a TTL.
const MAX_PER_FEED = 200
const MAX_FEEDS = 400

export interface PruneOptions {
  keep?: Set<string> // normalized feed URLs to retain — others are dropped (e.g. unsubscribed)
  maxAgeMs?: number // drop entries last fetched longer ago than this (0 = no age limit)
  maxFeeds?: number
  maxPerFeed?: number
  now?: number
}

// Prune the cache: drop feeds that aren't in `keep` (unsubscribed), drop entries
// past the age limit, cap articles per feed, and cap total feeds (keeping the
// most-recently-fetched). Pure — returns a new cache.
export const pruneArticleCache = (cache: ArticleCache, options: PruneOptions = {}): ArticleCache => {
  const { keep, maxAgeMs = 0, maxFeeds = MAX_FEEDS, maxPerFeed = MAX_PER_FEED, now = Date.now() } = options

  let entries = Object.entries(cache)
    .map(([url, entry]) => [normalizeFeedUrl(url), entry] as const)
    .filter(([url, entry]) => {
      if (keep && !keep.has(url)) {
        return false
      }

      if (maxAgeMs > 0 && now - (entry.fetchedAt || 0) > maxAgeMs) {
        return false
      }

      return Boolean(entry) && Array.isArray(entry.articles)
    })

  if (entries.length > maxFeeds) {
    entries = [...entries].sort((a, b) => (b[1].fetchedAt || 0) - (a[1].fetchedAt || 0)).slice(0, maxFeeds)
  }

  const out: ArticleCache = {}

  for (const [url, entry] of entries) {
    out[url] = { ...entry, articles: entry.articles.slice(0, maxPerFeed) }
  }

  return out
}

export const loadArticleCache = (file = cacheFile()): ArticleCache => {
  try {
    const data: unknown = JSON.parse(readFileSync(file, 'utf8'))

    if (!data || typeof data !== 'object') {
      return {}
    }

    return data as ArticleCache
  } catch {
    return {}
  }
}

export const saveArticleCache = (cache: ArticleCache, file = cacheFile()): boolean => {
  try {
    const dir = forecastHomeDir()

    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true })
    }

    // Always enforce the per-feed + total-feed caps on write, even if the
    // caller didn't prune.
    writeFileSync(file, JSON.stringify(pruneArticleCache(cache)), { mode: 0o600 })

    return true
  } catch {
    return false
  }
}
