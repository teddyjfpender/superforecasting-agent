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

export type DeskTabKind = 'thesis' | 'factor' | 'tag' | 'all'

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

export function buildDeskTabs(payload: ForecastWorkspaceResponse): DeskTab[] {
  const forecasts = payload.forecasts || []
  const present = new Set(forecasts.map((f) => f.id || '').filter(Boolean))
  const keep = (ids?: string[]): string[] => (ids || []).filter((id) => present.has(id))

  const tabs: DeskTab[] = []
  const grouped = new Set<string>()

  for (const th of payload.theses || []) {
    const ids = keep(th.question_ids)
    ids.forEach((id) => grouped.add(id))
    tabs.push({ key: `thesis:${th.id ?? th.title}`, label: th.title || 'Thesis', kind: 'thesis', refId: th.id, forecastIds: ids })
  }
  for (const fa of payload.factors || []) {
    const ids = keep(fa.question_ids)
    ids.forEach((id) => grouped.add(id))
    tabs.push({ key: `factor:${fa.id ?? fa.title}`, label: fa.title || 'Factor', kind: 'factor', refId: fa.id, forecastIds: ids })
  }

  // Tag/theme groups for the forecasts that belong to no thesis/factor.
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
    .map(([theme, ids]) => ({ key: `tag:${theme}`, label: `#${theme}`, kind: 'tag' as const, forecastIds: ids }))
    .sort((a, b) => b.forecastIds.length - a.forecastIds.length || a.label.localeCompare(b.label))
  tabs.push(...tagTabs)

  tabs.push({ key: 'all', label: 'All', kind: 'all', forecastIds: forecasts.map((f) => f.id || '').filter(Boolean) })
  return tabs
}

/** Resolve a tab's forecast ids to the item objects, preserving order. */
export function forecastsForTab(tab: DeskTab | undefined, forecasts: ForecastWorkspaceItem[]): ForecastWorkspaceItem[] {
  if (!tab) return []
  const byId = new Map(forecasts.map((f) => [f.id || '', f]))
  return tab.forecastIds.map((id) => byId.get(id)).filter((f): f is ForecastWorkspaceItem => !!f)
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
