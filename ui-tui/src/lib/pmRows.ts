// Pure row model for the Prediction Markets tape: an event collapses to a
// HEADLINE row; when expanded (and categorical, n>1) it reveals INDENTED
// outcome sub-rows — the discretised distribution the operator asked for.
// Kept pure + framework-free so the flatten / sort / filter logic is unit
// testable without the Ink harness.

import { type FieldSpec, rankItems } from './fuzzyRank.js'
import { fmtPMVol, type PMListItem, type PMOutcomeDTO, type PMVenue, venueLabel } from './pmData.js'
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
// the narrow-terminal drop order is VENUE first, then VOL. PROB is wide enough
// (10) for a binary row's colour-coded direction reading at 2dp — "YES 99.99%".
const PM_HEAD_FIXED: PmCol[] = [
  { align: 'right', key: 'prob', label: 'PROB', w: 10 },
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

// ── variable-height windowing (headline = 1 line; the FIRST outcome of an
// expanded group renders an extra dim OUTCOME/BID·ASK header line, so it costs 2).
// The old windowing counted rows uniformly, so an injected header line pushed the
// SELECTED row past the clipped viewport and the cursor vanished (the operator's
// bug). pmWindow scrolls in VISUAL-LINE space and guarantees the selected row is
// fully visible on every frame. Pure + deterministic → frame-by-frame testable.

// Whether row i begins a fresh outcome group in the FULL list (its own header
// line). The window's first rendered row ALSO draws a header (see the renderer's
// prev===undefined branch), so pmWindow charges the boundary row the same 2 lines.
const outcomeGroupStart = (rows: readonly PMDisplayRow[], i: number): boolean => {
  const row = rows[i]

  if (!row || row.kind !== 'outcome') {
    return false
  }

  const prev = rows[i - 1]

  return !prev || prev.kind !== 'outcome' || prev.parentId !== row.parentId
}

// Lines row i occupies when the window starts at `start`: an outcome sub-row that
// leads its group (or leads the window) carries a header line → 2, else 1.
const rowLineCost = (rows: readonly PMDisplayRow[], i: number, start: number): number =>
  rows[i]?.kind === 'outcome' && (i === start || outcomeGroupStart(rows, i)) ? 2 : 1

// The visible slice [start, end) for a `viewport`-line window that ALWAYS keeps
// the selected row fully on screen. Preference is a centred start; it is only
// nudged down when the selected row's bottom line would fall outside the viewport.
export function pmWindow(
  rows: readonly PMDisplayRow[],
  sel: number,
  viewport: number
): { end: number; start: number } {
  const n = rows.length

  if (n === 0) {
    return { end: 0, start: 0 }
  }

  const vp = Math.max(1, viewport)
  const s = Math.max(0, Math.min(sel, n - 1))

  const linesFromTo = (from: number, to: number): number => {
    let lines = 0

    for (let i = from; i <= to; i++) {
      lines += rowLineCost(rows, i, from)
    }

    return lines
  }

  // Centre, then pull the start DOWN until the selected row's last line fits.
  let start = Math.max(0, s - Math.floor(vp / 2))

  while (start < s && linesFromTo(start, s) > vp) {
    start++
  }

  // Fill downward with whole rows that fit the viewport (the selected row is
  // guaranteed to fit by the loop above, so it is always included).
  let used = 0
  let end = start

  while (end < n) {
    const cost = rowLineCost(rows, end, start)

    if (used + cost > vp) {
      break
    }

    used += cost
    end++
  }

  return { end: Math.max(end, s + 1), start }
}

// ── `f` structured filter (venue · topic · min volume · prob range · hide sports)
// A compact, testable filter over the fetched events. Composes ON TOP of the `/`
// text search and the column sort. venue is the single source of truth for the
// section (it also drives the fetch), so a filtered venue is honoured twice —
// harmlessly — here and at the gateway.

export interface PmFilter {
  hideSports: boolean
  maxProb: null | number // 0..1 inclusive
  minProb: null | number // 0..1 inclusive
  minVolume: null | number // dollars
  topic: string // substring over title + event title + category
  venue: 'all' | PMVenue
}

export const EMPTY_PM_FILTER: PmFilter = {
  hideSports: false,
  maxProb: null,
  minProb: null,
  minVolume: null,
  topic: '',
  venue: 'all'
}

// Parse a money shorthand ("1m" → 1_000_000, "500k" → 500_000, "2.3m", "1000",
// "$1,000"). Returns null for empty / unparseable input (an inactive bound).
export function parseMoneyShorthand(raw: string): null | number {
  const s = raw.trim().toLowerCase().replace(/[$,\s]/g, '')

  if (!s) {
    return null
  }

  const m = /^(\d+(?:\.\d+)?)(k|m|b)?$/.exec(s)

  if (!m) {
    return null
  }

  const mult = m[2] === 'b' ? 1e9 : m[2] === 'm' ? 1e6 : m[2] === 'k' ? 1e3 : 1

  return parseFloat(m[1]!) * mult
}

// Parse a percent field ("5", "95", "0.85") into a 0..1 probability. Values ≤ 1
// are read as already-fractional; anything larger is a percent. null = no bound.
export function parseProbPercent(raw: string): null | number {
  const s = raw.trim().replace(/[%\s]/g, '')

  if (!s) {
    return null
  }

  const n = Number(s)

  if (!Number.isFinite(n)) {
    return null
  }

  return n > 1 ? n / 100 : n
}

// An HONEST sports heuristic (labelled as such in the UI): an explicit sports
// category, or an obvious league / sport token in the title. Deliberately
// pattern-based, so it can over- or under-match — the filter chip says "heuristic".
const SPORTS_RE =
  /\b(nba|nfl|nhl|mlb|ncaa|epl|mls|ufc|mma|f1|formula\s?1|premier league|la liga|serie a|bundesliga|ligue 1|champions league|super bowl|world cup|world series|stanley cup|playoffs?|finals?|grand prix|olympics?|soccer|football|basketball|baseball|hockey|tennis|golf|cricket|boxing|nascar)\b/i

export function isSportsItem(item: PMListItem): boolean {
  const cat = (item.event.category ?? '').toLowerCase()

  if (cat.includes('sport')) {
    return true
  }

  return SPORTS_RE.test(`${item.distribution.title} ${item.event.title}`)
}

export const pmFilterActive = (f: PmFilter): boolean =>
  f.venue !== 'all' ||
  Boolean(f.topic.trim()) ||
  f.minVolume !== null ||
  f.minProb !== null ||
  f.maxProb !== null ||
  f.hideSports

// Apply the structured filter (pure). Prob bounds are INCLUSIVE; an item with no
// headline prob is excluded once any prob bound is set (a bound can't be met by a
// missing value — never fabricate one).
export function filterPMSection(items: readonly PMListItem[], f: PmFilter): PMListItem[] {
  return items.filter(item => {
    if (f.venue !== 'all' && item.event.venue.toLowerCase() !== f.venue) {
      return false
    }

    const topic = f.topic.trim().toLowerCase()

    if (topic) {
      const hay = `${item.distribution.title} ${item.event.title} ${item.event.category ?? ''}`.toLowerCase()

      if (!hay.includes(topic)) {
        return false
      }
    }

    if (f.minVolume !== null) {
      const vol = item.distribution.total_volume ?? item.event.volume ?? 0

      if (!(vol >= f.minVolume)) {
        return false
      }
    }

    if (f.minProb !== null || f.maxProb !== null) {
      const p = item.distribution.headline.top_prob

      if (p === null || p === undefined) {
        return false
      }

      if (f.minProb !== null && p < f.minProb) {
        return false
      }

      if (f.maxProb !== null && p > f.maxProb) {
        return false
      }
    }

    if (f.hideSports && isSportsItem(item)) {
      return false
    }

    return true
  })
}

// A muted one-line summary of the active filter for the section header
// ("venue kalshi · vol ≥ $1M · p 5-95% · no sports"). Empty when inactive.
export function pmFilterSummary(f: PmFilter): string {
  const parts: string[] = []

  if (f.venue !== 'all') {
    parts.push(`venue ${venueLabel(f.venue)}`)
  }

  if (f.topic.trim()) {
    parts.push(`“${f.topic.trim()}”`)
  }

  if (f.minVolume !== null) {
    parts.push(`vol ≥ ${fmtPMVol(f.minVolume)}`)
  }

  if (f.minProb !== null || f.maxProb !== null) {
    const lo = f.minProb !== null ? Math.round(f.minProb * 100) : 0
    const hi = f.maxProb !== null ? Math.round(f.maxProb * 100) : 100
    parts.push(`p ${lo}-${hi}%`)
  }

  if (f.hideSports) {
    parts.push('no sports')
  }

  return parts.join(' · ')
}
