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

// ── column packing (2-space gutters enforced; priority-drop on narrow) ────────
// Two aligned schemas so every value sits under a header that NAMES it (the old
// tape let bid/ask fall under VOL and volume under CLOSE). The pack machinery
// guarantees a minimum 2-space gutter between every column, so compact cells
// ("$2.3M" + "Oct 31") can never merge into "$2.3MOct 31".

export interface PmCol {
  align: 'left' | 'right'
  key: string
  label: string
  w: number
}

const PM_GUTTER = 2
const PM_MARKER = 2 // the leading '▸ '/'  ' cursor gutter
const PM_MARKET_MIN = 12

// Headline schema fixed columns (MARKET absorbs the leftover). Priority to KEEP
// under pressure: PROB + CLOSE are sacred (with MARKET); VOL outranks VENUE, so
// the narrow-terminal drop order is VENUE first, then VOL.
const PM_HEAD_FIXED: PmCol[] = [
  { align: 'right', key: 'prob', label: 'PROB', w: 6 },
  { align: 'right', key: 'vol', label: 'VOL', w: 7 },
  { align: 'right', key: 'close', label: 'CLOSE', w: 7 },
  { align: 'left', key: 'venue', label: 'VENUE', w: 6 }
]

const PM_HEAD_DROP_ORDER = ['venue', 'vol'] as const

// Pack the headline row into `avail` columns: choose which fixed columns survive
// (dropping VENUE then VOL until MARKET clears its minimum), then give MARKET the
// remaining width. Returns MARKET width + the surviving fixed columns in display
// order. Pure + deterministic so the layout is unit-testable.
export function packPmHead(avail: number): { cols: PmCol[]; marketW: number } {
  const budget = Math.max(PM_MARKET_MIN, avail - PM_MARKER)
  const keep = new Set(PM_HEAD_FIXED.map(c => c.key))

  const fixedWidth = () =>
    PM_HEAD_FIXED.filter(c => keep.has(c.key)).reduce((acc, c) => acc + PM_GUTTER + c.w, 0)

  for (const drop of PM_HEAD_DROP_ORDER) {
    if (budget - fixedWidth() >= PM_MARKET_MIN) {
      break
    }

    keep.delete(drop)
  }

  const cols = PM_HEAD_FIXED.filter(c => keep.has(c.key))

  return { cols, marketW: Math.max(PM_MARKET_MIN, budget - cols.reduce((a, c) => a + PM_GUTTER + c.w, 0)) }
}

// Outcome sub-row schema: OUTCOME (flex) | PROB | BID·ASK | VOL. Rendered under
// its own dim header so the bid/ask + volume cells are named correctly. The
// outcome rows are indented under the expand tree, so the label budget subtracts
// that indent on top of the cursor marker.
export const PM_OUTCOME_INDENT = 3 // the '└ ' tree glyph run

const PM_OUTCOME_FIXED: PmCol[] = [
  { align: 'right', key: 'prob', label: 'PROB', w: 6 },
  { align: 'right', key: 'ba', label: 'BID·ASK', w: 7 },
  { align: 'right', key: 'vol', label: 'VOL', w: 7 }
]

export function packPmOutcome(avail: number): { cols: PmCol[]; labelW: number } {
  const fixed = PM_OUTCOME_FIXED.reduce((a, c) => a + PM_GUTTER + c.w, 0)
  const budget = avail - PM_MARKER - PM_OUTCOME_INDENT

  return { cols: PM_OUTCOME_FIXED, labelW: Math.max(6, budget - fixed) }
}

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
