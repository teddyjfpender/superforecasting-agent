/**
 * Desk grouping — turns the forecast workspace payload into the ordered horizontal
 * category tabs the redesigned Desk navigates (mirroring the Markets view's tab strip).
 *
 * Order: each Thesis, then each Factor, then auto tag/theme groups for forecasts that
 * belong to no thesis/factor, then a final "All" catch-all. Thesis/factor membership is
 * server-side (question_ids); the tag fallback is pure TUI-side bucketing by topics→domain.
 */

import type {
  ForecastFactor,
  ForecastThesis,
  ForecastWorkspaceItem,
  ForecastWorkspaceResponse,
} from '../gatewayTypes.js'

export type DeskTabKind = 'thesis' | 'factor' | 'tag' | 'bench' | 'all'

/** True when a forecast is a ForecastBench backtest replay (domain isolation, with a
 *  tag fallback) — these belong in the separate read-only "Bench" lens, NOT the live
 *  organic-forecast list. Mirrors the gateway's `build_bench_scoreboard` selector. */
export function isBenchForecast(item: ForecastWorkspaceItem): boolean {
  if ((item.domain || '').trim().toLowerCase() === 'forecastbench') return true
  const tags = (item.topics || []).map((t) => (t || '').trim().toLowerCase())
  return tags.includes('bench') || tags.includes('forecastbench')
}

export interface DeskTab {
  /** stable key for selection/keying */
  key: string
  /** tab strip label */
  label: string
  kind: DeskTabKind
  /** thesis/factor id, for the aggregate read shown in the skinny panel header */
  refId?: string
  /** ids of the forecasts under this tab, in payload order */
  forecastIds: string[]
}

/** The theme bucket a forecast falls into when it belongs to no thesis/factor:
 *  first non-blank topic, else domain, else "untagged". */
export function forecastTheme(item: ForecastWorkspaceItem): string {
  const topic = (item.topics || []).map((t) => (t || '').trim()).find(Boolean)
  if (topic) return topic.toLowerCase()
  const domain = (item.domain || '').trim()
  return domain ? domain.toLowerCase() : 'untagged'
}

// Thesis/factor titles are long sentences ("Democrats take the Senate back tracker
// thesis"); tabs need a SHORT label. Strip the trailing kind-noise words + stopwords
// and keep the first significant words, so the strip stays on one line.
const LABEL_NOISE = /\b(thesis|tracker|basket|factor|index|forecast|outlook|tracker)\b/gi
const LABEL_STOP = new Set(['a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'in', 'is', 'of', 'on', 'or', 'the', 'to', 'vs', 'with'])

export function shortLensLabel(title: string, max = 18): string {
  const cleaned = (title || '').replace(LABEL_NOISE, ' ').replace(/\s+/g, ' ').trim()
  const words = cleaned.split(' ').filter((w) => w && !LABEL_STOP.has(w.toLowerCase()))
  let out = words.slice(0, 3).join(' ')
  if (out.length > max) out = words.slice(0, 2).join(' ')
  if (out.length > max) out = `${out.slice(0, max - 1)}…`
  return out || (title || 'Lens').slice(0, max)
}

/** A clean #tag label from a raw topic/theme: drop 4-digit years + 1-char tokens,
 *  keep the first significant word, cap short. "2026 u.s. primary election" → "primary". */
export function cleanTagLabel(theme: string, max = 14): string {
  const words = (theme || '').split(/[\s_./-]+/).filter((w) => w && !/^\d{4}$/.test(w) && w.length > 1)
  const sig = words.find((w) => w.length > 2) ?? words[0] ?? theme
  return sig.slice(0, max).toLowerCase()
}

export function buildDeskTabs(payload: ForecastWorkspaceResponse): DeskTab[] {
  const forecasts = payload.forecasts || []
  const present = new Set(forecasts.map((f) => f.id || '').filter(Boolean))
  const keep = (ids?: string[]): string[] => (ids || []).filter((id) => present.has(id))

  const tabs: DeskTab[] = []
  const grouped = new Set<string>()

  for (const th of payload.theses || []) {
    const ids = keep(th.question_ids)
    ids.forEach((id) => grouped.add(id))
    tabs.push({ key: `thesis:${th.id ?? th.title}`, label: shortLensLabel(th.title || 'Thesis'), kind: 'thesis', refId: th.id, forecastIds: ids })
  }
  for (const fa of payload.factors || []) {
    const ids = keep(fa.question_ids)
    ids.forEach((id) => grouped.add(id))
    tabs.push({ key: `factor:${fa.id ?? fa.title}`, label: shortLensLabel(fa.title || 'Factor'), kind: 'factor', refId: fa.id, forecastIds: ids })
  }

  // ForecastBench backtest replays are carved out FIRST so they never reach the
  // tag/All buckets — the live desk shows only organic forecasts, and the bench
  // questions surface ONLY under the read-only "Bench" lens (which renders the
  // scoreboard from the `forecast.bench` RPC, not this id list). Membership ids
  // are still carried so a `/forecast <id>` jump can find a bench question's tab.
  const benchIds = forecasts
    .map((f) => (grouped.has(f.id || '') ? '' : isBenchForecast(f) ? f.id || '' : ''))
    .filter(Boolean)
  benchIds.forEach((id) => grouped.add(id))

  // Tag/theme groups for the forecasts that belong to no thesis/factor (and are
  // not bench replays — those are already grouped out above).
  const buckets = new Map<string, string[]>()
  for (const f of forecasts) {
    const id = f.id || ''
    if (!id || grouped.has(id)) continue
    const theme = forecastTheme(f)
    const arr = buckets.get(theme)
    if (arr) arr.push(id)
    else buckets.set(theme, [id])
  }
  const tagTabs: DeskTab[] = [...buckets.entries()]
    .map(([theme, ids]) => ({ key: `tag:${theme}`, label: `#${cleanTagLabel(theme)}`, kind: 'tag' as const, forecastIds: ids }))
    .sort((a, b) => b.forecastIds.length - a.forecastIds.length || a.label.localeCompare(b.label))
  tabs.push(...tagTabs)

  // The Bench lens sits just before the All catch-all. ForecastBench replays
  // RESOLVE immediately, so they are NOT in the active workspace forecast list
  // (benchIds is typically empty) — visibility keys off payload.benchCount, the
  // count of domain=forecastbench questions of any status. The scoreboard loads
  // from the forecast.bench RPC, not this id list, so empty forecastIds is fine.
  if (benchIds.length || (payload.bench_count ?? 0) > 0) {
    tabs.push({ key: 'bench', label: '◇ Bench', kind: 'bench', forecastIds: benchIds })
  }

  // The All catch-all excludes the carved-out bench replays (they are not organic
  // live forecasts) but keeps every thesis/factor/tag member.
  const allIds = forecasts.map((f) => f.id || '').filter((id) => id && !benchIds.includes(id))
  tabs.push({ key: 'all', label: 'All', kind: 'all', forecastIds: allIds })
  return tabs
}

/** Resolve a tab's forecast ids to the item objects, preserving order. */
export function forecastsForTab(tab: DeskTab | undefined, forecasts: ForecastWorkspaceItem[]): ForecastWorkspaceItem[] {
  if (!tab) return []
  const byId = new Map(forecasts.map((f) => [f.id || '', f]))
  return tab.forecastIds.map((id) => byId.get(id)).filter((f): f is ForecastWorkspaceItem => !!f)
}

/** Pick the contiguous window of tab indices to render so `active` stays visible and the
 *  strip fits `maxWidth`. Expands outward from active, preferring the right (later lenses).
 *  Returns {start, end} (end exclusive). Pure — the variable Desk tab count needs this
 *  (Markets gets away with rendering all ~10 hard-coded categories). */
export function tabWindow(labelWidths: number[], active: number, maxWidth: number, sep = 3): { start: number; end: number } {
  const n = labelWidths.length
  if (n === 0) return { start: 0, end: 0 }
  const a = Math.max(0, Math.min(active, n - 1))
  const budget = Math.max(labelWidths[a], maxWidth - 6) // leave room for the ‹ › overflow markers + their spaces
  let start = a
  let end = a + 1
  let used = labelWidths[a]
  for (;;) {
    const left = start > 0 ? used + sep + labelWidths[start - 1] : Number.POSITIVE_INFINITY
    const right = end < n ? used + sep + labelWidths[end] : Number.POSITIVE_INFINITY
    if (right <= budget && right <= left) {
      used = right
      end += 1
    } else if (left <= budget) {
      used = left
      start -= 1
    } else {
      break
    }
  }
  return { start, end }
}

/** The thesis/factor whose aggregate read heads the skinny panel for a lens tab. */
export function tabRefThesis(tab: DeskTab | undefined, theses: ForecastThesis[] = []): ForecastThesis | undefined {
  if (!tab || tab.kind !== 'thesis') return undefined
  return theses.find((t) => t.id === tab.refId)
}
export function tabRefFactor(tab: DeskTab | undefined, factors: ForecastFactor[] = []): ForecastFactor | undefined {
  if (!tab || tab.kind !== 'factor') return undefined
  return factors.find((f) => f.id === tab.refId)
}
