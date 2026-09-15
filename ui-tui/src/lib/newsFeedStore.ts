import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { forecastHomeDir } from './forecastHome.js'

// Compatibility helpers for standalone terminal clients. Connected clients use
// the backend NewsDesk owner for atomic, additive profile edits; never replace
// its subscription file from the TUI. URL helpers remain shared with RSS parsing.

export interface SubscribedFeed {
  addedAt: number
  category: string
  custom?: boolean
  title: string
  url: string
}

export const newsFeedsFile = (dir = forecastHomeDir()) => join(dir, 'news_feeds.json')

// Normalised key for de-duplication / membership tests: lowercased, protocol-
// and trailing-slash-insensitive; preserve case-sensitive paths and queries so they do not make
// the same feed look like two.
export const normalizeFeedUrl = (url: string): string => {
  try {
    const parsed = new URL(ensureFeedUrlScheme(url))

    return `${parsed.host.toLowerCase()}${parsed.pathname.replace(/\/+$/, '')}${parsed.search}`
  } catch {
    return url.trim()
  }
}

export const isFeedUrl = (value: string): boolean => {
  const v = value.trim()

  if (/\s/.test(v)) {
    return false
  }

  if (/^https?:\/\//i.test(v)) {
    try {
      const url = new URL(v)

      return Boolean(url.hostname) && !url.username && !url.password
    } catch {
      return false
    }
  }

  // Bare domain with a path/extension, e.g. example.com/feed.xml
  return /^[a-z0-9.-]+\.[a-z]{2,}(\/\S*)?$/i.test(v)
}

export const ensureFeedUrlScheme = (value: string): string => {
  const v = value.trim()

  return /^https?:\/\//i.test(v) ? v : `https://${v}`
}

export const feedHost = (url: string): string => {
  try {
    return new URL(ensureFeedUrlScheme(url)).host.replace(/^www\./, '')
  } catch {
    return url
      .replace(/^https?:\/\//, '')
      .replace(/^www\./, '')
      .split('/')[0]
  }
}

export const loadSubscribedFeeds = (file = newsFeedsFile()): SubscribedFeed[] => {
  try {
    const data: unknown = JSON.parse(readFileSync(file, 'utf8'))

    const raw = Array.isArray(data)
      ? data
      : Array.isArray((data as { feeds?: unknown })?.feeds)
        ? (data as { feeds: unknown[] }).feeds
        : []

    return raw
      .filter((f): f is SubscribedFeed => Boolean(f) && typeof (f as SubscribedFeed).url === 'string')
      .map(f => ({
        addedAt: typeof f.addedAt === 'number' ? f.addedAt : 0,
        category: typeof f.category === 'string' ? f.category : 'Custom',
        custom: f.custom === true,
        title: typeof f.title === 'string' && f.title ? f.title : feedHost(f.url),
        url: f.url
      }))
  } catch {
    return []
  }
}

export const saveSubscribedFeeds = (feeds: SubscribedFeed[], file = newsFeedsFile()): boolean => {
  try {
    const dir = forecastHomeDir()

    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true })
    }

    writeFileSync(file, `${JSON.stringify({ feeds }, null, 2)}\n`, { mode: 0o600 })

    return true
  } catch {
    return false
  }
}
