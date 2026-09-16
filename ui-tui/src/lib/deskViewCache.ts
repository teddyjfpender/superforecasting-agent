/** Connection-owned snapshots survive view unmounts; different backends never share data. */
import type {
  DataEvents,
  MarketCatalogResponse,
  MarketProviderStatus,
  NewsArticleResponse,
  NewsDeskResponse
} from '../protocol/generated.js'

import { tuiEnvValue } from './envAlias.js'
import { forecastHomeDir } from './forecastHome.js'
import type { QuotesTransport } from './marketFetch.js'
import type { QuoteCache } from './marketStore.js'
import type { ArticleCache } from './newsFeedCache.js'

export interface DeskViewCache {
  quotes: QuoteCache
  events: Record<string, DataEvents>
  statuses: Record<string, MarketProviderStatus>
  marketDesk?: MarketCatalogResponse
  newsDesk?: NewsDeskResponse
  articles: ArticleCache
  bodies: Map<string, { value: NewsArticleResponse; fetchedAt: number }>
}
const caches = new WeakMap<object, DeskViewCache>()
const owners = new WeakMap<object, { context: string; owner: object }>()

/** The gateway may be reattached in place. Keep old replies in their old scope. */
export function gatewayCacheOwner(gateway: object): object {
  const context = JSON.stringify([forecastHomeDir(), tuiEnvValue('GATEWAY_URL')])
  const existing = owners.get(gateway)

  if (existing?.context === context) {
    return existing.owner
  }

  const owner = {}
  owners.set(gateway, { context, owner })

  return owner
}

export function deskViewCache(gateway?: QuotesTransport): DeskViewCache {
  const owner = gateway && gatewayCacheOwner(gateway)
  const existing = owner && caches.get(owner)

  if (existing) {
    return existing
  }

  const cache: DeskViewCache = { quotes: {}, events: {}, statuses: {}, articles: {}, bodies: new Map() }

  if (gateway) {
    caches.set(owner!, cache)
  }

  return cache
}

/** Insertion-order bounds for connection-lived records; never mutate old snapshots. */
export function retainEntries<T>(record: Record<string, T>, limit: number): void {
  for (const key of Object.keys(record).slice(0, Math.max(0, Object.keys(record).length - limit))) {
    delete record[key]
  }
}
