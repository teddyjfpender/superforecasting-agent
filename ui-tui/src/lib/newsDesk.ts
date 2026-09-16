import type { GatewayClient } from '../gatewayClient.js'
import type { NewsArticleResponse } from '../protocol/generated.js'

import { deskViewCache, gatewayCacheOwner, retainEntries } from './deskViewCache.js'
import { type Article, type FetchResult, isNhcStatusPlaceholder, parseFeed } from './newsFeedFetch.js'
import { normalizeFeedUrl } from './newsFeedStore.js'

export const NEWS_STALE_MS = 10 * 60 * 1000
const pendingFeeds = new WeakMap<object, Map<string, Promise<FetchResult>>>()

/** A view can go away while this request finishes; the connection still owns its result. */
export async function fetchBackendFeed(
  gw: GatewayClient,
  url: string,
  title: string,
  force = false
): Promise<FetchResult> {
  const cache = deskViewCache(gw)
  const key = normalizeFeedUrl(url)
  const cached = cache.articles[key]

  if (!force && cached && (Date.now() - cached.fetchedAt < NEWS_STALE_MS || Date.now() < (cached.retryAt ?? 0))) {
    return { articles: cached.articles, error: cached.error ?? null }
  }

  const owner = gatewayCacheOwner(gw)
  let pending = pendingFeeds.get(owner)

  if (!pending) {
    pending = new Map()
    pendingFeeds.set(owner, pending)
  }

  const existing = pending.get(key)

  if (existing) {
    return existing
  }

  const request = (async (): Promise<FetchResult> => {
    try {
      const result = await gw.request('news.feed', { url })
      const articles = parseFeed(result.xml, url, title)

      if (!articles.length) {
        throw new Error('No articles returned by this feed')
      }

      cache.articles[key] = { articles, fetchedAt: Date.now() }
      retainEntries(cache.articles, 700)

      return { articles, error: null }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Feed unavailable'

      // Retain acquisition time and back off failures across repeated navigation.
      cache.articles[key] = {
        articles: cached?.articles ?? [],
        fetchedAt: cached?.fetchedAt ?? 0,
        error: message,
        retryAt: Date.now() + 60_000
      }
      retainEntries(cache.articles, 700)

      return { articles: cached?.articles ?? [], error: message }
    }
  })().finally(() => pending!.delete(key))

  pending.set(key, request)

  return request
}

/** Exact source-link duplicates collapse; related reporting stays independent. */
export function uniqueArticles(articles: Article[], now = Date.now()): Article[] {
  const seen = new Set<string>()

  return articles
    .filter(article => {
      // Also clean previously persisted feed caches, without rewriting them.
      if (isNhcStatusPlaceholder(article)) {
        return false
      }

      let key = `${article.feedUrl}:${article.title}`

      if (article.link) {
        try {
          const url = new URL(article.link)
          url.hash = ''

          for (const name of [...url.searchParams.keys()]) {
            if (name.startsWith('utm_') || ['fbclid', 'gclid'].includes(name)) {
              url.searchParams.delete(name)
            }
          }

          key = url.href
        } catch {
          key = article.link
        }
      }

      if (seen.has(key)) {
        return false
      }

      seen.add(key)

      return true
    })
    .sort((a, b) => {
      // Future publication claims remain inspectable, but cannot pin the feed.
      const published = (date: number) => (Number.isFinite(date) && date > 0 && date <= now ? date : 0)

      return published(b.publishedAt) - published(a.publishedAt)
    })
}

const pendingArticles = new WeakMap<object, Map<string, Promise<NewsArticleResponse>>>()

export function fetchBackendArticle(gw: GatewayClient, url: string): Promise<NewsArticleResponse> {
  const cache = deskViewCache(gw)
  const cached = cache.bodies.get(url)

  if (cached && Date.now() - cached.fetchedAt < 30 * 60 * 1000) {
    return Promise.resolve(cached.value)
  }

  const owner = gatewayCacheOwner(gw)
  let pending = pendingArticles.get(owner)

  if (!pending) {
    pending = new Map()
    pendingArticles.set(owner, pending)
  }

  const existing = pending.get(url)

  if (existing) {
    return existing
  }

  const request = gw
    .request('news.article', { url })
    .then(value => {
      if (value.status !== 'unavailable') {
        cache.bodies.delete(url)
        cache.bodies.set(url, { value, fetchedAt: Date.now() })

        while (cache.bodies.size > 40) {
          cache.bodies.delete(cache.bodies.keys().next().value!)
        }
      }

      return value
    })
    .finally(() => pending!.delete(url))

  pending.set(url, request)

  return request
}
