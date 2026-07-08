/**
 * Desk grouping — turns the forecast workspace payload into the ordered horizontal
 * category tabs the redesigned Desk navigates (mirroring the Markets view's tab strip).
 *
 * Lens set: one tab per REAL thesis (an `outcome_type=thesis` aggregate), ordered by
 * member count DESC so the largest ("major") thesis leads and smaller ("minor") theses
 * follow, then a single "All" catch-all — and nothing else. Factor/tag/section
 * pseudo-lenses (redundant lenses for thesis-style questions that aren't real theses)
 * were removed: they cluttered the strip. Thesis membership is server-side (question_ids).
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

export function buildDeskTabs(payload: ForecastWorkspaceResponse): DeskTab[] {
  const forecasts = payload.forecasts || []
  const present = new Set(forecasts.map((f) => f.id || '').filter(Boolean))
  const keep = (ids?: string[]): string[] => (ids || []).filter((id) => present.has(id))
  const memberCount = (th: ForecastThesis): number => th.member_count ?? keep(th.question_ids).length

  // REAL theses only, ordered by member count DESC: the largest thesis (the
  // "major" thesis) leads, smaller ("minor") theses follow. Ties break on title so
  // the order is stable across reloads.
  const orderedTheses = [...(payload.theses || [])].sort(
    (a, b) => memberCount(b) - memberCount(a) || (a.title || '').localeCompare(b.title || '')
  )

  const tabs: DeskTab[] = []
  const grouped = new Set<string>()
  for (const th of orderedTheses) {
    const ids = keep(th.question_ids)
    ids.forEach((id) => grouped.add(id))
    tabs.push({ key: `thesis:${th.id ?? th.title}`, label: shortLensLabel(th.title || 'Thesis'), kind: 'thesis', refId: th.id, forecastIds: ids })
  }

  // ForecastBench backtest replays are still carved OUT of the All catch-all (the
  // live desk lists ORGANIC forecasts only) but no longer get their own lens — the
  // read-only Bench scoreboard is not a thesis, and the desk's lens set is real
  // theses + All, nothing else. (Bench replays resolve immediately, so on the live
  // desk this set is virtually always empty.)
  const benchIds = forecasts
    .map((f) => (grouped.has(f.id || '') ? '' : isBenchForecast(f) ? f.id || '' : ''))
    .filter(Boolean)

  // The All catch-all keeps every thesis member + every un-grouped forecast, and
  // excludes only the carved-out bench replays (not organic live forecasts).
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
