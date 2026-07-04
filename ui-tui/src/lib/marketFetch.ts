import type { MarketSeries } from '../content/marketProviders.js'
import type { MarketQuotesResponse, MarketSeriesRef } from '../protocol/generated.js'

// Every market provider is parsed SERVER-SIDE (Arc C — DONE at C3): their series
// route through the gateway's `market.quotes` RPC (one shared key store + the
// estimator-honesty tests that could finally SEE the quote math) instead of a
// client parser. Yahoo — the highest-volume provider — was the last to move; with
// it there is ZERO fetch/parse logic left in the TUI. This file is the thin
// transport wrapper the plan promised: group the series, make ONE RPC call, hand
// the quotes back. No `fetch`, no per-provider parser, no pooling remains.
//
// DEFAULT_SERVER_SIDE is the plan's per-provider `marketdata.server_side` flag:
// an operator can revert a provider by dropping it from `opts.serverSide`, and
// that provider's series are simply excluded from the batch (there is no client
// path to fall back to — the fallback is "don't fetch it").
export const DEFAULT_SERVER_SIDE = ['yahoo', 'frankfurter', 'bea', 'coingecko', 'fred', 'bls', 'stooq'] as const

// A quote carries a latest value plus the change vs the prior close/observation
// where the provider gives us one. Mirrors the server `Quote` (a server quote is
// a field-for-field drop-in) with the display-only columns kept optional. THE
// LAW holds: a missing measurement is `null`, never a fabricated 0.
export interface MarketQuote {
  asOf: number // epoch ms, 0 if unknown
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
  request: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>
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
  // Providers to route through market.quotes; defaults to DEFAULT_SERVER_SIDE.
  serverSide?: readonly string[]
}

// Map a curated series to the RPC's ref shape (echoing display metadata + the
// BEA `line` override when present).
const toSeriesRef = (s: MarketSeries): MarketSeriesRef => ({
  category: s.category,
  ...((s as { line?: string }).line ? { line: (s as { line?: string }).line } : {}),
  name: s.name,
  provider: s.provider,
  symbol: s.symbol,
  ...(s.unit ? { unit: s.unit } : {})
})

// Fetch every server-side series in ONE `market.quotes` call and hand the quotes
// back via onBatch. A provider dropped from `serverSide` is excluded from the
// batch; with no gateway (or no server-side series) nothing is fetched. One
// provider failing server-side never blanks the tape — its series just come back
// with honest nulls (or absent), never a fabricated 0.
export const fetchQuotes = async (seriesList: MarketSeries[], opts: FetchOpts): Promise<void> => {
  const serverSide = new Set(opts.serverSide ?? DEFAULT_SERVER_SIDE)
  const serverSeries = seriesList.filter(s => serverSide.has(s.provider))

  if (!serverSeries.length || !opts.gw) {
    return
  }

  try {
    const res = await opts.gw.request<MarketQuotesResponse>('market.quotes', {
      series: serverSeries.map(toSeriesRef)
    })

    if (res?.quotes?.length) {
      // A server Quote is a structural drop-in for MarketQuote (same
      // field-for-field shape, honest nulls preserved).
      opts.onBatch(res.quotes as MarketQuote[])
    }
  } catch {
    // One provider (or the whole RPC) down never blanks the tape — the cache
    // keeps the prior values, exactly as the client's getJson→null did.
  }
}
