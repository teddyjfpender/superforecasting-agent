import type { MarketSeries } from '../content/marketProviders.js'
import type { MarketQuotesResponse, MarketSeriesRef } from '../protocol/generated.js'

// Providers parsed SERVER-SIDE (Arc C): their series route through the gateway's
// market.quotes RPC (one shared key store + honesty tests) instead of a client
// parser. C1 shipped FX (frankfurter) + BEA; C2 adds coingecko + fred + bls +
// stooq. The list is the plan's per-provider `marketdata.server_side` flag (an
// operator can revert a provider to its client path per release). Only yahoo
// (C3) keeps a client parser — anything NOT here is client-side.
export const DEFAULT_SERVER_SIDE = ['frankfurter', 'bea', 'coingecko', 'fred', 'bls', 'stooq'] as const

// Fetch + normalize quotes from each market provider. Pure parsers (one per
// provider response shape) are unit-tested; the network functions run in the
// TUI's Node runtime (global fetch). A quote carries a latest value plus the
// change vs the prior close/observation where the provider gives us one.

export interface MarketQuote {
  asOf: number // epoch ms, 0 if unknown
  category: string
  change: null | number
  changePct: null | number
  currency?: string
  dayHigh?: null | number
  dayLow?: null | number
  exchange?: string
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

const num = (v: unknown): null | number => {
  const n = typeof v === 'string' ? Number(v) : typeof v === 'number' ? v : NaN

  return Number.isFinite(n) ? n : null
}

const str = (v: unknown): string => (typeof v === 'string' ? v : '')

const withChange = (value: null | number, prev: null | number): { change: null | number; changePct: null | number } => {
  if (value === null || prev === null) {
    return { change: null, changePct: null }
  }

  const change = value - prev

  return { change, changePct: prev ? (change / prev) * 100 : null }
}

// ---- pure parsers --------------------------------------------------------

export const parseYahoo = (chart: unknown, series: MarketSeries): MarketQuote => {
  const result = (chart as { chart?: { result?: { indicators?: { quote?: { close?: unknown[] }[] }; meta?: Record<string, unknown> }[] } })
    ?.chart?.result?.[0]

  const meta = result?.meta ?? {}
  const value = num(meta.regularMarketPrice)
  const prev = num(meta.chartPreviousClose) ?? num(meta.previousClose)
  const { change, changePct } = withChange(value, prev)

  const history = (result?.indicators?.quote?.[0]?.close ?? [])
    .map(c => num(c))
    .filter((c): c is number => c !== null)

  return {
    asOf: (num(meta.regularMarketTime) ?? 0) * 1000,
    category: series.category,
    change,
    changePct,
    currency: str(meta.currency) || undefined,
    dayHigh: num(meta.regularMarketDayHigh),
    dayLow: num(meta.regularMarketDayLow),
    exchange: str(meta.fullExchangeName) || str(meta.exchangeName) || undefined,
    history: history.length > 1 ? history.slice(-40) : undefined,
    name: str(meta.shortName) || str(meta.longName) || series.name,
    prevClose: prev,
    provider: 'yahoo',
    symbol: series.symbol,
    unit: series.unit,
    value,
    volume: num(meta.regularMarketVolume),
    week52High: num(meta.fiftyTwoWeekHigh),
    week52Low: num(meta.fiftyTwoWeekLow)
  }
}

// Frankfurter (FX), CoinGecko, FRED, BLS, BEA (NIPA), and Stooq are all parsed
// SERVER-SIDE (forecasting/marketdata) — their client parsers + contract tests
// moved to Python (Arc C1 + C2), where the estimator-honesty taxonomy can
// finally SEE the quote math (the fabricated BEA 0.0000 lived here in TS
// precisely because it could not). Their series route through
// gw.request('market.quotes'); see fetchQuotes below. Only yahoo (C3) still has
// a client parser.

// ---- network -------------------------------------------------------------

const getJson = async (url: string, init?: RequestInit, timeoutMs = 12000): Promise<unknown> => {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const r = await fetch(url, {
      ...init,
      headers: { 'User-Agent': 'Outrider/1.0', ...(init?.headers ?? {}) },
      signal: controller.signal
    })

    if (!r.ok) {
      return null
    }

    return await r.json()
  } catch {
    return null
  } finally {
    clearTimeout(timer)
  }
}

const pool = async <T>(items: T[], n: number, fn: (item: T) => Promise<void>): Promise<void> => {
  const queue = [...items]

  const worker = async () => {
    for (;;) {
      const item = queue.shift()

      if (item === undefined) {
        return
      }

      await fn(item)
    }
  }

  await Promise.all(Array.from({ length: Math.max(1, Math.min(n, items.length)) }, worker))
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
  // SERVER-SIDE from the one shared store (Arc C). Kept optional so the C3
  // key-flow rehome can drop it without a wire change.
  getKey?: (envVar: string) => string
  // The gateway handle for SERVER-SIDE providers. Absent (no gateway) → those
  // providers are skipped, exactly as the PM section degrades without a gateway.
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

// Fetch all the given series, grouped by provider, emitting quotes per group as
// they arrive. Missing API keys for keyed providers are skipped (the caller
// surfaces which ones need keys).
export const fetchQuotes = async (seriesList: MarketSeries[], opts: FetchOpts): Promise<void> => {
  const byProvider = new Map<string, MarketSeries[]>()

  for (const s of seriesList) {
    byProvider.set(s.provider, [...(byProvider.get(s.provider) ?? []), s])
  }

  const serverSide = new Set(opts.serverSide ?? DEFAULT_SERVER_SIDE)
  // A provider still handled client-side: not routed server-side (a provider in
  // `serverSide` with no gateway is simply skipped — no client parser remains).
  const client = (provider: string): MarketSeries[] | undefined =>
    serverSide.has(provider) ? undefined : byProvider.get(provider)

  const jobs: Promise<void>[] = []

  // ── SERVER-SIDE providers (FX + BEA + coingecko/fred/bls/stooq): ONE
  //    market.quotes RPC batches every server-side series in a single call. ──
  const serverSeries = seriesList.filter(s => serverSide.has(s.provider))

  if (serverSeries.length && opts.gw) {
    jobs.push(
      (async () => {
        try {
          const res = await opts.gw!.request<MarketQuotesResponse>('market.quotes', {
            series: serverSeries.map(toSeriesRef)
          })

          if (res?.quotes?.length) {
            // A server Quote is a structural drop-in for MarketQuote (same
            // field-for-field shape, honest nulls preserved).
            opts.onBatch(res.quotes as MarketQuote[])
          }
        } catch {
          // One provider down never blanks the tape (parity with getJson→null).
        }
      })()
    )
  }

  // ── CLIENT-SIDE providers (yahoo only, until C3) ──────────────────────────
  const yahoo = client('yahoo')

  if (yahoo?.length) {
    jobs.push(
      pool(yahoo, 6, async s => {
        const json = await getJson(
          `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(s.symbol)}?range=1mo&interval=1d`
        )

        if (json) {
          opts.onBatch([parseYahoo(json, s)])
        }
      })
    )
  }

  await Promise.all(jobs)
}
