import { DEFAULT_SERIES, type MarketSeries } from '../content/marketProviders.js'

// Find market line items two ways: a ranked search over the curated catalog
// (with intent synonyms — "gold"→commodities, "sp500"→^GSPC), and a live Yahoo
// symbol lookup so users can pull up ANY ticker. The catalog scorer is pure +
// tested; the Yahoo lookup is a thin network call.

const SYNONYMS: Record<string, string[]> = {
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
  let score = 0

  for (const tok of tokens) {
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

export const searchCatalog = (query: string): MarketSeries[] => {
  const q = query.trim().toLowerCase()

  if (!q) {
    return []
  }

  const tokens = q.split(/\s+/).filter(Boolean)
  const expanded = expand(tokens)

  return DEFAULT_SERIES.map(s => ({ s, score: scoreSeries(s, tokens, expanded) }))
    .filter(x => x.score > 0)
    .sort((a, b) => b.score - a.score || a.s.name.localeCompare(b.s.name))
    .map(x => x.s)
}

// Map a Yahoo quoteType to one of our categories.
export const yahooTypeToCategory = (quoteType: string): string => {
  switch ((quoteType || '').toUpperCase()) {
    case 'CRYPTOCURRENCY':
      return 'Crypto'

    case 'CURRENCY':
      return 'FX'

    case 'FUTURE':
      return 'Commodities'

    case 'INDEX':
      return 'Indices'

    default:
      return 'Stocks'
  }
}

export const parseYahooSearch = (json: unknown): MarketSeries[] => {
  const quotes = (json as { quotes?: Record<string, unknown>[] })?.quotes ?? []

  return quotes
    .filter(q => typeof q.symbol === 'string')
    .map(q => ({
      category: yahooTypeToCategory(String(q.quoteType ?? '')),
      name: String(q.shortname || q.longname || q.symbol),
      provider: 'yahoo',
      symbol: String(q.symbol)
    }))
}

export const searchYahoo = async (query: string, timeoutMs = 8000): Promise<MarketSeries[]> => {
  const q = query.trim()

  if (!q) {
    return []
  }

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const r = await fetch(
      `https://query1.finance.yahoo.com/v1/finance/search?q=${encodeURIComponent(q)}&quotesCount=10&newsCount=0`,
      { headers: { 'User-Agent': 'Outrider/1.0' }, signal: controller.signal }
    )

    if (!r.ok) {
      return []
    }

    return parseYahooSearch(await r.json())
  } catch {
    return []
  } finally {
    clearTimeout(timer)
  }
}
