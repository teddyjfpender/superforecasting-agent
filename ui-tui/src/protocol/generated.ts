// GENERATED FILE — DO NOT EDIT BY HAND.
// Source of truth: the `protocol/` Python package (pydantic models).
// Regenerate:      python -m protocol.codegen
// Staleness gate:  python -m protocol.codegen --check

export const PROTOCOL_VERSION = 1

export type WireEventName = 'approval.request' | 'background.complete' | 'browser.progress' | 'clarify.request' | 'cron.fired' | 'error' | 'forecast.warnings.automode.complete' | 'forecast.warnings.automode.error' | 'forecast.warnings.automode.progress' | 'gateway.protocol_error' | 'gateway.ready' | 'gateway.start_timeout' | 'gateway.stderr' | 'jobs.complete' | 'jobs.error' | 'jobs.progress' | 'markets.model.complete' | 'markets.model.error' | 'markets.model.progress' | 'markets.model.refreshed' | 'message.complete' | 'message.delta' | 'message.start' | 'pm.tick' | 'reasoning.available' | 'reasoning.delta' | 'review.summary' | 'review.sweep' | 'secret.request' | 'session.info' | 'skin.changed' | 'status.update' | 'subagent.complete' | 'subagent.progress' | 'subagent.spawn_requested' | 'subagent.start' | 'subagent.thinking' | 'subagent.tool' | 'sudo.request' | 'thinking.delta' | 'tool.complete' | 'tool.generating' | 'tool.progress' | 'tool.start' | 'voice.status' | 'voice.transcript'

export const WIRE_EVENT_NAMES: readonly WireEventName[] = ['approval.request', 'background.complete', 'browser.progress', 'clarify.request', 'cron.fired', 'error', 'forecast.warnings.automode.complete', 'forecast.warnings.automode.error', 'forecast.warnings.automode.progress', 'gateway.protocol_error', 'gateway.ready', 'gateway.start_timeout', 'gateway.stderr', 'jobs.complete', 'jobs.error', 'jobs.progress', 'markets.model.complete', 'markets.model.error', 'markets.model.progress', 'markets.model.refreshed', 'message.complete', 'message.delta', 'message.start', 'pm.tick', 'reasoning.available', 'reasoning.delta', 'review.summary', 'review.sweep', 'secret.request', 'session.info', 'skin.changed', 'status.update', 'subagent.complete', 'subagent.progress', 'subagent.spawn_requested', 'subagent.start', 'subagent.thinking', 'subagent.tool', 'sudo.request', 'thinking.delta', 'tool.complete', 'tool.generating', 'tool.progress', 'tool.start', 'voice.status', 'voice.transcript']

export const WireEvent = {
  APPROVAL_REQUEST: 'approval.request',
  BACKGROUND_COMPLETE: 'background.complete',
  BROWSER_PROGRESS: 'browser.progress',
  CLARIFY_REQUEST: 'clarify.request',
  CRON_FIRED: 'cron.fired',
  ERROR: 'error',
  FORECAST_WARNINGS_AUTOMODE_COMPLETE: 'forecast.warnings.automode.complete',
  FORECAST_WARNINGS_AUTOMODE_ERROR: 'forecast.warnings.automode.error',
  FORECAST_WARNINGS_AUTOMODE_PROGRESS: 'forecast.warnings.automode.progress',
  GATEWAY_PROTOCOL_ERROR: 'gateway.protocol_error',
  GATEWAY_READY: 'gateway.ready',
  GATEWAY_START_TIMEOUT: 'gateway.start_timeout',
  GATEWAY_STDERR: 'gateway.stderr',
  JOBS_COMPLETE: 'jobs.complete',
  JOBS_ERROR: 'jobs.error',
  JOBS_PROGRESS: 'jobs.progress',
  MARKETS_MODEL_COMPLETE: 'markets.model.complete',
  MARKETS_MODEL_ERROR: 'markets.model.error',
  MARKETS_MODEL_PROGRESS: 'markets.model.progress',
  MARKETS_MODEL_REFRESHED: 'markets.model.refreshed',
  MESSAGE_COMPLETE: 'message.complete',
  MESSAGE_DELTA: 'message.delta',
  MESSAGE_START: 'message.start',
  PM_TICK: 'pm.tick',
  REASONING_AVAILABLE: 'reasoning.available',
  REASONING_DELTA: 'reasoning.delta',
  REVIEW_SUMMARY: 'review.summary',
  REVIEW_SWEEP: 'review.sweep',
  SECRET_REQUEST: 'secret.request',
  SESSION_INFO: 'session.info',
  SKIN_CHANGED: 'skin.changed',
  STATUS_UPDATE: 'status.update',
  SUBAGENT_COMPLETE: 'subagent.complete',
  SUBAGENT_PROGRESS: 'subagent.progress',
  SUBAGENT_SPAWN_REQUESTED: 'subagent.spawn_requested',
  SUBAGENT_START: 'subagent.start',
  SUBAGENT_THINKING: 'subagent.thinking',
  SUBAGENT_TOOL: 'subagent.tool',
  SUDO_REQUEST: 'sudo.request',
  THINKING_DELTA: 'thinking.delta',
  TOOL_COMPLETE: 'tool.complete',
  TOOL_GENERATING: 'tool.generating',
  TOOL_PROGRESS: 'tool.progress',
  TOOL_START: 'tool.start',
  VOICE_STATUS: 'voice.status',
  VOICE_TRANSCRIPT: 'voice.transcript',
} as const

export interface ApprovalRequestPayload {
  command: string
  description: string
  request_id?: string
}

export interface AutomodeCompletePayload {
  cancelled?: boolean
  dry_run?: boolean
  job_id: string
  processed?: number
  tally?: Record<string, unknown>
  total?: number
}

export interface AutomodeErrorPayload {
  job_id: string
  message?: string
}

export interface AutomodeProgressPayload {
  alert_id?: string
  cancelled?: boolean
  done?: number
  dry_run?: boolean
  job_id: string
  phase?: string
  reason?: string
  remaining?: number
  status?: string
  total?: number
}

export interface BackgroundCompletePayload {
  task_id: string
  text: string
}

export interface BrowserProgressPayload {
  level?: string
  message?: string
}

export interface ClarifyRequestPayload {
  choices: null | string[]
  question: string
  request_id: string
}

export interface CronFiredPayload {
  count?: number
}

export interface ErrorPayload {
  message: string
}

export interface GatewayProtocolErrorPayload {
  preview?: string
}

export interface GatewayReadyPayload {
  skin?: SkinPayload
}

export interface GatewayStartTimeoutPayload {
  cwd?: string
  python?: string
  stderr_tail?: string
}

export interface GatewayStderrPayload {
  line: string
}

export interface JobCompletePayload {
  job_id: string
  result: Record<string, unknown>
  type: string
}

export interface JobErrorPayload {
  job_id: string
  message: string
  type: string
}

export interface JobProgressPayload {
  job_id: string
  progress: Record<string, unknown>
  type: string
}

export interface JobRecordDTO {
  annotations: Record<string, unknown>
  cancel_requested: boolean
  created_at: string
  current: null | string
  done_count: number
  error: null | string
  job_id: string
  progress: Record<string, unknown>[]
  result: null | Record<string, unknown>
  spec: Record<string, unknown>
  status: string
  total: null | number
  type: string
  updated_at: null | string
}

export interface JobsActiveRequest {
  types: null | string[]
}

export interface JobsActiveResponse {
  count: number
  jobs: JobRecordDTO[]
}

export interface JobsCancelRequest {
  job_id: string
}

export interface JobsCancelResponse {
  cancelled: boolean
  found: boolean
  job_id: string
}

export interface JobsStartRequest {
  session_id: null | string
  spec: null | Record<string, unknown>
  type: string
}

export interface JobsStartResponse {
  job_id: string
  type: string
}

export interface JobsStatusRequest {
  job_id: string
}

export interface JobsStatusResponse {
  found: boolean
  job: null | JobRecordDTO
}

export interface MarketModelCompletePayload {
  id: string
  status?: string
  version?: number
}

export interface MarketModelErrorPayload {
  id: string
  message?: string
}

export interface MarketModelProgressPayload {
  id: string
  message?: string
  phase?: string
}

export interface MarketModelRefreshedPayload {
  id: string
  presentation?: Record<string, unknown>
}

export interface MarketQuotesRequest {
  series: MarketSeriesRef[]
}

export interface MarketQuotesResponse {
  quotes: Quote[]
}

export interface MarketSearchRequest {
  query: string
}

export interface MarketSearchResponse {
  results: MarketSearchResult[]
}

export interface MarketSearchResult {
  category: string
  name: string
  provider: string
  symbol: string
}

export interface MarketSeriesRef {
  category?: string
  line?: string
  name?: string
  provider: string
  symbol: string
  unit?: string
}

export interface MessageCompletePayload {
  reasoning?: string
  rendered?: string
  status: string
  text: string
  usage: Record<string, unknown>
  warning?: string
}

export interface MessageDeltaPayload {
  rendered?: string
  text?: string
}

export interface MessageStartPayload {
}

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

export interface Quote {
  asOf: number
  category: string
  change: null | number
  changePct: null | number
  currency: null | string
  dayHigh: null | number
  dayLow: null | number
  exchange: null | string
  history: number[]
  name: string
  prevClose: null | number
  provider: string
  symbol: string
  unit: string
  value: null | number
  volume: null | number
  week52High: null | number
  week52Low: null | number
}

export interface ReasoningAvailablePayload {
  text?: string
}

export interface ReasoningDeltaPayload {
  text?: string
}

export interface ReviewSummaryPayload {
  text?: string
}

export interface ReviewSweepPayload {
  alerts?: number
  due_count?: number
  duration_ms?: number
  phase: string
  refreshed?: number
}

export interface SecretRequestPayload {
  env_var: string
  metadata?: Record<string, unknown>
  prompt: string
  request_id: string
}

export interface SessionInfoPayload {
  cwd: string
  fast: boolean
  model: string
  profile_name: string
  reasoning_effort: string
  release_date: string
  service_tier: string
  skills: Record<string, unknown>
  tools: Record<string, unknown>
  update_behind: null | boolean
  update_command: string
  usage: Record<string, unknown>
  version: string
}

export interface SkinPayload {
  appearance?: string
  banner_hero?: string
  banner_logo?: string
  branding?: Record<string, unknown>
  colors?: Record<string, unknown>
  help_header?: string
  name?: string
  tool_prefix?: string
}

export interface StatusUpdatePayload {
  kind: string
  text: string
}

export interface SubagentEventDTO {
  api_calls?: number
  cost_usd?: number
  depth?: number
  duration_seconds?: number
  files_read?: string[]
  files_written?: string[]
  goal: string
  input_tokens?: number
  model?: string
  output_tail?: Record<string, unknown>[]
  output_tokens?: number
  parent_id?: string
  reasoning_tokens?: number
  status?: string
  subagent_id?: string
  summary?: string
  task_count: number
  task_index: number
  text?: string
  tool_count?: number
  tool_name?: string
  tool_preview?: string
  toolsets?: string[]
}

export interface SudoRequestPayload {
  request_id: string
}

export interface ThinkingDeltaPayload {
  text?: string
}

export interface ToolCompletePayload {
  duration_s?: number
  inline_diff?: string
  name?: string
  summary?: string
  todos?: unknown[]
  tool_id: string
}

export interface ToolGeneratingPayload {
  name?: string
}

export interface ToolProgressPayload {
  name?: string
  preview?: string
}

export interface ToolStartPayload {
  context?: string
  name?: string
  todos?: unknown[]
  tool_id: string
}

export interface VoiceStatusPayload {
  state?: string
}

export interface VoiceTranscriptPayload {
  no_speech_limit?: boolean
  text?: string
}
