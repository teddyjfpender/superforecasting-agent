import type { GatewayClient } from '../gatewayClient.js'

import { type Article, type FetchResult, parseFeed } from './newsFeedFetch.js'

/** The connected backend owns networking, so a VPS desk uses its own access. */
export async function fetchBackendFeed(gw: GatewayClient, url: string, title: string): Promise<FetchResult> {
  try {
    const result = await gw.request('news.feed', { url })
    const articles = parseFeed(result.xml, url, title)

    return { articles, error: articles.length ? null : 'No articles returned by this feed' }
  } catch (error) {
    return { articles: [], error: error instanceof Error ? error.message : 'Feed unavailable' }
  }
}

/** Exact source-link duplicates collapse; related reporting stays independent. */
export function uniqueArticles(articles: Article[]): Article[] {
  const seen = new Set<string>()

  return articles
    .filter(article => {
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
    .sort((a, b) => b.publishedAt - a.publishedAt)
}
