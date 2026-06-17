import { type CatalogFeed, FEED_CATALOG } from '../content/newsFeedCatalog.js'

import { feedHost } from './newsFeedStore.js'

// Ranked search across the feed catalog. Two ways in: pick a category to
// browse, or type a query. The query is matched field-weighted (title >
// category > description > host) AND expanded through a small synonym map so
// intent-level searches work too — "soccer" surfaces Football feeds,
// "investing" surfaces Markets/Finance, "AI" surfaces ML/tech. That synonym
// layer is the "semantic" recall without shipping an embedding model.

export const ALL_CATEGORY = 'All'

// Query token -> related terms matched against a feed's category/title/desc.
const SYNONYMS: Record<string, string[]> = {
  ai: ['artificial intelligence', 'machine learning', 'ml', 'deep learning', 'llm', 'neural', 'technology'],
  ml: ['machine learning', 'artificial intelligence', 'ai', 'technology'],
  crypto: ['cryptocurrency', 'bitcoin', 'ethereum', 'blockchain', 'web3', 'finance'],
  bitcoin: ['crypto', 'cryptocurrency', 'blockchain', 'finance'],
  stocks: ['markets', 'equities', 'investing', 'trading', 'stock', 'finance', 'wall street', 'business'],
  investing: ['markets', 'finance', 'stocks', 'equities', 'business', 'economy'],
  markets: ['finance', 'stocks', 'business', 'economy', 'trading', 'wall street'],
  economy: ['economics', 'macro', 'business', 'finance', 'markets'],
  money: ['finance', 'personal finance', 'investing', 'markets'],
  soccer: ['football'],
  football: ['soccer'],
  movies: ['film', 'cinema', 'hollywood'],
  film: ['movies', 'cinema'],
  tv: ['television', 'streaming', 'shows'],
  space: ['nasa', 'astronomy', 'spaceflight', 'rocket', 'cosmos'],
  science: ['research', 'physics', 'biology', 'space'],
  tech: ['technology', 'gadgets', 'software', 'startups'],
  technology: ['tech', 'gadgets', 'software', 'programming', 'startups'],
  coding: ['programming', 'software', 'developer', 'web dev'],
  programming: ['coding', 'software', 'developer', 'engineering'],
  startup: ['startups', 'venture', 'vc', 'entrepreneur', 'business'],
  gaming: ['games', 'videogames', 'esports'],
  games: ['gaming', 'videogames'],
  politics: ['government', 'election', 'policy', 'world'],
  world: ['international', 'global', 'politics', 'news'],
  news: ['headlines', 'world', 'breaking'],
  cars: ['automotive', 'vehicles', 'auto'],
  food: ['cooking', 'recipes', 'cuisine'],
  design: ['ui', 'ux', 'product design'],
  photography: ['photo', 'camera'],
  weather: ['storm', 'hurricane', 'cyclone', 'typhoon', 'forecast', 'climate', 'meteorology', 'severe'],
  storm: ['hurricane', 'cyclone', 'typhoon', 'weather', 'severe', 'tropical'],
  hurricane: ['cyclone', 'typhoon', 'tropical', 'storm', 'weather', 'nhc'],
  flood: ['flooding', 'weather', 'disaster', 'rain'],
  earthquake: ['quake', 'seismic', 'usgs', 'disaster', 'hazard'],
  disaster: ['hazard', 'emergency', 'flood', 'earthquake', 'storm', 'weather', 'relief'],
  climate: ['weather', 'warming', 'environment', 'emissions'],
  wildfire: ['fire', 'wildfires', 'weather', 'hazard']
}

const expand = (tokens: string[]): string[] => {
  const out = new Set<string>()

  for (const tok of tokens) {
    for (const syn of SYNONYMS[tok] ?? []) {
      out.add(syn)
    }
  }

  // Don't let a synonym double as a literal token (already scored higher).
  for (const tok of tokens) {
    out.delete(tok)
  }

  return [...out]
}

const wordBoundary = (haystack: string, needle: string): boolean =>
  new RegExp(`\\b${needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`).test(haystack)

export const scoreFeed = (feed: CatalogFeed, tokens: string[], expanded: string[]): number => {
  const title = feed.title.toLowerCase()
  const cat = feed.category.toLowerCase()
  const desc = feed.description.toLowerCase()
  const host = feedHost(feed.url).toLowerCase()
  let score = 0

  for (const tok of tokens) {
    if (title === tok) {
      score += 14
    } else if (title.startsWith(tok)) {
      score += 9
    } else if (wordBoundary(title, tok)) {
      score += 6
    } else if (title.includes(tok)) {
      score += 3
    }

    if (cat === tok) {
      score += 8
    } else if (cat.includes(tok)) {
      score += 5
    }

    if (desc.includes(tok)) {
      score += 2
    }

    if (host.includes(tok)) {
      score += 2
    }
  }

  // Synonym (intent) matches — softer than literal hits but enough to surface
  // the right feeds when the user's words don't appear verbatim.
  for (const syn of expanded) {
    if (cat.includes(syn)) {
      score += 4
    }

    if (wordBoundary(title, syn)) {
      score += 2
    } else if (desc.includes(syn)) {
      score += 1
    }
  }

  return score
}

export const searchFeeds = (query: string, category: string = ALL_CATEGORY): CatalogFeed[] => {
  const pool =
    category && category !== ALL_CATEGORY ? FEED_CATALOG.filter(f => f.category === category) : FEED_CATALOG

  const q = query.trim().toLowerCase()

  if (!q) {
    // Catalog is pre-sorted by (category, title) at generation time.
    return pool
  }

  const tokens = q.split(/\s+/).filter(Boolean)
  const expanded = expand(tokens)

  return pool
    .map(feed => ({ feed, score: scoreFeed(feed, tokens, expanded) }))
    .filter(x => x.score > 0)
    .sort((a, b) => b.score - a.score || a.feed.title.localeCompare(b.feed.title))
    .map(x => x.feed)
}
