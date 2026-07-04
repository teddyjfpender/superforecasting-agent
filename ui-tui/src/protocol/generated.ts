// GENERATED FILE — DO NOT EDIT BY HAND.
// Source of truth: the `protocol/` Python package (pydantic models).
// Regenerate:      python -m protocol.codegen
// Staleness gate:  python -m protocol.codegen --check

export const PROTOCOL_VERSION = 1

export type WireEventName = 'pm.tick'

export const WIRE_EVENT_NAMES: readonly WireEventName[] = ['pm.tick']

export interface PMDistributionDTO {
  binary: boolean
  close_time: null | string
  event_id: string
  headline: PMDistributionHeadline
  normalized: boolean
  notes: string[]
  outcomes: PMOutcomeDTO[]
  overround: number
  title: string
  total_volume: number
  url: null | string
  venue: string
}

export interface PMDistributionHeadline {
  close_time: null | string
  n: number
  top_label: null | string
  top_prob: null | number
  total_volume: number
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

export interface PMHistoryPointDTO {
  p: number
  ts: number
}

export interface PMListItem {
  distribution: PMDistributionDTO
  event: PMEventDTO
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

export interface PMOrderLevelDTO {
  price: number
  size: number
}

export interface PMOutcomeDTO {
  label: string
  liquid: boolean
  market_id: string
  prob: number
  raw_prob: number
  volume: null | number
  yes_ask: null | number
  yes_bid: null | number
}

export interface PMStreamStart {
  reason?: string
  streaming: boolean
  subscribed?: string[]
}

export interface PMTickPayload {
  estimate: null | number
  kind: string
  market_id: string
  payload: Record<string, unknown>
  venue: string
}

export interface PmBookRequest {
  market_id: string
  venue: string
}

export interface PmBookResponse {
  book: PMOrderBookDTO
}

export interface PmDetailRequest {
  event_id: string
  venue: string
}

export interface PmDetailResponse {
  distribution: PMDistributionDTO
  event: PMEventDTO
}

export interface PmHistoryRequest {
  interval: null | string
  market_id: string
  max_points: null | number
  period_interval: null | number
  range: null | string
  series_ticker: null | string
  venue: string
}

export interface PmHistoryResponse {
  count: number
  points: PMHistoryPointDTO[]
}

export interface PmListRequest {
  limit: null | number
  query: null | string
  tag: null | string
  venue: null | string
}

export interface PmListResponse {
  count: number
  events: PMListItem[]
}

export interface PmStreamStartRequest {
  market_ids: null | string[]
  venue: string
}

export interface PmStreamStopRequest {
  market_ids: null | string[]
  venue: string
}

export interface PmStreamStopResponse {
  closed?: boolean
  remaining?: string[]
  stopped: boolean
  venue: string
}
