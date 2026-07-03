import type { MarketSeries } from '../content/marketProviders.js'

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

export const parseFrankfurter = (json: unknown, seriesList: MarketSeries[]): MarketQuote[] => {
  // A DATE-RANGE payload ({rates: {"2026-06-02": {EUR: ..}, ...}}): daily
  // closes give the change columns + the 1MO sparkline that /latest starved
  // (the operator: FX "missing fundamental information"). A /latest-shaped
  // payload (rates: {EUR: number}) still parses as a value-only quote.
  const data = json as { date?: string; rates?: Record<string, unknown> }
  const rates = data?.rates ?? {}
  const dateKeys = Object.keys(rates)
    .filter(k => /^\d{4}-\d{2}-\d{2}$/.test(k))
    .sort()

  if (dateKeys.length === 0) {
    const asOf = data?.date ? Date.parse(data.date) : 0

    return seriesList.map(s => ({
      asOf: Number.isFinite(asOf) ? asOf : 0,
      category: s.category,
      change: null,
      changePct: null,
      name: s.name,
      provider: 'frankfurter',
      symbol: s.symbol,
      unit: s.unit,
      value: num(rates[s.symbol])
    }))
  }

  const asOf = Date.parse(dateKeys[dateKeys.length - 1]!)

  return seriesList.map(s => {
    const closes = dateKeys
      .map(d => num((rates[d] as Record<string, unknown> | undefined)?.[s.symbol]))
      .filter((v): v is number => v !== null)
    const value = closes.length ? closes[closes.length - 1]! : null
    const prevClose = closes.length > 1 ? closes[closes.length - 2]! : null
    const change = value !== null && prevClose !== null ? value - prevClose : null

    return {
      asOf: Number.isFinite(asOf) ? asOf : 0,
      category: s.category,
      change,
      changePct: change !== null && prevClose ? (change / prevClose) * 100 : null,
      history: closes,
      name: s.name,
      prevClose,
      provider: 'frankfurter',
      symbol: s.symbol,
      unit: s.unit,
      value
    }
  })
}

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

export const parseBea = (json: unknown, series: MarketSeries): MarketQuote => {
  // NIPA responses carry EVERY LINE of the table (31 lines for T20305): the
  // old rows[last] read an arbitrary line's value, and an API error payload
  // (e.g. the invalid Year=LAST5 we used to send) yielded num('') === 0 — a
  // FABRICATED 0.0000 on every BEA row (the operator's catch). Filter to the
  // headline line, keep periods sorted, and let absence be null ('—').
  const rows = (json as { BEAAPI?: { Results?: { Data?: { DataValue?: string; LineNumber?: string; TimePeriod?: string }[] } } })
    ?.BEAAPI?.Results?.Data ?? []
  const line = (series as { line?: string }).line ?? '1'
  const lineRows = rows
    .filter(r => (r.LineNumber ?? '1') === line && r.TimePeriod)
    .sort((a, b) => String(a.TimePeriod).localeCompare(String(b.TimePeriod)))

  const last = lineRows[lineRows.length - 1]
  const prev = lineRows[lineRows.length - 2]
  const parseVal = (r?: { DataValue?: string }): null | number =>
    r?.DataValue ? num(String(r.DataValue).replace(/,/g, '')) : null
  const value = parseVal(last)
  const prevValue = parseVal(prev)
  const change = value !== null && prevValue !== null ? value - prevValue : null

  // BEA TimePeriod is "2024Q3" (quarterly) or "2024" (annual) — map to a date so
  // the detail pane shows a real "updated" instead of "—".
  const period = last?.TimePeriod || ''
  const quarter = /^(\d{4})Q([1-4])$/.exec(period)

  const asOf = quarter
    ? Date.parse(`${quarter[1]}-${String((Number(quarter[2]) - 1) * 3 + 1).padStart(2, '0')}-01`)
    : /^\d{4}$/.test(period)
      ? Date.parse(`${period}-01-01`)
      : 0

  return {
    asOf: Number.isFinite(asOf) ? asOf : 0,
    category: series.category,
    change,
    changePct: change !== null && prevValue ? (change / prevValue) * 100 : null,
    history: lineRows.map(parseVal).filter((v): v is number => v !== null).slice(-12),
    name: series.name,
    prevClose: prevValue,
    provider: 'bea',
    symbol: series.symbol,
    unit: series.unit,
    value
  }
}

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

export interface FetchOpts {
  getKey: (envVar: string) => string
  onBatch: (quotes: MarketQuote[]) => void
}

// Fetch all the given series, grouped by provider, emitting quotes per group as
// they arrive. Missing API keys for keyed providers are skipped (the caller
// surfaces which ones need keys).
export const fetchQuotes = async (seriesList: MarketSeries[], opts: FetchOpts): Promise<void> => {
  const byProvider = new Map<string, MarketSeries[]>()

  for (const s of seriesList) {
    byProvider.set(s.provider, [...(byProvider.get(s.provider) ?? []), s])
  }

  const jobs: Promise<void>[] = []

  const yahoo = byProvider.get('yahoo')

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

  const fx = byProvider.get('frankfurter')

  if (fx?.length) {
    jobs.push(
      (async () => {
        const symbols = fx.map(s => s.symbol).join(',')
        // ~35 calendar days of daily closes in ONE call: value + day change +
        // the 1MO sparkline (FX has no volume — that column stays honestly '—').
        const from = new Date(Date.now() - 35 * 86_400_000).toISOString().slice(0, 10)
        const json = await getJson(`https://api.frankfurter.app/${from}..?base=USD&symbols=${symbols}`)

        if (json) {
          opts.onBatch(parseFrankfurter(json, fx))
        }
      })()
    )
  }

  const crypto = byProvider.get('coingecko')

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

  const fred = byProvider.get('fred')
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

  const bls = byProvider.get('bls')

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

  const bea = byProvider.get('bea')
  const beaKey = opts.getKey('BEA_API_KEY')

  if (bea?.length && beaKey) {
    jobs.push(
      pool(bea, 3, async s => {
        const json = await getJson(
          // Year=LAST5 is INVALID for NIPA (API error 201 -> empty Data ->
          // the fabricated 0.0000). Two explicit years cover latest + prior
          // quarters for the change columns.
          `https://apps.bea.gov/api/data/?UserID=${beaKey}&method=GetData&datasetname=NIPA&TableName=${s.symbol}&Frequency=Q&Year=${new Date().getFullYear() - 1},${new Date().getFullYear()}&ResultFormat=JSON`
        )

        if (json) {
          opts.onBatch([parseBea(json, s)])
        }
      })
    )
  }

  await Promise.all(jobs)
}
