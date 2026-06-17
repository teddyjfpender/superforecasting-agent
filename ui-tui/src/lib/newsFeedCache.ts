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

// Drop the oldest 200 articles per feed and the whole entry if empty so the
// file can't grow without bound.
const MAX_PER_FEED = 200

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

    const trimmed: ArticleCache = {}

    for (const [url, entry] of Object.entries(cache)) {
      trimmed[normalizeFeedUrl(url)] = { ...entry, articles: entry.articles.slice(0, MAX_PER_FEED) }
    }

    writeFileSync(file, JSON.stringify(trimmed), { mode: 0o600 })

    return true
  } catch {
    return false
  }
}
