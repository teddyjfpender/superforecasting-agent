import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { forecastHomeDir } from './forecastHome.js'
import type { MarketQuote } from './marketFetch.js'

// What the user has enabled: which providers, and which categories to watch.
// Persisted to ~/.superforecasting-agent/markets.json. Quote values are cached
// separately so the table paints instantly on reopen, then refreshes.

export interface MarketConfig {
  categories: string[]
  providers: string[]
}

export const marketConfigFile = (dir = forecastHomeDir()) => join(dir, 'markets.json')

export const loadMarketConfig = (file = marketConfigFile()): MarketConfig => {
  try {
    const data = JSON.parse(readFileSync(file, 'utf8')) as Partial<MarketConfig>

    return {
      categories: Array.isArray(data.categories) ? data.categories.filter(c => typeof c === 'string') : [],
      providers: Array.isArray(data.providers) ? data.providers.filter(p => typeof p === 'string') : []
    }
  } catch {
    return { categories: [], providers: [] }
  }
}

export const saveMarketConfig = (config: MarketConfig, file = marketConfigFile()): boolean => {
  try {
    const dir = forecastHomeDir()

    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true })
    }

    writeFileSync(file, `${JSON.stringify(config, null, 2)}\n`, { mode: 0o600 })

    return true
  } catch {
    return false
  }
}

// Quote cache keyed by `${provider}:${symbol}`.
export type QuoteCache = Record<string, MarketQuote>

const quoteCacheFile = (dir = forecastHomeDir()) => join(dir, 'markets_cache.json')

export const quoteKey = (provider: string, symbol: string): string => `${provider}:${symbol}`

export const loadQuoteCache = (file = quoteCacheFile()): QuoteCache => {
  try {
    const data: unknown = JSON.parse(readFileSync(file, 'utf8'))

    return data && typeof data === 'object' ? (data as QuoteCache) : {}
  } catch {
    return {}
  }
}

export const saveQuoteCache = (cache: QuoteCache, file = quoteCacheFile()): boolean => {
  try {
    const dir = forecastHomeDir()

    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true })
    }

    writeFileSync(file, JSON.stringify(cache), { mode: 0o600 })

    return true
  } catch {
    return false
  }
}
