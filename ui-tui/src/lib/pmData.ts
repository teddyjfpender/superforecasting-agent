// Gateway-backed access to the prediction-markets subsystem (Polymarket +
// Kalshi). Every type here mirrors the `to_dict()` shapes emitted by
// `forecasting/pm/model.py` and surfaced through `tui_gateway/pm_rpc.py`
// (`pm.list` / `pm.detail` / `pm.book` / `pm.history` / `pm.stream.*`). The TUI
// is a pure consumer: the Python service is the one source of truth, so this
// module only fetches, normalises light-touch, and formats for display.

import { asRpcResult } from './rpc.js'

// A gateway that can `request()`. Kept structural so tests can pass a fake.
export interface PmGateway {
  request: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>
}

export type PMVenue = 'kalshi' | 'polymarket'

// ── wire shapes (mirror forecasting/pm/model.py to_dict) ────────────────────

export interface PMOutcomeDTO {
  label: string
  liquid: boolean
  market_id: string
  prob: number // de-vigged, sums to ~1 across a mutually-exclusive event
  raw_prob: number // pre-devig YES mid (honest raw-vs-devig labelling)
  volume: null | number
  yes_ask: null | number
  yes_bid: null | number
}

export interface PMDistributionHeadline {
  close_time: null | string
  n: number
  top_label: null | string
  top_prob: null | number
  total_volume: null | number
}

export interface PMDistributionDTO {
  binary: boolean
  close_time: null | string
  event_id: string
  headline: PMDistributionHeadline
  // True iff the probs were de-vig normalised (an earned, guaranteed partition).
  // When false the outcomes carry RAW mids that do NOT sum to 1 — the detail
  // pane must say so instead of claiming de-vig.
  normalized: boolean
  notes: string[]
  outcomes: PMOutcomeDTO[]
  overround: number
  title: string
  total_volume: number
  url: null | string
  venue: string
}

export interface PMMarketDTO {
  close_time: null | string
  event_id: null | string
  label: string
  last_price: null | number
  market_id: string
  open_interest: null | number
  question: string
  status: null | string
  token_ids: string[]
  url: null | string
  venue: string
  volume: null | number
  yes_ask: null | number
  yes_bid: null | number
  yes_mid: null | number
}

export interface PMEventDTO {
  category: null | string
  close_time: null | string
  event_id: string
  is_binary: boolean
  markets: PMMarketDTO[]
  mutually_exclusive: boolean
  slug: null | string
  title: string
  url: null | string
  venue: string
  volume: null | number
}

export interface PMOrderLevelDTO {
  price: number
  size: number
}

export interface PMOrderBookDTO {
  asks: PMOrderLevelDTO[]
  best_ask: null | number
  best_bid: null | number
  bids: PMOrderLevelDTO[]
  market_id: string
  mid: null | number
  tick_size: null | number
  timestamp: null | number
  venue: string
}

export interface PMHistoryPointDTO {
  p: number
  ts: number
}

// A list item pairs the raw event with its de-vigged distribution.
export interface PMListItem {
  distribution: PMDistributionDTO
  event: PMEventDTO
}

export type PMHistoryRange = '1d' | '1w' | 'all'

// ── fetchers ────────────────────────────────────────────────────────────────

export async function fetchPMList(
  gw: PmGateway,
  opts: { limit?: number; query?: string; tag?: string; venue?: PMVenue } = {}
): Promise<PMListItem[]> {
  const raw = await gw.request('pm.list', {
    ...(opts.venue ? { venue: opts.venue } : {}),
    ...(opts.query ? { query: opts.query } : {}),
    ...(opts.tag ? { tag: opts.tag } : {}),
    limit: opts.limit ?? 40
  })

  const res = asRpcResult<{ events?: PMListItem[] }>(raw)

  return Array.isArray(res?.events) ? res!.events : []
}

export async function fetchPMDetail(gw: PmGateway, venue: string, eventId: string): Promise<null | PMListItem> {
  const raw = await gw.request('pm.detail', { event_id: eventId, venue })
  const res = asRpcResult<PMListItem>(raw)

  return res?.event && res?.distribution ? res : null
}

export async function fetchPMBook(gw: PmGateway, venue: string, marketId: string): Promise<null | PMOrderBookDTO> {
  const raw = await gw.request('pm.book', { market_id: marketId, venue })
  const res = asRpcResult<{ book?: PMOrderBookDTO }>(raw)

  return res?.book ?? null
}

export async function fetchPMHistory(
  gw: PmGateway,
  venue: string,
  marketId: string,
  opts: { range?: PMHistoryRange; seriesTicker?: null | string } = {}
): Promise<PMHistoryPointDTO[]> {
  const raw = await gw.request('pm.history', {
    market_id: marketId,
    range: opts.range ?? '1w',
    ...(opts.seriesTicker ? { series_ticker: opts.seriesTicker } : {}),
    venue
  })

  const res = asRpcResult<{ points?: PMHistoryPointDTO[] }>(raw)

  return Array.isArray(res?.points) ? res!.points : []
}

export interface PMStreamStart {
  reason?: string
  streaming: boolean
  subscribed?: string[]
}

export async function startPMStream(gw: PmGateway, venue: string, marketIds: string[]): Promise<PMStreamStart> {
  const raw = await gw.request('pm.stream.start', { market_ids: marketIds, venue })
  const res = asRpcResult<PMStreamStart>(raw)

  return { reason: res?.reason, streaming: Boolean(res?.streaming), subscribed: res?.subscribed }
}

export async function stopPMStream(gw: PmGateway, venue: string, marketIds?: string[]): Promise<void> {
  await gw
    .request('pm.stream.stop', { venue, ...(marketIds ? { market_ids: marketIds } : {}) })
    .catch(() => undefined)
}

// ── venue-aware market reference ─────────────────────────────────────────────

// The id the book/history endpoints expect for a given outcome. Polymarket
// prices/books key on the YES CLOB token id (not the conditionId that the
// outcome carries as market_id); Kalshi keys on the market ticker directly.
export function bookMarketId(venue: string, market: PMMarketDTO | undefined, fallbackId: string): string {
  if (venue.toLowerCase() === 'polymarket') {
    return market?.token_ids?.[0] ?? fallbackId
  }

  return market?.market_id ?? fallbackId
}

// Kalshi candlesticks need the series ticker (carried on the event slug);
// Polymarket ignores it.
export function seriesTickerFor(venue: string, event: PMEventDTO | undefined): null | string {
  return venue.toLowerCase() === 'kalshi' ? (event?.slug ?? null) : null
}

// ── in-place tick folding (streaming) ────────────────────────────────────────

export interface PMTickPayload {
  kind: string
  market_id: string
  payload?: Record<string, unknown>
  venue: string
}

const toLevels = (raw: unknown): null | PMOrderLevelDTO[] => {
  if (!Array.isArray(raw)) {
    return null
  }

  const levels: PMOrderLevelDTO[] = []

  for (const entry of raw) {
    if (Array.isArray(entry) && entry.length >= 2) {
      levels.push({ price: Number(entry[0]), size: Number(entry[1]) })
    } else if (entry && typeof entry === 'object') {
      const o = entry as Record<string, unknown>
      levels.push({ price: Number(o.price), size: Number(o.size) })
    }
  }

  return levels.filter(l => Number.isFinite(l.price) && Number.isFinite(l.size))
}

// Fold a `pm.tick` book delta into the currently-shown book, matched by
// market_id. A price_change tick with no full book is a no-op on the ladders
// (the numeric mid is refreshed by the row-price applier below). Returns a new
// object when it changed, else the same reference (so React can bail on ===).
export function applyBookTick(book: null | PMOrderBookDTO, tick: PMTickPayload): null | PMOrderBookDTO {
  if (!book || tick.market_id !== book.market_id) {
    return book
  }

  const p = tick.payload ?? {}
  const bids = toLevels(p.bids ?? p.buys)
  const asks = toLevels(p.asks ?? p.sells)

  if (!bids && !asks) {
    return book
  }

  const nextBids = bids ?? book.bids
  const nextAsks = asks ?? book.asks

  return {
    ...book,
    asks: nextAsks,
    best_ask: nextAsks[0]?.price ?? null,
    best_bid: nextBids[0]?.price ?? null,
    bids: nextBids,
    mid: nextBids[0] && nextAsks[0] ? (nextBids[0].price + nextAsks[0].price) / 2 : book.mid,
    timestamp: typeof p.timestamp === 'number' ? p.timestamp : book.timestamp
  }
}

// The refreshed YES price a tick implies for the touched market (for the
// row-level repaint). Reads a mid/price field if the venue sent one, else
// derives it from a full book delta.
export function tickPrice(tick: PMTickPayload): null | number {
  const p = tick.payload ?? {}
  const direct = p.price ?? p.mid ?? p.yes_mid ?? p.last_price

  if (typeof direct === 'number' && Number.isFinite(direct)) {
    return direct
  }

  const bids = toLevels(p.bids ?? p.buys)
  const asks = toLevels(p.asks ?? p.sells)

  if (bids?.[0] && asks?.[0]) {
    return (bids[0].price + asks[0].price) / 2
  }

  return null
}

// ── display formatting ───────────────────────────────────────────────────────

export const fmtProb = (v: null | number | undefined): string =>
  v === null || v === undefined || !Number.isFinite(v) ? '—' : `${Math.round(v * 100)}%`

// A finer probability for the detail pane (one decimal).
export const fmtProb1 = (v: null | number | undefined): string =>
  v === null || v === undefined || !Number.isFinite(v) ? '—' : `${(v * 100).toFixed(1)}%`

export const fmtCents = (v: null | number | undefined): string =>
  v === null || v === undefined || !Number.isFinite(v) ? '—' : `${Math.round(v * 100)}¢`

export const fmtPMVol = (v: null | number | undefined): string => {
  if (v === null || v === undefined || !Number.isFinite(v)) {
    return '—'
  }

  const a = Math.abs(v)

  if (a >= 1e9) {
    return `$${(v / 1e9).toFixed(1)}B`
  }

  if (a >= 1e6) {
    return `$${(v / 1e6).toFixed(1)}M`
  }

  if (a >= 1e3) {
    return `$${(v / 1e3).toFixed(0)}K`
  }

  return `$${Math.round(v)}`
}

// Time-to-close from an ISO string: "3d" / "5h" / "22m" while open, the local
// date once it's more than a week out, "closed" in the past.
export const fmtClose = (iso: null | string | undefined): string => {
  if (!iso) {
    return '—'
  }

  const ts = Date.parse(iso)

  if (!Number.isFinite(ts)) {
    return '—'
  }

  const diff = ts - Date.now()

  if (diff <= 0) {
    return 'closed'
  }

  const mins = Math.floor(diff / 60_000)

  if (mins < 60) {
    return `${mins}m`
  }

  const hours = Math.floor(mins / 60)

  if (hours < 24) {
    return `${hours}h`
  }

  const days = Math.floor(hours / 24)

  if (days <= 7) {
    return `${days}d`
  }

  return new Date(ts).toLocaleDateString('en-US', { day: 'numeric', month: 'short' })
}

export const venueLabel = (venue: string): string =>
  venue.toLowerCase() === 'kalshi' ? 'Kalshi' : venue.toLowerCase() === 'polymarket' ? 'Polymarket' : venue

// A short, consistent venue chip for the dense tape ('poly' / 'kalshi') — always
// whole (never truncated mid-word), themed dim by the caller.
export const venueChip = (venue: string): string =>
  venue.toLowerCase() === 'kalshi' ? 'kalshi' : venue.toLowerCase() === 'polymarket' ? 'poly' : venue.toLowerCase()

// The YES bid/ask pair as integer cents ("40/42"), a single '—' when neither
// side is quoted (a degenerate/empty book — never a fabricated 0/0). A missing
// single side reads as '·' so the present side is still legible.
export const fmtBidAsk = (bid: null | number | undefined, ask: null | number | undefined): string => {
  const b = bid === null || bid === undefined ? null : bid
  const a = ask === null || ask === undefined ? null : ask

  if (b === null && a === null) {
    return '—'
  }

  const side = (v: null | number): string => (v === null ? '·' : String(Math.round(v * 100)))

  return `${side(b)}/${side(a)}`
}
