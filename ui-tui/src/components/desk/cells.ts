import { sweepColor, sweepStops } from '../../lib/accentSweep.js'
import { deltaGlyph, windowDelta } from '../../lib/forecastCharts.js'
import { spinnerFrame } from '../../lib/icons.js'
import type { SortValue } from '../../lib/tableSort.js'
import { dirColor, readinessColor, type Semantics } from '../../lib/visualSemantics.js'
import type { ForecastWorkspaceItem } from '../../protocol/generated.js'
import type { Theme } from '../../theme.js'
import { finite, headlineCompact, trimNum, truncate } from '../forecastsWorkspace.js'

// ── Desk table: column specs, sort-key values, and per-cell colour+text ───────
// Pure formatters + the DeskSweepCtx contract for the redesigned desk LIST. Moved
// out of deskView.tsx verbatim (Wave-5 modularization) so the row/cell rendering
// and keyboard-sort logic is unit-testable in isolation; deskView re-exports the
// public names so callers and tests keep importing them from the deskView module.

export interface DeskCol {
  align: 'left' | 'right'
  key: string
  label: string
  // Fixed columns carry a width; QUESTION is flexible (w computed from slack).
  w: number
}

// Display order, left→right. QUESTION's `w` is a placeholder — it is recomputed
// from the leftover width after the kept fixed columns are reserved.
export const DESK_COLS: DeskCol[] = [
  { align: 'left', key: 'q', label: 'QUESTION', w: 24 },
  { align: 'right', key: 'prob', label: 'PROB', w: 8 },
  { align: 'right', key: '1d', label: '1D', w: 8 },
  { align: 'right', key: '1w', label: '1W', w: 8 },
  { align: 'right', key: '1mo', label: '1MO', w: 9 },
  { align: 'right', key: 'ev', label: 'EV', w: 4 },
  // SRC = active watched-source count (0 = "no fuel", warning-coloured); RDY = the
  // 0-100 machine-readiness composite, banded by colour. Both reserve 5 (label 3 +
  // the " ▲/▼" sort indicator) so the sortable header renders without clipping —
  // the same "label + indicator fits" sizing every other numeric column uses.
  { align: 'right', key: 'src', label: 'SRC', w: 5 },
  { align: 'right', key: 'rdy', label: 'RDY', w: 5 },
  { align: 'right', key: 'age', label: 'AGE', w: 7 },
  // NEXT reserves 9 (vs the other numerics' 7-8): the honest due-state strings
  // ("◐ running", "due · Xm") are 8-9 chars, and unlike a min-width pad the column
  // must actually RESERVE the slot or the row's truncate-end clips into the string.
  { align: 'right', key: 'next', label: 'NEXT', w: 9 }
]

// Keep by priority when narrow (render still follows display order). QUESTION is
// always kept; PROB matters most; then SRC/RDY — the operator's machine-readiness
// signals (a 0-source row explains WHY nothing updates, which outranks momentum
// deltas: the operator asked for this column expressly) — then NEXT, the wider
// 1W window, EV, the noisier 1D/1MO, and AGE last.
export const DESK_PRIORITY = ['prob', 'src', 'rdy', 'next', '1w', 'ev', '1d', '1mo', 'age']

// Every desk column is sortable except the trailing trend spark (which is not a
// column). `o` cycles through them in header (display) order, then one keyless
// mode — 'voi' — which reorders the book by the server's value-of-information
// score (highest-value "touch next" first) even though it has no dedicated column.
export const DESK_SORT_KEYS = [...DESK_COLS.map(c => c.key), 'voi']

// Human labels for the sort modes (flashed on cycle so the keyless 'voi' mode is
// discoverable; column modes echo their header). Missing → the raw key.
export const SORT_MODE_LABELS: Record<string, string> = {
  '1d': '1D change',
  '1mo': '1MO change',
  '1w': '1W change',
  age: 'age',
  ev: 'evidence',
  next: 'next review',
  prob: 'probability',
  q: 'question',
  rdy: 'readiness',
  src: 'sources',
  voi: 'VOI (value of information)'
}

// The comparable value a desk row contributes for a given sort key. Text for
// QUESTION; the raw signed window Δ for 1D/1W/1MO; the probability/μ for PROB; a
// numeric age (older → larger, so ascending = freshest first) for AGE; the next
// event's epoch (soonest first ascending) for NEXT. Missing values sort last.
export const deskSortValue = (item: ForecastWorkspaceItem, key: string, nowMs: number): SortValue => {
  switch (key) {
    case '1d':
      return windowDelta(item.history, nowMs, 1)

    case '1mo':
      return windowDelta(item.history, nowMs, 30)

    case '1w':
      return windowDelta(item.history, nowMs, 7)
    case 'age': {
      const at = Date.parse(item.as_of ?? '')

      return Number.isFinite(at) ? nowMs - at : null
    }

    case 'ev':
      return item.evidence_count ?? 0
    case 'next': {
      const at = item.next_review_at
        ? Date.parse(item.next_review_at)
        : Date.parse(item.resolution_time ?? item.close_time ?? '')

      return Number.isFinite(at) ? at : null
    }

    case 'prob':
      return finite(item.headline_probability) ? item.headline_probability : null

    case 'q':
      return item.title ?? item.id ?? ''

    case 'rdy':
      return finite(item.readiness?.score) ? item.readiness!.score : null

    case 'src':
      return item.src_count ?? 0

    case 'voi':
      // Negate so ASCENDING surfaces the HIGHEST value-of-information first (the
      // 'age' inversion pattern) — cycling to voi lands the most urgent touch on
      // top without needing a direction toggle. No score → sorts last.
      return finite(item.voi?.score) ? -item.voi!.score : null

    default:
      return null
  }
}

// AGE from the snapshot's real as_of: "now" (<60s), "5m", "3h", "2d", "4mo" —
// the server's coarse freshness string ("fresh today") collapsed everything from
// the last 24h into an ambiguous "now". Minutes use bare "m"; months always "mo"
// (the repo-wide convention so 2mo never reads as 2 minutes). Falls back to the
// freshness string only when as_of is unparseable.
const shortAge = (nowMs: number, asOf: string | undefined, freshness: string | undefined): string => {
  const at = Date.parse(asOf ?? '')

  if (Number.isFinite(at)) {
    const ms = Math.max(0, nowMs - at)

    if (ms < 60_000) {return 'now'}
    const mins = ms / 60_000

    if (mins < 60) {return `${Math.round(mins)}m`}
    const hours = mins / 60

    if (hours < 24) {return `${Math.round(hours)}h`}
    const days = hours / 24

    if (days < 52) {return `${Math.round(days)}d`}

    return `${Math.max(2, Math.round(days / 30))}mo`
  }

  if (!freshness) {
    return '—'
  }

  const m = /(\d+)\s*([a-z]+)/i.exec(freshness)

  return m ? `${m[1]}${m[2].toLowerCase().slice(0, 2)}` : truncate(freshness, 6)
}

// Compact relative-time forward for the NEXT column: "5h", "3d", "2mo". Sub-day
// rounds to hours; up to ~7wk reads in days; further out collapses to months so a
// far-off resolution still fits the narrow column.
const relTime = (ms: number): string => {
  const days = ms / 86400000

  if (days < 1) {return `${Math.max(1, Math.round(ms / 3600000))}h`}

  if (days < 52) {return `${Math.round(days)}d`}

  return `${Math.max(2, Math.round(days / 30))}mo`
}

// Forward "time to NEXT auto-reforecast" for the NEXT column (the live schedule).
// "now" (due/overdue), "5h", "3d"; status drives colour. When there is NO live
// review (market_nightly markets deliberately have no re-forecast cadence; a
// primary-election cron the desk can't see), FALL BACK to the question's next
// real event — resolution_time ?? close_time — rendered with a leading "⤓" marker
// and a distinct 'res' status so it reads visibly as a resolution date, NOT a
// scheduled review. A real review (next_review_at present) renders EXACTLY as
// before — the fallback never alters it. Neither → "—".
export const dueText = (
  item: ForecastWorkspaceItem,
  nowMs: number
): { status: 'none' | 'now' | 'ok' | 'res' | 'soon'; text: string } => {
  const at = item.next_review_at ? Date.parse(item.next_review_at) : NaN

  if (Number.isFinite(at)) {
    const ms = at - nowMs

    if (ms <= 0) {return { status: 'now', text: 'now' }}
    const days = ms / 86400000

    if (days < 1) {return { status: 'soon', text: `${Math.max(1, Math.round(ms / 3600000))}h` }}
    const d = Math.round(days)

    return { status: d <= 2 ? 'soon' : 'ok', text: `${d}d` }
  }

  // No scheduled review → show the next meaningful event (resolution), marked.
  const eventAt = Date.parse(item.resolution_time ?? item.close_time ?? '')

  if (!Number.isFinite(eventAt)) {return { status: 'none', text: '—' }}
  const ms = eventAt - nowMs

  // Already resolved/closed but still on the desk → just flag it as due.
  if (ms <= 0) {return { status: 'res', text: '⤓now' }}

  return { status: 'res', text: `⤓${relTime(ms)}` }
}

// The live review-sweep context threaded into the NEXT column so a DUE row can
// render honest state instead of a static "now": is a sweep running (spinner),
// when will the gateway sweeper next tick, and — when the sweeper is disabled —
// whether the nightly cron will pick it up "tonight". All epochs are ms (NaN when
// absent). `frame` is the 500ms spinner tick (only read while `running`). `nowMs`
// is the minute-bucketed clock so the "due · Xm" text is stable within a minute
// (which keeps the memoised row from re-rendering on every 500ms reflow when idle).
export interface DeskSweepCtx {
  frame: number
  nightlyNextAt: number
  nowMs: number
  running: boolean
  // The agent is working THIS question right now → the gutter animates with
  // the house accent sweep (same family as the Home chat / review sweep).
  runningNow?: boolean
  nextTickAt: number
  sweeperEnabled: boolean
}

// The NEXT cell for a row whose scheduled review is DUE (status 'now'). Honest,
// at-a-glance: while a sweep runs → an animated spinner + "running"; else, when
// the gateway sweeper is enabled → a countdown to its next tick ("due · Xm",
// "due · <1m" under a minute, imminent when the tick time is unknown/past); when
// the sweeper is disabled → "due · tonight" if the nightly cron will pick it up,
// else a plain "due". Strings stay narrow (≤ ~9 chars, bar the rare "tonight").
export const dueNowCell = (sweep: DeskSweepCtx | undefined, t: Theme): { color: string; text: string } => {
  if (!sweep) {
    return { color: t.color.error, text: 'now' }
  }

  if (sweep.running) {
    // Match the Home chat's busy spinner: colour the glyph (+ its "running" label)
    // by sweeping the brand accent family via sweepColor(sweepStops(t), frame) — the
    // exact helper appChrome's FaceTicker uses — instead of a static accent. `frame`
    // is the shared 500ms tick, so the cell cycles colour in lock-step with the
    // summary line while the memo keeps idle rows frozen.
    return { color: sweepColor(sweepStops(t), sweep.frame), text: `${spinnerFrame(sweep.frame)} running` }
  }

  if (sweep.sweeperEnabled) {
    const imminent = !Number.isFinite(sweep.nextTickAt) || sweep.nextTickAt <= sweep.nowMs

    if (imminent) {
      return { color: t.color.warn, text: 'due · <1m' }
    }

    const diff = sweep.nextTickAt - sweep.nowMs

    return { color: t.color.warn, text: diff < 60000 ? 'due · <1m' : `due · ${Math.ceil(diff / 60000)}m` }
  }

  if (Number.isFinite(sweep.nightlyNextAt)) {
    return { color: t.color.warn, text: 'due · tonight' }
  }

  return { color: t.color.warn, text: 'due' }
}

// Window change → display text only (colour is applied by the caller from the
// raw signed value so direction reads via colour AND glyph). For distributions
// the magnitude is outcome-unit Δμ; for probabilities it is percent-points.
const windowChgText = (item: ForecastWorkspaceItem, value: number | null): string => {
  if (value === null) {
    return '—'
  }

  const glyph = deltaGlyph(value)

  if (item.headline_kind === 'distribution') {
    if (!finite(value) || Math.abs(value) < 1e-6) {
      return '·'
    }

    return `${glyph}${value > 0 ? '+' : ''}${trimNum(value)}`
  }

  // 2dp point deltas (the operator's precision standard — an integer-only
  // column hides every sub-point move a fresh commit produces). '·' only when
  // the rendered value would read 0.00.
  if (!finite(value) || Math.abs(value) < 0.00005) {
    return '·'
  }

  const points = (value * 100).toFixed(2)

  return `${glyph}${value > 0 ? '+' : ''}${points}`
}

// CHG cell colour + text together, so a flat ('·') or absent ('—') change is
// painted neutral rather than a misleading coloured up/down move.
const windowChgCell = (
  item: ForecastWorkspaceItem,
  value: number | null,
  sem: Semantics
): { color: string; text: string } => {
  const text = windowChgText(item, value)
  const color = text === '·' || text === '—' ? sem.subtle : dirColor(sem, value)

  return { color, text }
}

// One cell's colour + text. `windows` are the precomputed 1D/1W/1MO deltas so the
// switch stays a pure formatter. Exported so the SRC "no fuel" warning + the RDY
// band colours are unit-testable in isolation (the dueNowCell pattern).
export const deskCellText = (
  key: string,
  item: ForecastWorkspaceItem,
  sem: Semantics,
  t: Theme,
  windows: { '1d': number | null; '1mo': number | null; '1w': number | null },
  nowMs: number,
  sweep?: DeskSweepCtx
): { color: string; text: string } => {
  switch (key) {
    case '1d':
      return windowChgCell(item, windows['1d'], sem)

    case '1mo':
      return windowChgCell(item, windows['1mo'], sem)

    case '1w':
      return windowChgCell(item, windows['1w'], sem)

    case 'age':
      return { color: sem.subtle, text: shortAge(nowMs, item.as_of ?? undefined, item.freshness ?? undefined) }
    case 'next': {
      const due = dueText(item, nowMs)

      // A DUE row ('now') no longer reads a static "now": spell out honest sweep
      // state (spinner while running, a countdown to the next tick, or the nightly
      // fallback). Every other status is unchanged.
      if (due.status === 'now') {
        return dueNowCell(sweep, t)
      }

      // A resolution-date fallback is informational (not an urgent review) → paint
      // it subtle so the "⤓" marker, not colour, signals the distinction.
      const color = due.status === 'soon' ? t.color.warn : sem.subtle

      return { color, text: due.text }
    }

    case 'ev':
      return { color: sem.subtle, text: String(item.evidence_count ?? 0) }
    case 'src': {
      // Active watched-source count. 0 is the "no fuel" signal — the autonomous
      // desk has nothing to refresh — so it paints in the warning colour; a
      // fuelled row stays subtle so only the empty ones draw the eye.
      const n = item.src_count ?? 0

      return { color: n > 0 ? sem.subtle : t.color.warn, text: String(n) }
    }

    case 'rdy': {
      // The 0-100 machine-readiness composite, banded by colour (≥80 ok, 50-79
      // warn, <50 danger). No composite (benchmark/market question) → subtle "—".
      const score = item.readiness?.score

      return finite(score)
        ? { color: readinessColor(t, score), text: String(Math.round(score)) }
        : { color: sem.subtle, text: '—' }
    }

    case 'prob':
      return { color: t.color.text, text: headlineCompact(item, 2) }

    case 'q':
      return { color: t.color.label, text: item.title ?? item.id ?? 'untitled' }

    default:
      return { color: t.color.text, text: '' }
  }
}
