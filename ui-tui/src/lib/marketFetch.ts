import type { MarketSeries } from '../content/marketProviders.js'
import type { MarketQuotesResponse, MarketSeriesRef } from '../protocol/generated.js'

// Providers parsed SERVER-SIDE (Arc C): their series route through the gateway's
// market.quotes RPC (one shared key store + honesty tests) instead of a client
// parser. FX (frankfurter) + BEA first; the list is the plan's per-provider
// `marketdata.server_side` flag. Anything NOT here keeps its client parser.
export const DEFAULT_SERVER_SIDE = ['frankfurter', 'bea'] as const

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

// Frankfurter (FX) is now parsed SERVER-SIDE (forecasting/marketdata) — its
// client parser + tests moved to Python (Arc C). Series route through
// gw.request('market.quotes'); see fetchQuotes below.

export const parseCoingecko = (json: unknown, seriesList: MarketSeries[]): MarketQuote[] => {
  const data = (json && typeof json === 'object' ? json : {}) as Record<string, Record<string, unknown>>

  return seriesList.map(s => {
    const row = data[s.symbol] ?? {}
    const value = num(row.usd)
    const pct = num(row.usd_24h_change)

    return {
      asOf: Date.now(),
      category: s.category,
      change: value !== null && pct !== null ? value * (pct / 100) : null,
      changePct: pct,
      name: s.name,
      provider: 'coingecko',
      symbol: s.symbol,
      unit: s.unit,
      value
    }
  })
}

// FRED observations (sorted desc, limit 2): latest value + change vs prior.
export const parseFred = (json: unknown, series: MarketSeries): MarketQuote => {
  const obs = (json as { observations?: { date?: string; value?: string }[] })?.observations ?? []
  const value = num(obs[0]?.value)
  const prev = num(obs[1]?.value)
  const { change, changePct } = withChange(value, prev)

  return {
    asOf: obs[0]?.date ? Date.parse(obs[0].date) : 0,
    category: series.category,
    change,
    changePct,
    name: series.name,
    provider: 'fred',
    symbol: series.symbol,
    unit: series.unit,
    value
  }
}

// FRED's keyless public endpoint (fredgraph.csv) returns "DATE,VALUE" rows,
// oldest→newest, with "." for missing values. We take the last two real values.
export const parseFredCsv = (csv: string, series: MarketSeries): MarketQuote => {
  const rows = csv
    .trim()
    .split(/\r?\n/)
    .slice(1) // drop the header row
    .map(line => {
      const comma = line.indexOf(',')

      return { date: line.slice(0, comma), value: num(line.slice(comma + 1)) }
    })
    .filter(r => r.value !== null)

  const last = rows[rows.length - 1]
  const prev = rows[rows.length - 2]
  const value = last?.value ?? null
  const { change, changePct } = withChange(value, prev?.value ?? null)

  return {
    asOf: last?.date ? Date.parse(last.date) : 0,
    category: series.category,
    change,
    changePct,
    name: series.name,
    provider: 'fred',
    symbol: series.symbol,
    unit: series.unit,
    value
  }
}

export const parseBls = (json: unknown, series: MarketSeries): MarketQuote => {
  const seriesData = (json as { Results?: { series?: { data?: { period?: string; value?: string; year?: string }[] }[] } })
    ?.Results?.series?.[0]?.data ?? []

  const value = num(seriesData[0]?.value)
  const prev = num(seriesData[1]?.value)
  const { change, changePct } = withChange(value, prev)
  const top = seriesData[0]

  return {
    asOf: top?.year ? Date.parse(`${top.year}-${(top.period || 'M01').replace(/^M/, '')}-01`) : 0,
    category: series.category,
    change,
    changePct,
    name: series.name,
    provider: 'bls',
    symbol: series.symbol,
    unit: series.unit,
    value
  }
}

// BEA (NIPA) is now parsed SERVER-SIDE (forecasting/marketdata) — its client
// parser + tests moved to Python (Arc C), where the estimator-honesty taxonomy
// can finally SEE the quote math (the fabricated-0.0000 bug lived here in TS
// precisely because they could not). Series route through market.quotes.

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

const getText = async (url: string, timeoutMs = 12000): Promise<null | string> => {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const r = await fetch(url, { headers: { 'User-Agent': 'Outrider/1.0' }, signal: controller.signal })

    if (!r.ok) {
      return null
    }

    return await r.text()
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
  getKey: (envVar: string) => string
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

  // ── SERVER-SIDE providers (FX + BEA in C1): one market.quotes RPC for all ──
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

  const crypto = client('coingecko')

  if (crypto?.length) {
    jobs.push(
      (async () => {
        const ids = crypto.map(s => s.symbol).join(',')

        const json = await getJson(
          `https://api.coingecko.com/api/v3/simple/price?ids=${ids}&vs_currencies=usd&include_24hr_change=true`
        )

        if (json) {
          opts.onBatch(parseCoingecko(json, crypto))
        }
      })()
    )
  }

  const fred = client('fred')
  const fredKey = opts.getKey('FRED_API_KEY')

  if (fred?.length) {
    jobs.push(
      pool(fred, 5, async s => {
        if (fredKey) {
          // Official JSON API (needs a key) — most reliable.
          const json = await getJson(
            `https://api.stlouisfed.org/fred/series/observations?series_id=${encodeURIComponent(s.symbol)}&api_key=${fredKey}&file_type=json&sort_order=desc&limit=2`
          )

          if (json) {
            opts.onBatch([parseFred(json, s)])
          }
        } else {
          // Keyless public CSV endpoint — works without a key (the public CSV is
          // occasionally flaky, which is why a key raises reliability).
          const csv = await getText(`https://fred.stlouisfed.org/graph/fredgraph.csv?id=${encodeURIComponent(s.symbol)}`)

          if (csv) {
            opts.onBatch([parseFredCsv(csv, s)])
          }
        }
      })
    )
  }

  const bls = client('bls')

  if (bls?.length) {
    jobs.push(
      (async () => {
        const blsKey = opts.getKey('BLS_API_KEY')
        await pool(bls, 4, async s => {
          const body = JSON.stringify({
            ...(blsKey ? { registrationkey: blsKey } : {}),
            seriesid: [s.symbol],
            startyear: String(new Date().getFullYear() - 1),
            endyear: String(new Date().getFullYear())
          })

          const json = await getJson('https://api.bls.gov/publicAPI/v2/timeseries/data/', {
            body,
            headers: { 'Content-Type': 'application/json' },
            method: 'POST'
          })

          if (json) {
            opts.onBatch([parseBls(json, s)])
          }
        })
      })()
    )
  }

  await Promise.all(jobs)
}
