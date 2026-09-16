/** Versioned plain JSON survives Signal/Telegram text transport and ordinary history exports.
 * Only validated, bounded snapshots render. Unknown versions remain ordinary text.
 */
import type { FeedShare, SharedFeed, SharedObservation } from '../protocol/generated.js'

import type { MarketQuote } from './marketFetch.js'

export const FEED_SHARE_LIMIT = 48 * 1024
const marker = '\n```sfa-feed\n'
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)

const keys = (v: Record<string, unknown>, allowed: string[]) =>
  Object.keys(v).every(k => allowed.includes(k)) && allowed.every(k => k in v)

const plain = (v: unknown, max: number, min = 0): v is string =>
  typeof v === 'string' &&
  v.length >= min &&
  v.length <= max &&
  [...v].every(char => {
    const code = char.charCodeAt(0)

    return code >= 32 && (code < 127 || code > 159)
  })

const day = (v: unknown): v is string =>
  typeof v === 'string' &&
  /^\d{4}-\d{2}-\d{2}$/.test(v) &&
  Number.isFinite(Date.parse(v)) &&
  new Date(v).toISOString().slice(0, 10) === v

const period = (v: unknown): v is Record<string, unknown> & { start: string; end: string } =>
  object(v) && day(v.start) && day(v.end) && v.start <= v.end

const instant = (v: unknown) =>
  v === null || (plain(v, 40) && /(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v)))

const publicUrl = (v: unknown) => {
  if (v === null) {
    return true
  }

  if (!plain(v, 2048)) {
    return false
  }

  try {
    const u = new URL(v)

    return (
      ['http:', 'https:'].includes(u.protocol) && !!u.hostname && !u.username && !u.password && !u.search && !u.hash
    )
  } catch {
    return false
  }
}

export function validFeedShare(v: unknown): v is FeedShare {
  if (
    !object(v) ||
    !keys(v, ['type', 'version', 'presentation', 'horizon', 'feeds']) ||
    v.type !== 'sfa.feed' ||
    v.version !== 1 ||
    (v.presentation !== 'bar-chart' && v.presentation !== 'line-chart') ||
    !period(v.horizon) ||
    !keys(v.horizon, ['start', 'end']) ||
    !Array.isArray(v.feeds) ||
    v.feeds.length < 1 ||
    v.feeds.length > 4
  ) {
    return false
  }

  const ids = new Set<string>()

  for (const f of v.feeds) {
    if (
      !object(f) ||
      !keys(f, [
        'provider',
        'symbol',
        'name',
        'unit',
        'kind',
        'source_url',
        'retrieved_at',
        'revision_policy',
        'points'
      ]) ||
      !plain(f.provider, 80, 1) ||
      !plain(f.symbol, 160, 1) ||
      !plain(f.name, 240, 1) ||
      !plain(f.unit, 80) ||
      !plain(f.kind, 40) ||
      !plain(f.revision_policy, 80) ||
      !publicUrl(f.source_url) ||
      !instant(f.retrieved_at) ||
      !Array.isArray(f.points) ||
      f.points.length < 1 ||
      f.points.length > 120
    ) {
      return false
    }

    const id = JSON.stringify([f.provider, f.symbol])

    if (ids.has(id)) {
      return false
    }

    ids.add(id)
    let previous = ''

    for (const p of f.points) {
      if (
        !period(p) ||
        !keys(p, ['start', 'end', 'value']) ||
        !(p.value === null || (typeof p.value === 'number' && Number.isFinite(p.value))) ||
        p.start <= previous ||
        p.start < v.horizon.start ||
        p.end > v.horizon.end
      ) {
        return false
      }

      previous = p.end
    }
  }

  return true
}

export function decodeFeedMessage(text: string): { text: string; share: FeedShare | null } {
  if (Buffer.byteLength(text, 'utf8') > FEED_SHARE_LIMIT) {
    return { text, share: null }
  }

  const index = text.lastIndexOf(marker)

  if (index < 0 || !text.endsWith('\n```')) {
    return { text, share: null }
  }

  try {
    const share: unknown = JSON.parse(text.slice(index + marker.length, -4))

    return validFeedShare(share) ? { text: text.slice(0, index).trim(), share } : { text, share: null }
  } catch {
    return { text, share: null }
  }
}

export function encodeFeedMessage(text: string, share: FeedShare): string {
  if (!validFeedShare(share)) {
    throw new Error('Feed snapshot is invalid; refresh the source before sharing.')
  }

  const wire = `${text.trim()}${marker}${JSON.stringify(share)}\n\x60\x60\x60`

  if (Buffer.byteLength(wire, 'utf8') > FEED_SHARE_LIMIT) {
    throw new Error('Feed snapshot is too large. Choose a shorter horizon.')
  }

  return wire
}

export function shareQuote(quote: MarketQuote): FeedShare | null {
  // The wire chart uses calendar days; providers also supply timezone-aware
  // instants (e.g. Yahoo daily closes). Normalize those to UTC days here, not
  // in the ledger. Validation below still rejects overlapping/collapsed days.
  const chartDay = (value: string): string => {
    if (day(value as unknown)) {
      return value
    }

    if (
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
      day(value.slice(0, 10)) &&
      Number.isFinite(Date.parse(value))
    ) {
      return new Date(value).toISOString().slice(0, 10)
    }

    return value
  }

  let points: SharedObservation[] = (quote.dated_history ?? [])
    .map(p => ({ start: chartDay(p.period_start), end: chartDay(p.period_end), value: p.value }))
    .slice(-120)

  if (!points.length && quote.asOf > 0 && Number.isFinite(quote.asOf) && quote.asOf <= 8.64e15) {
    const date = new Date(quote.asOf).toISOString().slice(0, 10)
    points = [{ start: date, end: date, value: quote.value }]
  }

  if (!points.length) {
    return null
  }

  // Strip URL query strings, credentials and fragments; never forward API tokens.
  let source: string | null = null

  try {
    const url = new URL(quote.source_url || '')

    if (!url.username && !url.password && ['http:', 'https:'].includes(url.protocol)) {
      source = url.origin + url.pathname
    }
  } catch {
    /* no public source */
  }

  const feed: SharedFeed = {
    provider: quote.provider,
    symbol: quote.symbol,
    name: quote.name,
    unit: quote.unit || quote.currency || '',
    kind: quote.kind || 'quote',
    source_url: source,
    retrieved_at: quote.retrieved_at || null,
    revision_policy: quote.revision_policy || 'unknown',
    points
  }

  const share: FeedShare = {
    type: 'sfa.feed',
    version: 1,
    presentation: 'bar-chart',
    horizon: { start: points[0]!.start, end: points.at(-1)!.end },
    feeds: [feed]
  }

  return validFeedShare(share) ? share : null
}

export function presentFeedShare(share: FeedShare, presentation: FeedShare['presentation'], count: number): FeedShare {
  const feeds = share.feeds.map(f => ({ ...f, points: f.points.slice(-count) }))

  return {
    ...share,
    presentation,
    feeds,
    horizon: {
      start: feeds.map(f => f.points[0]!.start).sort()[0]!,
      end: feeds
        .map(f => f.points.at(-1)!.end)
        .sort()
        .at(-1)!
    }
  }
}
