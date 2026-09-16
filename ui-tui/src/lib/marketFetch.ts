import type { MarketSeries } from '../content/marketProviders.js'
import type { ObservationComparison, RpcRequest } from '../protocol/generated.js'
import type { DataEvents, MarketProviderStatus, MarketSeriesRef } from '../protocol/generated.js'

import { deskViewCache, gatewayCacheOwner, retainEntries } from './deskViewCache.js'
import { quoteKey } from './marketStore.js'

// The connected backend owns all fetching, credentials and parsing. This
// adapter limits provider RPC concurrency and paints each completed group.
// Retained for compatibility tests; unspecified serverSide allows the catalog.
export const DEFAULT_SERVER_SIDE = ['yahoo', 'frankfurter', 'bea', 'coingecko', 'fred', 'bls', 'stooq'] as const

// A quote carries a latest value plus the change vs the prior close/observation
// where the provider gives us one. Mirrors the server `Quote` (a server quote is
// a field-for-field drop-in) with the display-only columns kept optional. THE
// LAW holds: a missing measurement is `null`, never a fabricated 0.
export interface MarketQuote {
  comparison?: ObservationComparison | null
  last_movement?: ObservationComparison | null
  asOf: number // epoch ms, 0 if unknown
  retrieved_at?: string | null
  refresh_seconds?: number
  kind?: string
  published_at?: string | null
  issue_time?: string | null
  valid_from?: string | null
  valid_until?: string | null
  revision_policy?: string
  source_url?: string | null
  source_family?: string | null
  dated_history?: {
    period_start: string
    period_end: string
    value: number | null
    published_at: string | null
    status: string | null
  }[]
  category: string
  change: null | number
  changePct: null | number
  currency?: null | string
  dayHigh?: null | number
  dayLow?: null | number
  exchange?: null | string
  // Recent closes (oldest→newest) for a sparkline in the detail pane.
  history?: number[]
  name: string
  prevClose?: null | number
  provider: string
  symbol: string
  unit?: string
  value: null | number
  volume?: null | number
  week52High?: null | number
  week52Low?: null | number
}

// The minimal gateway surface fetchQuotes needs — just `request`. Kept
// structural (not the full GatewayClient) so the lib stays decoupled and is
// trivially stubbable in tests; GatewayClient satisfies it by shape.
export interface QuotesTransport {
  request: RpcRequest
}

export interface FetchOpts {
  // Legacy env-key reader — retained for the caller (marketsView) but no longer
  // read here: every keyed provider (fred/bls/bea) now resolves its key
  // SERVER-SIDE from the one shared store (Arc C). Kept optional so the caller
  // can drop it without a wire change.
  getKey?: (envVar: string) => string
  // The gateway handle. Absent (no gateway) → nothing is fetched, exactly as the
  // pm section degrades without a gateway.
  gw?: QuotesTransport
  onBatch: (quotes: MarketQuote[]) => void
  onEvents?: (data: DataEvents) => void
  onStatus?: (status: MarketProviderStatus[]) => void
  signal?: AbortSignal
  // Optional explicit provider allowlist; absent means all selected providers.
  serverSide?: readonly string[]
}

// Map a curated series to the RPC's ref shape (echoing display metadata + the
// BEA `line` override when present).
const toSeriesRef = (s: MarketSeries): MarketSeriesRef => ({
  category: s.category,
  ...(s.catalog_id ? { catalog_id: s.catalog_id } : {}),
  ...((s as { line?: string }).line ? { line: (s as { line?: string }).line } : {}),
  name: s.name,
  provider: s.provider,
  symbol: s.symbol,
  ...(s.unit ? { unit: s.unit } : {})
})

// Coalesce overlapping requests across rapid topic switches and view remounts.
const pendingQuotes = new WeakMap<object, Map<string, Promise<Awaited<ReturnType<typeof requestQuotes>>>>>()

const requestQuotes = (gateway: QuotesTransport, series: MarketSeries[]) =>
  gateway.request('market.quotes', { series: series.map(toSeriesRef) })

async function retainedQuotes(gateway: QuotesTransport, series: MarketSeries[]) {
  const owner = gatewayCacheOwner(gateway)
  const cache = deskViewCache(gateway)
  let pending = pendingQuotes.get(owner)

  if (!pending) {
    pending = new Map()
    pendingQuotes.set(owner, pending)
  }

  const key = JSON.stringify(series.map(toSeriesRef).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))))
  let request = pending.get(key)

  if (!request) {
    request = requestQuotes(gateway, series)
      .then(result => {
        for (const quote of result.quotes) {
          cache.quotes[quoteKey(quote.provider, quote.symbol)] = quote
        }

        retainEntries(cache.quotes, 2000)

        for (const status of result.statuses ?? []) {
          cache.statuses[status.provider] = status
        }

        return result
      })
      .finally(() => pending!.delete(key))
    pending.set(key, request)
  }

  return request
}

// Cancellation discards late responses and stops scheduling additional groups.
// Already-running backend refreshes remain backend-owned and may warm its cache.
export const fetchQuotes = async (seriesList: MarketSeries[], opts: FetchOpts): Promise<void> => {
  const gateway = opts.gw

  if (!gateway) {
    return
  }

  const allowed = opts.serverSide ? new Set(opts.serverSide) : null
  const groups = new Map<string, MarketSeries[]>()

  for (const series of seriesList) {
    if (allowed && !allowed.has(series.provider)) {
      continue
    }

    const group = groups.get(series.provider) ?? []
    group.push(series)
    groups.set(series.provider, group)
  }

  // Each provider paints as it finishes. Bound concurrent requests; providers
  // own batching and quotas, and one slow source cannot hold the whole screen.
  const queue = [...groups.entries()]

  const worker = async () => {
    while (queue.length && !opts.signal?.aborted) {
      const next = queue.shift()

      if (!next) {
        return
      }

      const [provider, series] = next

      try {
        if (series[0]?.kind === 'event') {
          for (const ref of series) {
            if (opts.signal?.aborted || !ref.catalog_id) {
              break
            }

            const cache = deskViewCache(gateway)
            const result = await gateway.request('market.events.list', { series_id: ref.catalog_id })

            if (result.data) {
              const cache = deskViewCache(gateway)
              cache.events[result.data.series_id] = result.data
              retainEntries(cache.events, 100)
            }

            if (opts.signal?.aborted) {
              return
            }

            if (result.data) {
              opts.onEvents?.(result.data)
            }

            opts.onStatus?.([result.status])
          }

          continue
        }

        const result = await retainedQuotes(gateway, series)

        if (opts.signal?.aborted) {
          return
        }

        if (result.quotes.length) {
          opts.onBatch(result.quotes)
        }

        opts.onStatus?.(result.statuses ?? [])
      } catch {
        if (!opts.signal?.aborted) {
          opts.onStatus?.([
            { provider, status: 'unavailable', message: 'Unable to retrieve data. Try refreshing.', retry_after: null }
          ])
        }
      }
    }
  }

  await Promise.all(Array.from({ length: Math.min(4, queue.length) }, worker))
}
