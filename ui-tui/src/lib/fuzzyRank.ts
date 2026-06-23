// Generic client-side fuzzy + synonym ranker — the unified search engine behind
// every view's `/` filter (news, markets, docs, desk). It is the "semantic"
// recall WITHOUT an embedding model: tokenize the query, expand intent synonyms,
// and score each item field-by-field with exact > prefix > word-boundary >
// substring tiers (plus softer synonym hits). It generalizes the proven
// scoreFeed/scoreSeries scorers so every view ranks loaded items identically and
// instantly (no RPC, no LLM, no network).

// Query token -> related intent terms. Seeded from the news + markets scorers so
// "investing" surfaces Markets, "election" surfaces politics, "ai" surfaces ML.
// Views can extend this per-call by passing their own merged map.
export const FUZZY_SYNONYMS: Record<string, string[]> = {
  ai: ['artificial intelligence', 'machine learning', 'ml', 'deep learning', 'llm', 'neural', 'technology'],
  ml: ['machine learning', 'artificial intelligence', 'ai', 'technology'],
  crypto: ['cryptocurrency', 'bitcoin', 'ethereum', 'blockchain', 'web3', 'finance'],
  bitcoin: ['crypto', 'cryptocurrency', 'blockchain', 'finance'],
  stocks: ['markets', 'equities', 'investing', 'trading', 'stock', 'finance', 'wall street', 'business'],
  equities: ['stocks', 'markets', 'shares', 'investing', 'finance'],
  investing: ['markets', 'finance', 'stocks', 'equities', 'business', 'economy'],
  markets: ['finance', 'stocks', 'business', 'economy', 'trading', 'wall street'],
  economy: ['economics', 'macro', 'business', 'finance', 'markets'],
  macro: ['economy', 'economics', 'inflation', 'rates', 'markets'],
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
  election: ['politics', 'vote', 'voting', 'ballot', 'government'],
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

// A searchable field: how to pull its text from an item + how heavily to weight
// a hit. Title-like fields weight high; body-like fields weight low.
export type FieldSpec<T> = {
  get: (item: T) => null | string | string[] | undefined
  weight: number
}

export type Ranked<T> = { item: T; score: number }

export const tokenize = (query: string): string[] => query.trim().toLowerCase().split(/\s+/).filter(Boolean)

export const expandTokens = (tokens: string[], synonyms: Record<string, string[]> = FUZZY_SYNONYMS): string[] => {
  const out = new Set<string>()

  for (const tok of tokens) {
    for (const syn of synonyms[tok] ?? []) {
      out.add(syn)
    }
  }

  // A synonym that's also a literal token would double-score — drop it.
  for (const tok of tokens) {
    out.delete(tok)
  }

  return [...out]
}

const wordBoundary = (haystack: string, needle: string): boolean => {
  // Escaped literal + \b can't throw, but guard anyway so no query can ever break
  // a view's filter; the scorer's substring tier still catches the token.
  try {
    return new RegExp(`\\b${needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`).test(haystack)
  } catch {
    return false
  }
}

// Tiered per-field score against the literal + expanded (synonym) tokens. The
// caller multiplies this by the field's weight, so a title hit dominates a body
// hit even at the same tier.
const scoreText = (text: string, tokens: string[], expanded: string[]): number => {
  let score = 0

  for (const tok of tokens) {
    if (text === tok) {
      score += 14
    } else if (text.startsWith(tok)) {
      score += 9
    } else if (wordBoundary(text, tok)) {
      score += 6
    } else if (text.includes(tok)) {
      score += 3
    }
  }

  for (const syn of expanded) {
    if (wordBoundary(text, syn)) {
      score += 2
    } else if (text.includes(syn)) {
      score += 1
    }
  }

  return score
}

const fieldText = (value: null | string | string[] | undefined): string => {
  if (Array.isArray(value)) {
    return value.join(' ').toLowerCase()
  }

  return (value ?? '').toLowerCase()
}

export const scoreItem = <T>(item: T, fields: FieldSpec<T>[], tokens: string[], expanded: string[]): number => {
  let total = 0

  for (const field of fields) {
    const text = fieldText(field.get(item))

    if (text) {
      total += field.weight * scoreText(text, tokens, expanded)
    }
  }

  return total
}

// Rank items by relevance to the query. Empty query → every item passes through
// with score 0 (callers show the full list unranked). Otherwise non-matches are
// dropped and matches are ordered by score desc, with original order as a stable
// tiebreak so equal-score items don't jitter as the user types.
export const rankItems = <T>(
  items: T[],
  query: string,
  fields: FieldSpec<T>[],
  synonyms: Record<string, string[]> = FUZZY_SYNONYMS
): Ranked<T>[] => {
  const tokens = tokenize(query)

  if (tokens.length === 0) {
    return items.map(item => ({ item, score: 0 }))
  }

  const expanded = expandTokens(tokens, synonyms)

  return items
    .map((item, index) => ({ item, index, score: scoreItem(item, fields, tokens, expanded) }))
    .filter(x => x.score > 0)
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map(x => ({ item: x.item, score: x.score }))
}

// Convenience: just the matching items in ranked order (full list for an empty
// query). The common shape a view's filtered list needs.
export const filterRanked = <T>(
  items: T[],
  query: string,
  fields: FieldSpec<T>[],
  synonyms: Record<string, string[]> = FUZZY_SYNONYMS
): T[] => (query.trim() ? rankItems(items, query, fields, synonyms).map(r => r.item) : items)
