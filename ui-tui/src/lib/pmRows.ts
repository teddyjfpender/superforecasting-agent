// Pure row model for the Prediction Markets tape: an event collapses to a
// HEADLINE row; when expanded (and categorical, n>1) it reveals INDENTED
// outcome sub-rows — the discretised distribution the operator asked for.
// Kept pure + framework-free so the flatten / sort / filter logic is unit
// testable without the Ink harness.

import { type FieldSpec, rankItems } from './fuzzyRank.js'
import { type PMListItem, type PMOutcomeDTO, venueLabel } from './pmData.js'
import { type SortValue } from './tableSort.js'

// A stable id for an event row: venue-scoped so Polymarket + Kalshi ids never
// collide in the one shared tape.
export const pmRowId = (item: PMListItem): string => `${item.event.venue}:${item.event.event_id}`

export type PMDisplayRow =
  | { id: string; item: PMListItem; kind: 'headline' }
  | { id: string; outcome: PMOutcomeDTO; parent: PMListItem; parentId: string; kind: 'outcome' }

// Flatten the sorted items into display rows, expanding the events whose id is
// in `expanded`. Binary events (n<=1) never expand — the headline IS the row.
export function flattenPMRows(items: readonly PMListItem[], expanded: ReadonlySet<string>): PMDisplayRow[] {
  const rows: PMDisplayRow[] = []

  for (const item of items) {
    const id = pmRowId(item)
    rows.push({ id, item, kind: 'headline' })

    const outcomes = item.distribution.outcomes ?? []
    const categorical = !item.distribution.binary && outcomes.length > 1

    if (categorical && expanded.has(id)) {
      outcomes.forEach((outcome, i) => {
        rows.push({ id: `${id}#${outcome.market_id || i}`, kind: 'outcome', outcome, parent: item, parentId: id })
      })
    }
  }

  return rows
}

// Whether an event can expand (categorical with >1 outcome).
export const pmExpandable = (item: PMListItem): boolean =>
  !item.distribution.binary && (item.distribution.outcomes?.length ?? 0) > 1

// ── sort (headline rows only; sub-rows stay attached under their parent) ─────

export const PM_SORT_KEYS = ['title', 'prob', 'vol', 'close'] as const

export const pmSortValue = (item: PMListItem, key: string): SortValue => {
  const h = item.distribution.headline

  switch (key) {
    case 'close': {
      const ts = item.distribution.close_time ? Date.parse(item.distribution.close_time) : NaN

      return Number.isFinite(ts) ? ts : null
    }

    case 'prob':
      return h.top_prob ?? null

    case 'title':
      return item.distribution.title || item.event.title || ''

    case 'vol':
      return item.distribution.total_volume ?? null

    default:
      return null
  }
}

// ── `/` filter fields (title is the key, then category, then venue label) ────

const PM_SEARCH_FIELDS: FieldSpec<PMListItem>[] = [
  { get: i => i.distribution.title || i.event.title, weight: 1 },
  { get: i => i.event.category ?? '', weight: 0.5 },
  { get: i => venueLabel(i.event.venue), weight: 0.4 }
]

// Rank + filter the items by a `/` query, preserving item identity. An empty
// query returns the input order untouched.
export function filterPMItems(items: readonly PMListItem[], query: string): PMListItem[] {
  const q = query.trim()

  if (!q) {
    return items.slice()
  }

  const rankOf = new Map<PMListItem, number>()
  rankItems(items as PMListItem[], q, PM_SEARCH_FIELDS).forEach((r, i) => rankOf.set(r.item, i))

  return items.filter(i => rankOf.has(i)).sort((a, b) => (rankOf.get(a) ?? 0) - (rankOf.get(b) ?? 0))
}
