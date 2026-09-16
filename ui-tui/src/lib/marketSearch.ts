import type { MarketSeries } from '../content/marketProviders.js'

import type { QuotesTransport } from './marketFetch.js'

// Find market line items two ways: a ranked search over the curated catalog
// (with intent synonyms — "gold"→commodities, "sp500"→^GSPC), and a live Yahoo
// symbol lookup so users can pull up ANY ticker. The catalog scorer is pure +
// tested; the Yahoo lookup now routes SERVER-SIDE through the gateway's
// `market.search` RPC (Arc C3) — the parser + quoteType→category mapping moved
// to Python (forecasting/marketdata/providers/yahoo.py), so no Yahoo fetch/parse
// runs client-side anymore.

const SYNONYMS: Record<string, string[]> = {
  us: ['united states', 'usa', 'american'],
  uk: ['united kingdom', 'gbr', 'british'],
  uae: ['united arab emirates', 'are'],
  growth: ['gdp', 'output'],
  housing: ['home', 'house', 'mortgage', 'residential'],
  weather: ['temperature', 'precipitation', 'wind'],
  rain: ['precipitation'],
  population: ['demographics'],
  currency: ['fx', 'exchange'],
  bitcoin: ['btc', 'crypto'],
  bonds: ['rates', 'treasury', 'yield'],
  btc: ['bitcoin', 'crypto'],
  crude: ['oil', 'commodities'],
  dollar: ['fx', 'usd', 'currency'],
  dow: ['dji', 'indices'],
  eth: ['ethereum', 'crypto'],
  ethereum: ['eth', 'crypto'],
  gas: ['natural gas', 'commodities'],
  gold: ['commodities', 'metal'],
  inflation: ['cpi', 'prices', 'pce'],
  jobs: ['employment', 'payrolls', 'unemployment'],
  nasdaq: ['ixic', 'indices'],
  oil: ['crude', 'commodities', 'wti'],
  rates: ['yield', 'treasury', 'fed', 'bonds'],
  silver: ['commodities', 'metal'],
  stocks: ['equities', 'shares'],
  treasury: ['rates', 'yield', 'bonds'],
  yield: ['rates', 'treasury', 'bonds']
}

const expand = (tokens: string[]): string[] => {
  const out = new Set<string>()

  for (const tok of tokens) {
    for (const syn of SYNONYMS[tok] ?? []) {
      out.add(syn)
    }
  }

  for (const tok of tokens) {
    out.delete(tok)
  }

  return [...out]
}

export const scoreSeries = (s: MarketSeries, tokens: string[], expanded: string[]): number => {
  const name = s.name.toLowerCase()
  const symbol = s.symbol.toLowerCase()
  const cat = s.category.toLowerCase()
  const metadata = s.search_terms?.toLowerCase() ?? ''
  const text = `${name} ${symbol} ${cat} ${metadata} ${s.provider}`

  if (
    !tokens.every(token =>
      [token, ...(SYNONYMS[token] ?? [])].some(term =>
        ['us', 'uk', 'uae'].includes(token)
          ? new RegExp(`(^|[^a-z0-9_])${term}($|[^a-z0-9_])`).test(text)
          : text.includes(term)
      )
    )
  ) {
    return 0
  }

  let score = 0

  for (const tok of tokens) {
    if (metadata.includes(tok)) {
      score += 4
    }

    if (symbol === tok) {
      score += 14
    } else if (symbol.includes(tok)) {
      score += 7
    }

    if (name === tok) {
      score += 12
    } else if (name.startsWith(tok)) {
      score += 8
    } else if (name.includes(tok)) {
      score += 5
    }

    if (cat === tok) {
      score += 6
    } else if (cat.includes(tok)) {
      score += 3
    }
  }

  for (const syn of expanded) {
    if (cat.includes(syn) || name.includes(syn) || symbol.includes(syn)) {
      score += 3
    }
  }

  return score
}

export const searchCatalog = (query: string, catalog: readonly MarketSeries[]): MarketSeries[] => {
  const q = query.trim().toLowerCase()

  if (!q) {
    return []
  }

  const tokens = q.split(/\s+/).filter(Boolean)
  const expanded = expand(tokens)

  return catalog
    .map(s => ({ s, score: scoreSeries(s, tokens, expanded) }))
    .filter(x => x.score > 0)
    .sort((a, b) => b.score - a.score || a.s.name.localeCompare(b.s.name))
    .map(x => x.s)
}

// The live symbol lookup, routed through the gateway's `market.search` RPC (the
// Yahoo endpoint + parser live server-side now). Without a gateway there is no
// client fallback — the catalog results still show; the remote merge is simply
// empty (parity with fetchQuotes degrading when no gw is present).
export const searchYahoo = async (query: string, gw?: QuotesTransport): Promise<MarketSeries[]> => {
  const q = query.trim()

  if (!q || !gw) {
    return []
  }

  const res = await gw.request('market.search', { query: q })

  return (res?.results ?? []).map(r => ({
    category: r.category,
    name: r.name,
    provider: r.provider,
    symbol: r.symbol
  }))
}

/** Federated discovery; unknown remote metadata never becomes a catalog binding. */
export const discoverMarkets = async (query: string, gw?: QuotesTransport): Promise<MarketSeries[]> => {
  if (!gw || query.trim().length < 2) {
    return []
  }

  const response = await gw.request('market.discover', { query: query.trim().slice(0, 200) })

  return response.results.map(hit => ({
    provider: hit.provider,
    symbol: hit.symbol,
    name: hit.name,
    category: hit.category,
    unit: hit.unit,
    ...(hit.catalog_id ? { catalog_id: hit.catalog_id } : {})
  }))
}
