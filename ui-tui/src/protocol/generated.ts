// GENERATED FILE — DO NOT EDIT BY HAND.
// Source of truth: the `protocol/` Python package (pydantic models).
// Regenerate:      python -m protocol.codegen
// Staleness gate:  python -m protocol.codegen --check

export const PROTOCOL_VERSION = 1

export type WireEventName = 'approval.request' | 'background.complete' | 'browser.progress' | 'clarify.request' | 'command.finished' | 'command.output' | 'command.started' | 'cron.fired' | 'error' | 'forecast.warnings.automode.complete' | 'forecast.warnings.automode.error' | 'forecast.warnings.automode.progress' | 'gateway.protocol_error' | 'gateway.ready' | 'gateway.start_timeout' | 'gateway.stderr' | 'jobs.complete' | 'jobs.error' | 'jobs.progress' | 'markets.model.complete' | 'markets.model.error' | 'markets.model.progress' | 'markets.model.refreshed' | 'message.complete' | 'message.delta' | 'message.start' | 'pm.tick' | 'reasoning.available' | 'reasoning.delta' | 'review.summary' | 'review.sweep' | 'secret.request' | 'session.info' | 'skin.changed' | 'status.update' | 'subagent.complete' | 'subagent.progress' | 'subagent.spawn_requested' | 'subagent.start' | 'subagent.thinking' | 'subagent.tool' | 'sudo.request' | 'thinking.delta' | 'tool.complete' | 'tool.generating' | 'tool.progress' | 'tool.start' | 'voice.status' | 'voice.transcript'

export const WIRE_EVENT_NAMES: readonly WireEventName[] = ['approval.request', 'background.complete', 'browser.progress', 'clarify.request', 'command.finished', 'command.output', 'command.started', 'cron.fired', 'error', 'forecast.warnings.automode.complete', 'forecast.warnings.automode.error', 'forecast.warnings.automode.progress', 'gateway.protocol_error', 'gateway.ready', 'gateway.start_timeout', 'gateway.stderr', 'jobs.complete', 'jobs.error', 'jobs.progress', 'markets.model.complete', 'markets.model.error', 'markets.model.progress', 'markets.model.refreshed', 'message.complete', 'message.delta', 'message.start', 'pm.tick', 'reasoning.available', 'reasoning.delta', 'review.summary', 'review.sweep', 'secret.request', 'session.info', 'skin.changed', 'status.update', 'subagent.complete', 'subagent.progress', 'subagent.spawn_requested', 'subagent.start', 'subagent.thinking', 'subagent.tool', 'sudo.request', 'thinking.delta', 'tool.complete', 'tool.generating', 'tool.progress', 'tool.start', 'voice.status', 'voice.transcript']

export const WireEvent = {
  APPROVAL_REQUEST: 'approval.request',
  BACKGROUND_COMPLETE: 'background.complete',
  BROWSER_PROGRESS: 'browser.progress',
  CLARIFY_REQUEST: 'clarify.request',
  COMMAND_FINISHED: 'command.finished',
  COMMAND_OUTPUT: 'command.output',
  COMMAND_STARTED: 'command.started',
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

export interface AckRequestBody {
  correlation_id: string
  intent: string
  note: null | string
  question_ref: null | SfpQuestionRef
  request_kind: null | string
  signal: null | string
}

export interface AgentProcess {
  command: string
  session_id: string
  status: string
  uptime: number
}

export interface AgentsActiveKinds {
  procs: number
  quorum: number
  reforecast: number
}

export interface AgentsActiveSummaryRequest {
}

export interface AgentsActiveSummaryResponse {
  count: number
  headline: string
  kinds: AgentsActiveKinds
}

export interface AgentsListRequest {
}

export interface AgentsListResponse {
  processes: AgentProcess[]
}

export interface ApprovalRequestPayload {
  command: string
  description: string
  request_id?: string
}

export interface ApprovalRespondRequest {
  all: boolean
  choice: string
  request_id: null | string
  session_id: null | string
}

export interface ApprovalRespondResponse {
  ok?: boolean
}

export interface ApprovalResult {
  choice: 'always' | 'deny' | 'once' | 'session'
}

export interface AuthPollRequest {
  cancel: boolean
  session_id: null | string
}

export interface AuthPollResponse {
  credentials_applied?: boolean
  message?: string
  provider?: null | string
  status: string
  url?: null | string
  user_code?: null | string
}

export interface AuthStartRequest {
  provider: string
  session_id: null | string
}

export interface AuthStartResponse {
  interval: number
  provider: string
  url: string
  user_code: string
}

export interface AutomodeCancelRequest {
  job_id: string
}

export interface AutomodeCancelResponse {
  cancelled?: boolean
  found: boolean
  job_id: string
}

export interface AutomodeCompletePayload {
  cancelled?: boolean
  dry_run?: boolean
  failures?: Record<string, unknown>
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
  failures?: Record<string, unknown>
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

export interface BackgroundStartResponse {
  task_id?: string
}

export interface BrowserManageRequest {
  action: null | string
  session_id: null | string
  url: null | string
}

export interface BrowserManageResponse {
  connected?: boolean
  messages?: string[]
  url?: string
}

export interface BrowserProgressPayload {
  level?: string
  message?: string
}

export interface BuildInfoPayload {
  behind?: null | number
  install_method?: string
  latest_version?: string
  release_date?: string
  remedy?: string
  stale?: boolean
  version: string
}

export interface ClarifyRequestPayload {
  choices: null | string[]
  question: string
  request_id: string
}

export interface ClarifyRespondRequest {
  answer: string
  request_id: null | string
  session_id: null | string
}

export interface ClarifyRespondResponse {
  ok?: boolean
}

export interface ClarifyResult {
  answer: string
}

export interface CliExecRequest {
  argv: string[]
  timeout: number
}

export interface CliExecResponse {
  blocked: boolean
  code: number
  hint?: string
  output: string
}

export interface ClipboardPasteRequest {
  session_id: null | string
}

export interface ClipboardPasteResponse {
  attached?: boolean
  count?: number
  height?: number
  message?: string
  token_estimate?: number
  width?: number
}

export interface CommandAliasResult {
  target: string
  type: 'alias'
}

export interface CommandDispatchRequest {
  arg: string
  name: string
  session_id: null | string
}

export type CommandDispatchResponse = CommandAliasResult | CommandExecResult | CommandSendResult | CommandSkillResult

export interface CommandExecResult {
  output: string
  type: 'exec' | 'plugin'
}

export interface CommandFinished {
  command_id: string
  status: 'cancelled' | 'failed' | 'finished'
}

export interface CommandOutput {
  command_id: string
  stream: 'stderr' | 'stdout'
  text: string
}

export interface CommandResolveRequest {
  name: string
}

export interface CommandResolveResponse {
  canonical: string
  category: string
  description: string
}

export interface CommandSendResult {
  message: string
  notice?: string
  type: 'send'
}

export interface CommandSkillResult {
  message: string
  name: string
  type: 'skill'
}

export interface CommandStarted {
  command_id: string
  name: string
  request_id: string
}

export interface CommandsCatalogRequest {
}

export interface CommandsCatalogResponse {
  canon?: Record<string, string>
  categories?: SlashCategory[]
  pairs?: [string, string][]
  skill_count?: number
  sub?: Record<string, string[]>
  warning?: string
}

export interface CompletionRequest {
  text: null | string
  word: null | string
}

export interface CompletionResponse {
  items?: GatewayCompletionItem[]
  replace_from?: number
}

export interface ConfigDisplayConfig {
  bell_on_complete?: boolean
  busy_input_mode?: string
  details_mode?: string
  inline_diffs?: boolean
  mouse_tracking?: null | boolean | number | string
  sections?: Record<string, string>
  show_cost?: boolean
  show_reasoning?: boolean
  streaming?: boolean
  thinking_mode?: string
  tui_auto_resume_recent?: boolean
  tui_compact?: boolean
  tui_mouse?: null | boolean | number | string
  tui_status_indicator?: string
  tui_statusbar?: 'bottom' | 'off' | 'on' | 'top' | boolean
}

export interface ConfigFullConfig {
  display?: ConfigDisplayConfig
  voice?: ConfigVoiceConfig
}

export interface ConfigFullResponse {
  authentication_status?: string
  config?: ConfigFullConfig
  display?: string
  home?: string
  model?: string
  mtime?: number
  prompt?: string
  provider?: string
  providers?: Record<string, unknown>[]
  value?: string
}

export interface ConfigGetValueRequest {
  key: null | string
  session_id: null | string
}

export interface ConfigGetValueResponse {
  display?: string
  home?: string
  value?: string
}

export interface ConfigMtimeResponse {
  mtime?: number
}

export interface ConfigProviderEntry {
  aliases: string[]
  authenticated: null
  id: string
  label: string
}

export interface ConfigProviderResponse {
  authentication_status: 'not_checked'
  model: string
  provider: string
  providers: ConfigProviderEntry[]
}

export interface ConfigSetRequest {
  key: null | string
  session_id: null | string
  value: null | string
}

export interface ConfigSetResponse {
  credential_warning?: string
  history_reset?: boolean
  info?: SessionInfo
  value?: string
  warning?: string
}

export interface ConfigVoiceConfig {
  record_key?: unknown
}

export interface CronFiredPayload {
  count?: number
}

export interface CronManageRequest {
  action: string
  name: string
  prompt: string
  schedule: string
}

export interface CronManageResponse {
  count?: number
  error?: string
  job?: Record<string, unknown>
  jobs?: Record<string, unknown>[]
  message?: string
  status?: string
  success?: boolean
}

export interface DataCatalog {
  categories: Array<DataCategory>
  countries: Array<DataCountry>
  presets: Array<DataPreset>
  providers: Array<DataProvider>
  regions: Array<DataRegion>
  series: Array<DataSeries>
  version: number
}

export interface DataCategory {
  aliases: Array<string>
  group: string
  id: string
  name: string
}

export interface DataCountry {
  id: string
  name: string
  region: string
}

export interface DataEvent {
  area: null | string
  description: string
  effective_at: null | string
  event_id: string
  expires_at: null | string
  issued_at: null | string
  severity: null | string
  source_url: null | string
  title: string
}

export interface DataEvents {
  events: DataEvent[]
  retrieved_at: string
  series_id: string
  truncated: boolean
}

export interface DataLocation {
  latitude: number
  longitude: number
  name: string
  timezone: string
}

export interface DataPreset {
  description: string
  id: string
  name: string
  series_ids: Array<string>
  version: number
}

export interface DataProvider {
  access_note: string
  auth: 'none' | 'optional' | 'required'
  capabilities: Array<'events' | 'history' | 'latest' | 'search' | 'stream'>
  description: string
  id: string
  key_env: null | string
  name: string
  signup_url: null | string
  website: string
}

export interface DataRegion {
  id: string
  members: Array<string>
  name: string
}

export interface DataSeries {
  category: string
  change_basis: 'last_transition' | 'previous_observation'
  concept_id: string
  country: null | string
  dimensions: Record<string, string>
  expected_lag_seconds: null | number
  frequency: 'annual' | 'daily' | 'event' | 'hourly' | 'monthly' | 'quarterly' | 'tick' | 'weekly'
  history_points: number
  id: string
  kind: 'estimate' | 'event' | 'forecast' | 'observation' | 'probability' | 'quote' | 'reanalysis'
  line: null | string
  location: null | DataLocation
  name: string
  provider: string
  refresh_seconds: number
  region: string
  revision_policy: 'as_issued' | 'first_release' | 'latest' | 'unknown'
  source_family: string
  source_url: string
  symbol: string
  tags: Array<string>
  unit: string
}

export interface DatedValue {
  period_end: string
  period_start: string
  published_at: null | string
  status: null | string
  value: null | number
}

export interface DelegationActiveEntry {
  depth?: number
  goal?: string
  kind?: string
  model?: null | string
  parent_id?: null | string
  started_at?: number
  status?: string
  subagent_id?: string
  tool_count?: number
}

export interface DelegationBackgroundEntry {
  delegation_id: string
  dispatched_at?: number
  durable_status?: string
  goal?: string
  model?: null | string
  result?: null | Record<string, unknown>
  status: string
}

export interface DelegationPauseRequest {
  paused: null | boolean
  session_id?: string
}

export interface DelegationPauseResponse {
  paused?: boolean
}

export interface DelegationStatusRequest {
  session_id?: string
}

export interface DelegationStatusResponse {
  active?: DelegationActiveEntry[]
  background?: DelegationBackgroundEntry[]
  max_async_children?: number
  max_concurrent_children?: number
  max_spawn_depth?: number
  paused?: boolean
}

export interface DeskCustomSeries {
  category: string
  line: null | string
  name: string
  provider: string
  symbol: string
  unit: string
}

export interface DeskEdit {
  add: string[]
  catalog_revision: string
  custom_add?: DeskCustomSeries[]
  custom_remove?: DeskCustomSeries[]
  home_region?: null | string
  preset_id: null | string
  remove: string[]
  start_empty: boolean
  weather_locations?: null | string[]
}

export interface DeskPatch {
  categories?: null | string[]
  custom?: null | DeskCustomSeries[]
  pm_saved?: null | DeskSavedEvent[]
  providers?: null | string[]
  server_side?: null | string[]
  watchlist?: null | DeskCustomSeries[]
}

export interface DeskPreview {
  added: string[]
  already_selected: string[]
  catalog_revision: string
  credential_providers: string[]
  removed: string[]
  revision: string
  selection: DeskSelection
}

export interface DeskSavedEvent {
  event_id: string
  venue: string
}

export interface DeskSelection {
  categories: string[]
  custom: DeskCustomSeries[]
  home_region: null | string
  pm_saved: DeskSavedEvent[]
  providers: string[]
  revision: string
  series_ids: string[]
  server_side: null | string[]
  state: 'custom' | 'empty' | 'preset' | 'unconfigured'
  watchlist: DeskCustomSeries[]
  weather_locations: null | string[]
}

export interface EmptyRequest {
}

export interface ErrorPayload {
  durable_status?: string
  message: string
  turn_id?: string
}

export interface EventsReplayRequest {
  limit: number
  session_id: string
  since_id: number
  types: null | string | string[]
}

export interface EventsReplayResponse {
  count: number
  frames: Record<string, unknown>[]
  last_id: number
  records: Record<string, unknown>[]
  session_id: string
  since_id: number
}

export interface EvidenceShareBody {
  available_at: null | string
  captured_at: string
  claim: string
  evidence_id: null | string
  excerpt: null | string
  published_at: null | string
  sha256: string
  source_name: null | string
  source_type: string
  source_url: null | string
  stance: null | string
  triage_label: null | string
}

export interface FeedShare {
  feeds: SharedFeed[]
  horizon: SharedPeriod
  presentation: 'bar-chart' | 'line-chart'
  type: 'sfa.feed'
  version: number | number
}

export interface ForecastAnalystNote {
  as_of?: string
  be_aware?: string
  body?: string
  created_at?: string
  forecast_id?: null | string
  generator?: string
  headline?: string
  how_it_feels?: string
  how_it_thinks?: string
  kind?: string
  looking_for?: string
  stance?: null | string
  verdict?: null | string
}

export interface ForecastArticleAttachRequest {
  article: ForecastArticleClaim
  prepare_update: boolean
  question_id: string
}

export interface ForecastArticleAttachResponse {
  already_attached: boolean
  evidence_id: string
  interview_id: null | string
  question_id: string
}

export interface ForecastArticleClaim {
  content: string
  extraction: 'article' | 'feed'
  feed_url: string
  published_at: null | string
  publisher: string
  title: string
  url: string
}

export interface ForecastBenchAggregate {
  mean_agent_brier?: null | number
  mean_brier_edge?: null | number
  mean_market_brier?: null | number
  n?: number
}

export interface ForecastBenchRequest {
  limit: null | number
}

export interface ForecastBenchResponse {
  aggregate?: ForecastBenchAggregate
  count?: number
  generated_at?: string
  output?: string
  product?: string
  resolved_count?: number
  rows?: ForecastBenchRow[]
}

export interface ForecastBenchRow {
  agent_brier?: null | number
  agent_probability?: null | number
  agent_probability_display?: string
  as_of?: null | string
  brier_edge?: null | number
  domain?: null | string
  id: string
  market_brier?: null | number
  market_probability?: null | number
  market_probability_display?: string
  outcome?: null | number
  outcome_label?: null | string
  resolved?: boolean
  resolved_at?: null | string
  source?: null | string
  title?: string
  topics?: string[]
}

export interface ForecastCalibrationBias {
  advisory_text?: null | string
  ci_high?: null | number
  ci_low?: null | number
  curve_shape?: Record<string, unknown>[]
  direction?: null | string
  ece?: null | number
  ess?: number
  ess_min?: number
  horizon_label?: null | string
  n?: number
  notes?: string[]
  pvalue?: null | number
  sce_raw?: null | number
  sce_shrunk?: null | number
  scope_ref?: null | string
  scope_type?: string
  status?: string
}

export interface ForecastCalibrationBreakdownRow {
  bias?: null | ForecastCalibrationBias
  calibration_curve_sample_count?: number
  count?: number
  domain?: string
  expected_calibration_error?: null | number
  mean_brier?: null | number
  mean_predicted?: null | number
  observed_frequency?: null | number
  origin?: string
}

export interface ForecastCalibrationBucketRow {
  bucket?: string
  count?: number
  mean_brier?: null | number
  sample_status?: string
}

export interface ForecastCalibrationCurveRow {
  bucket?: string
  calibration_gap?: null | number
  count?: number
  mean_predicted?: null | number
  observed_frequency?: null | number
  sample_status?: string
}

export interface ForecastCalibrationLesson {
  coverage?: ForecastCalibrationLessonCoverage
  dormant?: boolean
  lesson?: null | string
  lesson_id?: string
  recommended_adjustment?: Record<string, unknown>
  scope?: string
  scope_ref?: null | string
  scope_type?: string
}

export interface ForecastCalibrationLessonCoverage {
  application_rate?: number
  applied_count?: number
  in_scope_count?: number
  last_seen?: null | string
}

export interface ForecastCalibrationRequest {
  domain: null | string
  origin: null | string
}

export interface ForecastCalibrationResponse {
  bias?: null | ForecastCalibrationBias
  cohort_scoreboard?: ForecastCohortScoreboard
  domain?: null | string
  domains?: ForecastCalibrationBreakdownRow[]
  lessons?: ForecastCalibrationLesson[]
  origin?: null | string
  origins?: ForecastCalibrationBreakdownRow[]
  summary?: ForecastCalibrationSummary
}

export interface ForecastCalibrationSummary {
  buckets?: ForecastCalibrationBucketRow[]
  calibration_curve?: ForecastCalibrationCurveRow[]
  calibration_curve_sample_count?: number
  calibration_eligible?: null | boolean
  calibration_trend?: ForecastCalibrationTrend
  count?: number
  domain?: null | string
  ensemble_component_contributions?: ForecastDashboardCalibrationComponent[]
  expected_calibration_error?: null | number
  forecast_origin?: null | string
  horizon?: null | string
  max_calibration_error?: null | number
  mean_abs_probability_movement_before_close?: null | number
  mean_brier?: null | number
  mean_log_score?: null | number
  mean_predicted?: null | number
  mean_probability_movement_before_close?: null | number
  mean_sharpness?: null | number
  observed_frequency?: null | number
  probability_movement_count?: number
  question_type_breakdown?: ForecastDashboardQuestionTypeCalibration[]
}

export interface ForecastCalibrationTrend {
  direction?: string
  windows?: ForecastCalibrationTrendWindow[]
}

export interface ForecastCalibrationTrendWindow {
  brier?: null | number
  n?: number
  period?: string
  sce?: null | number
}

export interface ForecastCandidateInterval {
  hi: number
  lo: number
  mid?: number
}

export interface ForecastCardBody {
  as_of: string
  band: null | SfpBand
  criteria_hash: string
  distribution: null | Record<string, unknown>
  evidence_refs: SfpEvidenceRef[]
  horizon_days: null | number
  outcome_type: string
  probability: null | number
  question_id: null | string
  question_title: string
  rationale_bullets: string[]
}

export interface ForecastCohortScoreboard {
  cohorts?: Record<string, unknown>
  continuous_scorecard?: ForecastContinuousScorecard
  difficulty_adjustment?: ForecastDifficultyAdjustment
  pooled_diagnostic?: ForecastPooledDiagnostic
  quarantined?: ForecastQuarantineSummary
}

export interface ForecastCommandRequest {
  arg: null | string
  argv: null | string[]
}

export interface ForecastCommandResponse {
  code?: number
  output?: string
}

export interface ForecastConfigDecision {
  action_threshold?: null | string
  decision_deadline?: null | string
  decision_owner?: null | string
  update_triggers?: unknown[]
}

export interface ForecastConfigGate {
  category?: string
  default?: string
  doc?: string
  id: string
  label: string
  looser?: boolean
  severity: string
  source: string
}

export interface ForecastConfigRequest {
  id: null | string
  question_id: null | string
}

export interface ForecastConfigResponse {
  cadence?: null | string
  decision?: ForecastConfigDecision
  gates?: ForecastConfigGate[]
  impact?: null | string
  next_run_at?: null | string
  profile?: string
  question_id?: string
  thresholds?: ForecastConfigThreshold[]
  title?: string
}

export interface ForecastConfigSetRequest {
  decision: null | Record<string, unknown>
  hooks: null | Record<string, unknown>
  id: null | string
  question_id: null | string
  review_cadence: null | string
}

export interface ForecastConfigThreshold {
  default: number
  direction?: string
  help?: string
  integer?: boolean
  key: string
  label: string
  looser?: boolean
  maximum: number
  minimum: number
  rule_ids?: string[]
  source: string
  value: number
}

export interface ForecastContinuousScorecard {
  by_rule?: Record<string, unknown>
  domains?: string[]
  live_calibration_eligible_n?: number
  mean_crps?: null | number
  mean_log_score?: null | number
  n?: number
}

export interface ForecastDashboardAlert {
  acknowledged_at?: null | string
  created_at?: string
  id?: string
  reason?: string
  recommended_action?: string
  scope_ref?: string
  scope_type?: string
  severity?: string
}

export interface ForecastDashboardBacktest {
  agent_edge?: null | number
  agent_mean_brier?: null | number
  best_baseline?: null | string
  best_baseline_brier?: null | number
  case_count?: number
  claim_status?: ForecastDashboardClaimStatus
  dataset?: string
  id?: string
  leakage_checks_passed?: boolean
  paired_agent_edge?: null | number
  paired_agent_edge_ci95_high?: null | number
  paired_agent_edge_ci95_low?: null | number
  paired_agent_wins?: number
  paired_baseline_wins?: number
  paired_count?: number
  paired_ties?: number
  probability_sources?: string[]
}

export interface ForecastDashboardCalibration {
  calibration_eligible?: null | boolean
  count?: number
  domain?: null | string
  ensemble_component_contributions?: ForecastDashboardCalibrationComponent[]
  forecast_origin?: null | string
  horizon?: null | string
  mean_abs_probability_movement_before_close?: null | number
  mean_brier?: null | number
  mean_log_score?: null | number
  mean_probability_movement_before_close?: null | number
  mean_sharpness?: null | number
  probability_movement_count?: number
  question_type_breakdown?: ForecastDashboardQuestionTypeCalibration[]
}

export interface ForecastDashboardCalibrationComponent {
  count?: number
  mean_abs_distance_from_forecast?: null | number
  mean_contribution?: null | number
  mean_probability?: null | number
  mean_weight?: null | number
  mean_weight_share?: null | number
  name?: string
}

export interface ForecastDashboardClaimStatus {
  can_claim_live_superforecasting?: boolean
  case_count?: number
  evidence_type?: string
  leakage_checks_passed?: boolean
  message?: string
  scored_count?: number
  verdict?: string
}

export interface ForecastDashboardDoctor {
  claim_live_superforecasting?: boolean
  doctor_status?: string
  next_action?: string
  next_actions?: ForecastDoctorNextAction[]
  next_requirement?: string
  pilot_gap_count?: number
  pilot_passed_checks?: number
  pilot_status?: string
  pilot_total_checks?: number
  readiness_gap_count?: number
  readiness_verdict?: string
  scheduled_review_run_count?: number
  tester_handoff_ready?: boolean
}

export interface ForecastDashboardErrorProfile {
  domain?: null | string
  id?: string
  mean_brier?: null | number
  question_type?: null | string
  recommended_adjustments?: string[]
  recurring_errors?: string[]
  sample_count?: number
  topic?: null | string
  updated_at?: null | string
}

export interface ForecastDashboardEvidenceStatus {
  backtests?: ForecastEvidenceBacktests
  can_claim_live_superforecasting?: boolean
  gaps?: string[]
  message?: string
  next_actions?: ForecastEvidenceNextAction[]
  requirements?: ForecastEvidenceRequirement[]
  score_counts?: ForecastEvidenceScoreCounts
  verdict?: string
}

export interface ForecastDashboardFactor {
  coverage?: null | number
  cvar?: null | number
  delta?: null | number
  domain?: null | string
  downside?: null | number
  id?: string
  mean?: null | number
  member_count?: number
  q05?: null | number
  q95?: null | number
  sd?: null | number
  status?: string
  title?: string
  units?: null | string
}

export interface ForecastDashboardLearning {
  active_lessons?: number
  effectiveness?: ForecastLearningEffectiveness
  invalidated_lessons?: number
  recent_lessons?: ForecastDashboardLesson[]
  tentative_lessons?: number
  top_error_profiles?: ForecastDashboardErrorProfile[]
  total_lessons?: number
  trials?: Record<string, number>
}

export interface ForecastDashboardLesson {
  confidence?: null | number
  id?: string
  lesson?: string
  recommended_adjustment?: Record<string, unknown>
  scope_ref?: null | string
  scope_type?: null | string
  source_postmortem_count?: number
  source_score_count?: number
  status?: string
  updated_at?: null | string
}

export interface ForecastDashboardLiveBaseline {
  baseline_type?: string
  mean_brier?: null | number
  mean_brier_improvement_vs_baseline?: null | number
  paired_agent_edge_ci95_high?: null | number
  paired_agent_edge_ci95_low?: null | number
  paired_agent_edge_mean_brier?: null | number
  paired_agent_mean_brier?: null | number
  paired_agent_wins?: number
  paired_baseline_mean_brier?: null | number
  paired_baseline_wins?: number
  paired_count?: number
  paired_ties?: number
  source?: string
}

export interface ForecastDashboardLivePerformance {
  agent?: ForecastLivePerformanceAgent
  baselines?: ForecastDashboardLiveBaseline[]
  claim_status?: ForecastDashboardClaimStatus
  score_count?: number
}

export interface ForecastDashboardQuestion {
  as_of?: null | string
  baseline_count?: number
  close_time?: null | string
  confidence?: null | number
  delta?: null | number
  domain?: null | string
  evidence_count?: number
  id?: string
  latest_evidence_at?: null | string
  latest_evidence_claim?: null | string
  latest_evidence_summary?: null | string
  latest_rationale?: null | string
  open_alert_count?: number
  open_assumption_count?: number
  open_reference_class_count?: number
  operations?: Record<string, unknown>
  probability?: null | Record<string, unknown> | number | string
  resolution_time?: null | string
  stale_assumption_count?: number
  stale_reference_class_count?: number
  status?: string
  tail_audit?: null | ForecastTailAudit
  title?: string
  topics?: string[]
}

export interface ForecastDashboardQuestionTypeCalibration {
  brier_count?: number
  count?: number
  mean_brier?: null | number
  mean_log_score?: null | number
  mean_proper_score?: null | number
  mean_sharpness?: null | number
  question_type?: string
  score_rules?: string[]
}

export interface ForecastDashboardRequest {
  fast: null | boolean
  limit: null | number
  summary_only: null | boolean
}

export interface ForecastDashboardResponse {
  output?: string
  summary?: ForecastDashboardSummary
}

export interface ForecastDashboardReview {
  as_of?: null | string
  close_time?: null | string
  domain?: null | string
  id?: string
  latest_evidence_at?: null | string
  latest_evidence_claim?: null | string
  latest_evidence_summary?: null | string
  latest_rationale?: null | string
  next_action?: string
  priority?: number
  probability?: null | Record<string, unknown> | number | string
  reasons?: string[]
  resolution_time?: null | string
  title?: string
}

export interface ForecastDashboardScheduleRun {
  alert_count?: number
  alert_reasons?: string[]
  auto_postmortem?: boolean
  auto_score?: boolean
  cadence?: null | string
  id?: string
  learning_review_count?: number
  next_run_at?: string
  postmortem_count?: number
  run_at?: string
  scheduled_review_id?: string
  scope_ref?: null | string
  scope_type?: null | string
  score_count?: number
  status?: string
}

export interface ForecastDashboardSummary {
  active_count?: number
  alerts?: ForecastDashboardAlert[]
  calibration?: ForecastDashboardCalibration
  closing_soon_count?: number
  doctor?: ForecastDashboardDoctor
  entity_count?: number
  evidence_status?: ForecastDashboardEvidenceStatus
  factor_count?: number
  factors?: ForecastDashboardFactor[]
  learning?: ForecastDashboardLearning
  lifecycle?: ForecastLifecycleSummary
  live_performance?: ForecastDashboardLivePerformance
  open_alert_count?: number
  open_assumption_count?: number
  open_reference_class_count?: number
  product?: string
  question_total?: number
  questions?: ForecastDashboardQuestion[]
  recent_backtests?: ForecastDashboardBacktest[]
  review_queue?: ForecastDashboardReview[]
  review_queue_count?: number
  scheduled_review_run_count?: number
  scheduled_review_runs?: ForecastDashboardScheduleRun[]
  stale_assumption_count?: number
  stale_reference_class_count?: number
  theses?: ForecastDashboardThesis[]
  thesis_count?: number
}

export interface ForecastDashboardThesis {
  coverage?: null | number
  delta?: null | number
  domain?: null | string
  health_display?: string
  health_probability?: null | number
  id?: string
  member_count?: number
  n_eff?: null | number
  status?: string
  thesis_score?: null | number
  title?: string
}

export interface ForecastDeskTaskRequest {
  instruction: null | string
  max_iterations: null | number
  model: null | string
  provider: null | string
  question_ids: null | string[]
  session_id: null | string
}

export interface ForecastDifficultyAdjustment {
  limits?: string
  method?: string
  n_eligible?: number
  n_no_anchor?: number
  provenance?: Record<string, unknown>
  reference_difficulty?: null | number
}

export interface ForecastDoctorNextAction {
  action?: string
  requirement_id?: string
  source?: string
}

export interface ForecastEvidenceBacktests {
  agent_protocol_scored_count?: number
  distinct_dataset_count?: number
  external_dataset_count?: number
  external_source_family_count?: number
  leakage_free_run_count?: number
  positive_best_baseline_edge_run_count?: number
  run_count?: number
  source_families?: string[]
}

export interface ForecastEvidenceNextAction {
  action?: string
  requirement_id?: string
}

export interface ForecastEvidenceRequirement {
  description?: string
  id?: string
  observed?: number
  passed?: boolean
  recommended_action?: string
  required?: number
}

export interface ForecastEvidenceScoreCounts {
  backtest?: number
  imported_baseline?: number
  live?: number
}

export interface ForecastFactor {
  aggregate_stale?: boolean
  analyst_note?: null | ForecastAnalystNote
  as_of?: null | string
  constituents?: ForecastFactorConstituent[]
  coverage?: null | number
  cvar?: null | number
  delta?: null | number
  domain?: null | string
  downside?: null | number
  freshness?: string
  history?: ForecastFactorHistoryPoint[]
  id?: string
  mean?: null | number
  member_count?: number
  n_eff?: null | number
  q05?: null | number
  q50?: null | number
  q95?: null | number
  question_ids?: string[]
  rationale?: null | string
  sd?: null | number
  snapshot_count?: number
  title?: string
  topics?: string[]
  units?: null | string
  volatility?: null | number
}

export interface ForecastFactorConstituent {
  contribution?: null | number
  direction?: string
  flags?: string[]
  id?: string
  mean?: null | number
  sd?: null | number
  status?: string
  title?: null | string
  w_norm?: null | number
  weight?: null | number
}

export interface ForecastFactorHistoryPoint {
  as_of?: string
  band_high?: null | number
  band_low?: null | number
  created_at?: string
  headline_probability?: null | number
  volatility?: null | number
}

export interface ForecastHooksPreviewRequest {
  max_scan: null | number
  rule: null | Record<string, unknown>
}

export interface ForecastHooksPreviewResponse {
  applies?: number
  capped_at?: number
  failing?: string[]
  issues?: Record<string, unknown>[]
  valid?: boolean
  would_block?: number
}

export interface ForecastHooksRemoveRuleRequest {
  id: null | string
}

export interface ForecastHooksRemoveRuleResponse {
  ok?: boolean
}

export interface ForecastHooksRequest {
  question_id: null | string
}

export interface ForecastHooksResponse {
  enabled?: boolean
  glossary?: Record<string, unknown>[]
  operators?: string[]
  overrides?: Record<string, unknown>
  profile?: string
  profiles?: string[]
  reasoning_methods?: Record<string, unknown>[]
  resolved?: Record<string, unknown>
  rules?: Record<string, unknown>[]
  user_rules?: Record<string, unknown>[]
}

export interface ForecastHooksSaveRuleRequest {
  edit_id: null | string
  rule: null | Record<string, unknown>
}

export interface ForecastHooksSaveRuleResponse {
  error?: string
  issues?: Record<string, unknown>[]
  ok?: boolean
}

export interface ForecastHooksSetRequest {
  rule_id: null | string
  target: null | string
  value: null | unknown
}

export interface ForecastHooksSetResponse {
  enabled?: boolean
  profile?: string
}

export interface ForecastLearningEffectiveness {
  counts?: Record<string, number>
  interpretation?: string
  status?: string
}

export interface ForecastLifecycleSummary {
  counts?: Record<string, number>
}

export interface ForecastLivePerformanceAgent {
  mean_brier?: null | number
  mean_log_score?: null | number
}

export interface ForecastMarketSeed {
  captured_at: string
  close_time: null | string
  event_id: null | string
  kind: 'prediction_market' | 'series'
  market_price: null | number
  observed_at: null | string
  observed_value: null | number
  outcome_id: null | string
  outcome_label: null | string
  period_end: null | string
  period_start: null | string
  provider: string
  published_at: null | string
  retrieved_at: null | string
  revision_policy: null | string
  source_url: null | string
  symbol: string
  title: string
  units: null | string
}

export interface ForecastNextAction {
  action?: string
  question_id?: string
  reason?: string
  score?: number
  title?: null | string
}

export interface ForecastOnboardCommitRequest {
  spec: null | Record<string, unknown>
}

export interface ForecastOnboardCommitResponse {
  committed?: boolean
  issues?: Record<string, unknown>[]
  question_id?: string
}

export interface ForecastOnboardProposeRequest {
  prompt: null | string
  spec: null | Record<string, unknown>
}

export interface ForecastOnboardProposeResponse {
  committable?: boolean
  errors?: Record<string, unknown>[]
  issues?: Record<string, unknown>[]
  readiness_gaps?: Record<string, unknown>[]
  recommended_clarifications?: Record<string, unknown>[]
  spec?: Record<string, unknown>
}

export interface ForecastOperationRequest {
  arg: null | string
  argv: null | string[]
  operation: string
}

export interface ForecastOperationResponse {
  code: number
  data: null | Record<string, unknown>
  output: string
}

export interface ForecastOutcomeSpace {
  choices?: unknown[]
  type?: string
}

export interface ForecastPooledDiagnostic {
  label?: string
  mean_brier?: null | number
  n?: number
}

export interface ForecastQuarantineSummary {
  n?: number
  reasons?: Record<string, unknown>
}

export interface ForecastQuestionChoice {
  domain: null | string
  id: string
  title: string
}

export interface ForecastQuestionChoicesResponse {
  questions: ForecastQuestionChoice[]
}

export interface ForecastQuestionPacket {
  analyst_note?: null | ForecastAnalystNote
  analyst_notes?: ForecastAnalystNote[]
  applicability_facts?: Record<string, unknown>
  assumptions?: ForecastQuestionPacketAssumption[]
  baseline_comparisons?: Record<string, unknown>[]
  calibration_lessons?: ForecastDashboardLesson[]
  corrections?: Record<string, unknown>[]
  domain_error_profiles?: ForecastDashboardErrorProfile[]
  evidence?: ForecastQuestionPacketEvidence[]
  forecast_history?: ForecastQuestionPacketSnapshot[]
  informed_by?: string[]
  model_runs?: Record<string, unknown>[]
  panel_runs?: ForecastQuestionPacketPanelRun[]
  postmortems?: Record<string, unknown>[]
  question?: ForecastQuestionPacketQuestion
  reference_classes?: ForecastQuestionPacketReferenceClass[]
  related_forecasts?: ForecastRelatedView[]
  related_shared_sources?: ForecastSharedSource[]
  resolution?: null | Record<string, unknown>
  retrospective?: null | ForecastAnalystNote
  scores?: Record<string, unknown>[]
  settlement_review?: null | Record<string, unknown>
  watched_sources?: Record<string, unknown>[]
}

export interface ForecastQuestionPacketAssumption {
  id?: string
  status?: string
  text?: string
}

export interface ForecastQuestionPacketEvidence {
  available_at?: string
  claim?: string
  claim_type?: string
  id?: string
  published_at?: null | string
  relevance_rating?: null | number
  reliability_rating?: null | number
  source_name?: null | string
  source_type?: string
  source_url?: null | string
  stance?: string
  summary?: string
}

export interface ForecastQuestionPacketPanelRun {
  aggregate_probability?: null | number
  aggregation_method?: string
  created_at?: string
  estimates?: ForecastWorkspacePanelEstimate[]
  id?: string
  spread_summary?: Record<string, number>
  trim?: number
}

export interface ForecastQuestionPacketQuestion {
  close_time?: null | string
  created_at?: string
  description?: string
  domain?: null | string
  id?: string
  impact?: null | string
  next_review_at?: null | string
  outcome_space?: ForecastOutcomeSpace
  resolution_criteria?: string
  resolution_source?: null | string
  resolution_time?: null | string
  review_cadence?: null | string
  status?: string
  tags?: string[]
  title?: string
  topics?: string[]
}

export interface ForecastQuestionPacketReferenceClass {
  base_rate?: null | number
  id?: string
  name?: string
  status?: string
}

export interface ForecastQuestionPacketResponse {
  packet?: ForecastQuestionPacket
  related?: null | ForecastRelated
  relevant_lessons?: ForecastDashboardLesson[]
}

export interface ForecastQuestionPacketSnapshot {
  as_of?: string
  change_my_mind?: string[]
  confidence?: null | number
  ensemble_components?: null | Record<string, unknown>
  evidence_refs?: string[]
  forecast_id?: string
  forecast_origin?: string
  metadata?: null | ForecastSnapshotMetadata
  method?: null | string
  probability_or_distribution?: null | Record<string, unknown> | number | string
  rationale?: string
  reasons_down?: string[]
  reasons_up?: string[]
}

export interface ForecastQuestionReadinessRequest {
  question_id: null | string
}

export interface ForecastQuestionReadinessResponse {
  gaps: ForecastReadinessGap[]
  question_id?: string
  score: number
  src_count?: number
  title?: string
}

export interface ForecastQuestionRequest {
  id: null | string
}

export interface ForecastQuorumProgressStep {
  at?: string
  detail?: string
  stage?: string
}

export interface ForecastQuorumRunRef {
  created_at?: null | string
  run_id?: string
  status?: string
}

export interface ForecastQuorumStatusRequest {
  run_id: null | string
}

export interface ForecastQuorumStatusResponse {
  degraded?: boolean
  error?: null | string
  panel_run_id?: null | string
  progress?: ForecastQuorumProgressStep[]
  question_id?: null | string
  result?: ForecastQuorumStatusResult
  run_id?: string
  status?: string
}

export interface ForecastQuorumStatusResult {
  aggregate_probability?: null | number
  committed_probability?: null | number
  degraded?: boolean
  disagreement?: null | number
}

export interface ForecastReadiness {
  gaps: ForecastReadinessGap[]
  score: number
}

export interface ForecastReadinessGap {
  fix_hint: string
  key: string
  label: string
}

export interface ForecastReforecastActiveJob {
  created_at?: null | string
  done_count?: number
  mode?: string
  question_ids?: string[]
  run_id?: string
  status?: string
  total?: number
}

export interface ForecastReforecastActiveRequest {
  limit: null | number
}

export interface ForecastReforecastActiveResponse {
  error?: string
  jobs?: ForecastReforecastActiveJob[]
}

export interface ForecastReforecastCurrent {
  question_id?: string
  stage?: string
  title?: string
}

export interface ForecastReforecastMarkResponse {
  next_run_at?: string
  queued?: boolean
  scheduled?: string
}

export interface ForecastReforecastRequest {
  id: null | string
}

export interface ForecastReforecastResultRow {
  committed?: boolean
  error?: null | string
  forecast_id?: null | string
  question_id: string
  quorum_autorun?: null | Record<string, unknown>
  saturation?: null | number
  title?: string
}

export interface ForecastReforecastStartRequest {
  max_iterations: null | number
  model: null | string
  provider: null | string
  question_ids: null | string[]
  session_id: null | string
}

export interface ForecastReforecastStartResponse {
  note?: string
  run_id: string
  total: number
}

export interface ForecastReforecastStatusRequest {
  run_id: null | string
}

export interface ForecastReforecastStatusResponse {
  current?: null | ForecastReforecastCurrent
  done_count?: number
  error?: null | string
  progress?: string[]
  quorums_started?: number
  results?: ForecastReforecastResultRow[]
  run_id?: string
  status: string
  task_summary?: string
  total?: number
}

export interface ForecastRelated {
  forecasts?: ForecastRelatedView[]
  informed_by?: string[]
  shared_sources?: ForecastSharedSource[]
}

export interface ForecastRelatedView {
  as_of?: null | string
  be_aware?: null | string
  headline_kind?: string
  headline_probability?: null | number
  id?: string
  link_label?: null | string
  link_type?: string
  note_headline?: null | string
  probability_display?: string
  reasons_down?: string[]
  reasons_up?: string[]
  relationship?: string
  stance?: null | string
  title?: string
  verdict?: null | string
}

export interface ForecastResolveRequest {
  auto_score: boolean
  confidence: null | number
  confirmed_by: null | string
  correction_ref: null | string
  criteria_satisfied: boolean
  outcome: unknown
  question_id: string
  resolution_source: null | string
  resolution_source_snapshot_ref: null | string
  resolution_status: string
  resolver_notes: null | string
  resolver_type: string
  scoreable: boolean
  trusted_policy_id: null | string
}

export interface ForecastResolveResponse {
  resolution: Record<string, unknown>
  retrospective: null | Record<string, unknown>
  score: null | Record<string, unknown>
}

export interface ForecastReviewRequest {
  confidence_above: null | number
  confidence_below: null | number
  domain: null | string
  horizon: null | string
  large_delta_threshold: null | number
  last_days: number
  now: null | string
  stale: boolean
  topic: null | string
}

export interface ForecastReviewResponse {
  rows: ForecastReviewRow[]
}

export interface ForecastReviewRow {
  current_snapshot: null | Record<string, unknown>
  priority: number
  question: Record<string, unknown>
  reasons: string[]
}

export interface ForecastReviewsNextRequest {
}

export interface ForecastReviewsNextResponse {
  due_count?: number
  next_due_at?: null | string
  nightly?: ForecastReviewsNightly
  sweeper?: ForecastReviewsSweeper
}

export interface ForecastReviewsNightly {
  installed?: boolean
  last_run_at?: null | string
  next_run_at?: null | string
}

export interface ForecastReviewsSweeper {
  enabled?: boolean
  interval_minutes?: number
  next_tick_at?: null | string
  running?: boolean
}

export interface ForecastScheduleCronHealth {
  errored?: string[]
  healthy?: boolean
  installed?: number
  jobs?: ForecastScheduleCronJob[]
  missed?: string[]
}

export interface ForecastScheduleCronJob {
  enabled?: boolean
  errored?: boolean
  id?: null | string
  last_error?: null | string
  last_run_at?: null | string
  last_status?: null | string
  missed?: boolean
  name?: null | string
  next_run_at?: null | string
  schedule?: null | string
  script?: null | string
}

export interface ForecastScheduleReviewRow {
  cadence?: null | string
  id?: string
  last_run_at?: null | string
  next_run_at?: null | string
  scope_ref?: null | string
  scope_type?: null | string
  trigger_reason?: null | string
}

export interface ForecastScheduleStatusRequest {
  limit: null | number
}

export interface ForecastScheduleStatusResponse {
  cron?: ForecastScheduleCronHealth
  healthy?: boolean
  scheduled_review_count?: number
  scheduled_reviews?: ForecastScheduleReviewRow[]
}

export interface ForecastSharedSource {
  kind?: string
  shared_with?: string[]
  source?: string
}

export interface ForecastSnapshotMetadata {
  tail_audit?: null | ForecastTailAudit
}

export interface ForecastTailAudit {
  issues?: string[]
  null_model?: null | ForecastTailNullModel
  outcomes?: ForecastTailOutcome[]
  passes?: boolean
  residual_cap?: number
  threshold?: number
  total_mass?: number
  unearned_mass?: number
}

export interface ForecastTailNullModel {
  agent_tail?: number
  excess_tail?: number
  floor?: number
  null_distribution?: Record<string, number>
  null_tail?: number
  ratio?: number
  within_tolerance?: boolean
}

export interface ForecastTailOutcome {
  classification?: null | string
  evidence_strength?: string
  has_path?: boolean
  name?: string
  note?: string
  path?: string
  probability?: number
  unearned?: boolean
}

export interface ForecastThesesRequest {
}

export interface ForecastThesesResponse {
  factors?: ForecastFactor[]
  theses?: ForecastThesis[]
}

export interface ForecastThesis {
  aggregate_stale?: boolean
  analyst_note?: null | ForecastAnalystNote
  as_of?: null | string
  components?: ForecastThesisComponent[]
  coverage?: null | number
  delta?: null | number
  domain?: null | string
  entities?: ForecastThesisEntity[]
  event_band?: null | ForecastThesisEventBand
  event_probability?: null | number
  freshness?: string
  headline_display?: string
  headline_probability?: null | number
  health_display?: string
  health_probability?: null | number
  history?: ForecastThesisHistoryPoint[]
  id?: string
  member_count?: number
  n_eff?: null | number
  question_ids?: string[]
  rationale?: null | string
  rho?: null | number
  score_band?: null | ForecastThesisScoreBand
  snapshot_count?: number
  spread?: null | Record<string, unknown>
  status?: string
  thesis_score?: null | number
  title?: string
  top_sensitivities?: ForecastThesisSensitivity[]
  topics?: string[]
  triggers?: ForecastThesisTrigger[]
}

export interface ForecastThesisBadge {
  direction?: string
  role?: null | string
  thesis_id: string
  thesis_title?: string
  weight?: null | number
}

export interface ForecastThesisComponent {
  as_of?: null | string
  contribution_pts?: null | number
  direction?: string
  flags?: string[]
  id?: string
  latest_belief_display?: string
  latest_headline?: null | number
  marginal_health_delta?: null | number
  outcome_type?: null | string
  role?: null | string
  s_i?: null | number
  s_raw?: null | number
  sigma?: null | number
  status?: string
  title?: null | string
  w_norm?: null | number
  weight?: null | number
}

export interface ForecastThesisEntity {
  action?: string
  band?: null | number[]
  contributions?: ForecastThesisComponent[]
  coverage?: null | number
  delta?: null | number
  kind?: string
  label?: string
  n_eff?: null | number
  name?: string
  score?: null | number
  stance?: string
  suitability?: null | number
  suitability_display?: string
  top_driver?: null | string
  top_driver_id?: null | string
  trend?: string
  weight_count?: number
}

export interface ForecastThesisEventBand {
  p10?: null | number
  p50?: null | number
  p90?: null | number
}

export interface ForecastThesisHistoryPoint {
  as_of?: string
  created_at?: string
  event_high?: null | number
  event_low?: null | number
  headline_probability?: null | number
  headline_regime?: string
  score_high?: null | number
  score_low?: null | number
  thesis_score?: null | number
}

export interface ForecastThesisScoreBand {
  q05?: null | number
  q50?: null | number
  q95?: null | number
}

export interface ForecastThesisSensitivity {
  delta_p_event?: null | number
  direction?: string
  member_id?: string
  p?: null | number
  p_event_at_minus?: null | number
  p_event_at_plus?: null | number
  sensitivity?: null | number
  title?: null | string
}

export interface ForecastThesisTrigger {
  better?: string[]
  delta?: null | number
  direction?: string
  less?: string[]
  member_id?: string
  note?: string
  signal?: string
}

export interface ForecastTriageContestedRequest {
  limit: null | number
  question: null | string
  question_id: null | string
}

export interface ForecastTriageContestedResponse {
  contested?: ForecastTriageContestedRow[]
  count?: number
}

export interface ForecastTriageContestedRow {
  alert_id?: null | string
  auto_label?: null | string
  candidate_ref?: null | string
  created_at?: null | string
  id?: string
  materiality?: null | string
  question_id?: null | string
  rationale?: string
  relevance?: null | number
  source?: null | string
  summary?: string
  title?: string
  url?: null | string
}

export interface ForecastTriageRelabelRequest {
  adjudications: null | Record<string, unknown>[]
  label: null | string
  label_id: null | string
}

export interface ForecastTriageRelabelResponse {
  count?: number
  relabeled?: Record<string, unknown>[]
  success?: boolean
}

export interface ForecastVoi {
  action?: string
  components?: ForecastVoiComponents
  rank?: number
  reason?: string
  score?: number
}

export interface ForecastVoiAlerts {
  count?: number
  norm?: number
  weighted?: number
}

export interface ForecastVoiComponents {
  alerts?: ForecastVoiAlerts
  amplifier?: number
  base?: number
  proximity?: ForecastVoiProximity
  readiness?: ForecastVoiReadiness
  sensitivity?: ForecastVoiSensitivity
  staleness?: ForecastVoiStaleness
}

export interface ForecastVoiProximity {
  days_until?: null | number
  horizon_days?: number
  norm?: number
  resolve_days?: null | number
  weighted?: number
}

export interface ForecastVoiReadiness {
  dampen?: number
  has_sources?: boolean
  src_count?: number
}

export interface ForecastVoiSensitivity {
  abs_pp?: number
  delta_p_event?: null | number
  thesis_id?: null | string
  thesis_title?: null | string
}

export interface ForecastVoiStaleness {
  age_days?: null | number
  cadence_days?: number
  norm?: number
  ratio?: number
  weighted?: number
}

export interface ForecastWarningDismissedItem {
  alert_id?: string
  dismiss_actor?: string
  dismiss_note?: string
  dismiss_reason?: string
  dismiss_ttl_days?: number
  dismissed_at?: string
  reason?: string
  scope_ref?: string
}

export interface ForecastWarningGroup {
  auto_resolvable?: boolean
  count?: number
  kind?: string
  reason?: string
  recommended_action?: string
  scope_refs?: string[]
  severity?: string
}

export interface ForecastWarningResolveResult {
  acknowledged?: boolean
  alert_id?: string
  detail?: string
  kind?: string
  reason?: string
  scope_ref?: string
  status?: string
}

export interface ForecastWarningsAgentTier {
  reasons?: ForecastWarningGroup[]
  stale?: ForecastWarningsTier
  total?: number
}

export interface ForecastWarningsAggregateRequest {
  reason: null | string
  scope: null | string
}

export interface ForecastWarningsAggregateResponse {
  agent?: ForecastWarningsAgentTier
  free?: ForecastWarningsTier
  headline?: ForecastWarningsHeadline
  manual?: ForecastWarningsTier
}

export interface ForecastWarningsAutomodeRunRequest {
  dry_run: null | boolean
  limit: null | number
  reason: null | string
  scope: null | string
  session_id: null | string
}

export interface ForecastWarningsAutomodeRunResponse {
  dry_run?: boolean
  job_id?: string
}

export interface ForecastWarningsDismissRequest {
  actor: null | string
  alert_id: null | string
  alert_ids: null | string[]
  kind: null | unknown
  kinds: null | unknown
  note: null | string
  now: null | string
  reason: null | string | string[]
  scope: null | string
  ttl_days: null | number
}

export interface ForecastWarningsDismissResponse {
  count?: number
  dismissed?: ForecastWarningDismissedItem[]
  matched?: number
}

export interface ForecastWarningsHeadline {
  agent?: number
  free?: number
  manual?: number
  total?: number
}

export interface ForecastWarningsListRequest {
  limit: null | number
  reason: null | string
  scope: null | string
}

export interface ForecastWarningsListResponse {
  group_count?: number
  groups?: ForecastWarningGroup[]
  open_total?: number
}

export interface ForecastWarningsResolveRequest {
  alert_id: null | string
  now: null | string
}

export interface ForecastWarningsResolveResponse {
  count?: number
  results?: ForecastWarningResolveResult[]
}

export interface ForecastWarningsTier {
  reasons?: ForecastWarningGroup[]
  total?: number
}

export interface ForecastWorkspaceDistribution {
  ci50?: null | number[]
  ci90?: null | number[]
  mean?: null | number
  median?: null | number
  pmf?: null | ForecastWorkspacePmfPoint[]
  sd?: null | number
}

export interface ForecastWorkspaceEvidence {
  available_at?: string
  claim?: string
  claim_type?: string
  id?: string
  published_at?: null | string
  relevance_rating?: null | number
  reliability_rating?: null | number
  source?: string
  source_type?: string
  stance?: string
  summary?: string
}

export interface ForecastWorkspaceHistoryPoint {
  as_of?: string
  band_high?: null | number
  band_low?: null | number
  confidence?: null | number
  created_at?: string
  forecast_id?: string
  forecast_origin?: string
  headline_probability?: null | number
  method?: null | string
  probability?: null | Record<string, unknown> | number | string
  rationale?: string
  reasons_down_count?: number
  reasons_up_count?: number
}

export interface ForecastWorkspaceItem {
  action_threshold?: null | string
  analyst_note?: null | ForecastAnalystNote
  analyst_notes?: ForecastAnalystNote[]
  as_of?: null | string
  candidate_intervals?: null | Record<string, ForecastCandidateInterval>
  change_my_mind?: string[]
  close_time?: null | string
  closing_soon?: boolean
  confidence?: null | number
  decision_deadline?: null | string
  decision_owner?: null | string
  decision_readiness_issues?: string[]
  delta?: null | number
  distribution?: null | ForecastWorkspaceDistribution
  domain?: null | string
  evidence?: ForecastWorkspaceEvidence[]
  evidence_count?: number
  freshness?: string
  headline_kind?: string
  headline_probability?: null | number
  history?: ForecastWorkspaceHistoryPoint[]
  id?: string
  impact?: null | string
  lessons_count?: number
  method?: null | string
  next_review_at?: null | string
  open_alert_count?: number
  outcome_choices?: unknown[]
  outcome_type?: string
  panel?: null | ForecastWorkspacePanel
  probability?: null | Record<string, unknown> | number | string
  probability_display?: string
  quorum_run?: null | ForecastQuorumRunRef
  rationale?: null | string
  readiness?: null | ForecastReadiness
  reasons_down?: string[]
  reasons_up?: string[]
  related?: null | ForecastRelated
  relevant_lessons?: ForecastDashboardLesson[]
  resolution?: null | ForecastWorkspaceResolution
  resolution_criteria?: string
  resolution_time?: null | string
  retrospective?: null | ForecastAnalystNote
  review_cadence?: null | string
  saturation_below_threshold?: boolean
  saturation_score?: null | number
  scores?: null | ForecastWorkspaceScores
  snapshot_count?: number
  src_count?: number
  status?: string
  tail_audit?: null | ForecastTailAudit
  thesis_ids?: ForecastThesisBadge[]
  title?: string
  topics?: string[]
  units?: null | string
  update_triggers?: ForecastWorkspaceTrigger[]
  voi?: null | ForecastVoi
}

export interface ForecastWorkspacePanel {
  aggregate_probability?: null | number
  aggregation_method?: string
  created_at?: string
  estimates?: ForecastWorkspacePanelEstimate[]
  id?: string
  kind?: string
  spread?: Record<string, number>
  trim?: number
}

export interface ForecastWorkspacePanelEstimate {
  belief?: null | string
  confidence_high?: null | number
  confidence_low?: null | number
  crux?: null | string
  perspective?: string
  probability?: null | number
  trimmed?: boolean
  weight?: null | number
}

export interface ForecastWorkspacePmfPoint {
  label: string
  probability: number
}

export interface ForecastWorkspaceRequest {
  limit: null | number
}

export interface ForecastWorkspaceResolution {
  outcome?: unknown
  resolution_status?: string
  resolved_at?: string
  scoreable?: boolean
}

export interface ForecastWorkspaceResponse {
  active_count?: number
  bench_count?: number
  closing_soon_count?: number
  factor_count?: number
  factors?: ForecastFactor[]
  forecasts?: ForecastWorkspaceItem[]
  generated_at?: string
  next_actions?: ForecastNextAction[]
  open_alert_count?: number
  operations?: Record<string, unknown>
  output?: string
  product?: string
  theses?: ForecastThesis[]
  thesis_count?: number
}

export interface ForecastWorkspaceScores {
  count?: number
  last_bucket?: null | string
  last_scored_at?: null | string
  mean_brier?: null | number
  mean_log_score?: null | number
}

export interface ForecastWorkspaceTrigger {
  action?: string
  mechanism?: string
  notes?: string
  source_ref?: string
  threshold?: string
  window?: string
}

export interface GatewayCompletionItem {
  display: string
  meta?: string
  text: string
}

export interface GatewayProtocolErrorPayload {
  preview?: string
}

export interface GatewayReadyPayload {
  build?: BuildInfoPayload
  capabilities?: string[]
  min_protocol_version?: number
  protocol_version?: number
  skin?: SkinPayload
}

export interface GatewaySkin {
  appearance?: string
  banner_hero?: string
  banner_logo?: string
  branding?: Record<string, string>
  colors?: Record<string, string>
  help_header?: string
  tool_prefix?: string
}

export interface GatewayStartTimeoutPayload {
  cwd?: string
  python?: string
  stderr_tail?: string
}

export interface GatewayStderrPayload {
  line: string
}

export interface GatewayTranscriptMessage {
  context?: string
  name?: string
  role: 'assistant' | 'system' | 'tool' | 'user'
  text?: string
}

export interface HostNegotiateRequest {
  protocol_version: number
  required_capabilities: string[]
}

export interface HostNegotiateResponse {
  capabilities: string[]
  min_protocol_version: number
  protocol_version: number
}

export interface ImageAttachRequest {
  path: null | string
  session_id: null | string
}

export interface ImageAttachResponse {
  height?: number
  name?: string
  remainder?: string
  token_estimate?: number
  width?: number
}

export interface InputDetectDropRequest {
  session_id: null | string
  text: null | string
}

export interface InputDetectDropResponse {
  height?: number
  is_image?: boolean
  matched?: boolean
  name?: string
  text?: string
  token_estimate?: number
  width?: number
}

export interface InsightsRequest {
  days: number
  source: null | string
}

export interface InsightsResponse {
  days: number
  messages: number
  sessions: number
}

export interface InterviewAnswer {
  actor: 'agent' | 'user'
  custom_text: null | string
  evidence_refs: string[]
  note: string
  question_id: string
  status: 'answered' | 'skipped' | 'unknown'
  value: null | number | string | string[]
}

export interface InterviewAnswerRequest {
  custom_text: null | string
  expected_revision: number
  interview_id: string
  note: string
  question_id: string
  request_id: string
  status: 'answered' | 'skipped' | 'unknown'
  value: null | number | string | string[]
}

export interface InterviewAssumption {
  actor: 'agent' | 'user'
  evidence_refs: string[]
  id: string
  probability: null | number
  rationale: string
  statement: string
  uncertainty: 'aleatoric' | 'epistemic' | 'measurement' | 'mixed' | 'unclassified'
}

export interface InterviewAssumptionSaveRequest {
  assumption: InterviewAssumption
  expected_revision: number
  interview_id: string
  request_id: string
}

export interface InterviewBeginRequest {
  interview_id: string
  question_id: null | string
  seed: null | ForecastMarketSeed
  title: string
}

export interface InterviewChoice {
  id: string
  label: string
}

export interface InterviewCommitResponse {
  question_id: string
  revision: number
}

export interface InterviewDraft {
  answers: InterviewAnswer[]
  assumptions: InterviewAssumption[]
  baseline_forecast_id: null | string
  context_digest: null | string
  evidence_refs: string[]
  generations: InterviewGenerationRecord[]
  mode: 'create' | 'update'
  parent_interview: null | InterviewParent
  question_id: null | string
  questions: InterviewQuestion[]
  scenarios: InterviewScenario[]
  schema_version: number
  seed: null | ForecastMarketSeed
  status: 'cancelled' | 'draft' | 'needs_research' | 'needs_user' | 'ready'
  title: string
}

export interface InterviewEvaluateRequest {
  interview_id: string
  options: ScenarioEvaluationOptions
  request_id: string
  revision: number
}

export interface InterviewEvaluationStatusResponse {
  found: boolean
  job: null | JobRecordDTO
  report: null | ScenarioReport
  request_id: null | string
  stale: boolean
}

export interface InterviewGenerateRequest {
  interview_id: string
  options: InterviewGenerationOptions
  request_id: string
  revision: number
}

export interface InterviewGenerateResponse {
  job_id: string
}

export interface InterviewGenerationOptions {
  max_questions: number
  max_tokens: number
  model: null | string
  provider: null | string
  timeout_seconds: number
}

export interface InterviewGenerationRecord {
  created_at: string
  input_digest: string
  input_revision: number
  job_id: string
  max_tokens: number
  output_tokens: null | number
  prompt_digest: string
  requested_provider: null | string
  response_model: string
  summary: string
}

export interface InterviewGenerationStatusResponse {
  found: boolean
  job: null | JobRecordDTO
  request_id: null | string
}

export interface InterviewListRequest {
  question_id: null | string
}

export interface InterviewListResponse {
  interviews: InterviewRecord[]
}

export interface InterviewParent {
  digest: string
  interview_id: string
  revision: number
}

export interface InterviewPreviewRequest {
  interview_id: string
  revision: number
}

export interface InterviewPreviewResponse {
  committable: boolean
  issues: Record<string, unknown>[]
  spec: Record<string, unknown>
  unanswered: string[]
}

export interface InterviewPromoteRequest {
  job_id: string
  preview_digest: string
  repetition: number
}

export interface InterviewPromoteResponse {
  forecast_id: string
  question_id: string
}

export interface InterviewPromotionPreviewRequest {
  job_id: string
  repetition: number
}

export interface InterviewPromotionPreviewResponse {
  blockers: string[]
  candidate: Record<string, number> | number
  job_id: string
  preview_digest: string
  promoted_forecast_id: null | string
  question_id: string
  repetition: number
  would_commit: boolean
}

export interface InterviewQuestion {
  allow_custom: boolean
  assumption_ids: string[]
  choices: InterviewChoice[]
  id: string
  kind: 'multiple' | 'number' | 'probability' | 'single' | 'text'
  prompt: string
  rationale: string
  required: boolean
  section: 'beliefs' | 'challenge' | 'define' | 'drivers' | 'outside_view' | 'resolve' | 'review' | 'scenarios' | 'uncertainty' | 'update_plan'
}

export interface InterviewReadRequest {
  interview_id: string
  revision: null | number
}

export interface InterviewRecord {
  actor: 'agent' | 'user'
  created_at: string
  digest: string
  document: InterviewDraft
  interview_id: string
  request_id: string
  revision: number
}

export interface InterviewScenario {
  actor: 'agent' | 'user'
  conditions: Record<string, boolean>
  excluded_assumption_ids: string[]
  id: string
  kind: 'ablation' | 'conditional'
  name: string
}

export interface InterviewScenarioDeleteRequest {
  expected_revision: number
  interview_id: string
  request_id: string
  scenario_id: string
}

export interface InterviewScenarioSaveRequest {
  expected_revision: number
  interview_id: string
  request_id: string
  scenario: InterviewScenario
}

export interface InterviewTargetRequest {
  interview_id: string
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
  policy_decisions: Record<string, unknown>[]
  policy_grants: string[]
  progress: Record<string, unknown>[]
  resolved_policy: null | Record<string, unknown>
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

export interface LessonShareBody {
  compiled_rule_preview: null | string
  confidence: null | number
  effect_size: null | number
  lesson: string
  lesson_id: null | string
  origin_n: null | number
  scope_ref: null | string
  scope_type: string
  status: null | string
}

export interface MarketCatalogRequest {
}

export interface MarketCatalogResponse {
  catalog: DataCatalog
  catalog_revision: string
  configured_providers: string[]
  selection: DeskSelection
}

export interface MarketDiscoverRequest {
  category?: string
  country?: string
  kind?: string
  provider?: string
  query: string
  region?: string
}

export interface MarketDiscoverResponse {
  results: MarketDiscoveryHit[]
  statuses: MarketProviderStatus[]
}

export interface MarketDiscoveryHit {
  catalog_id: null | string
  category: string
  country: null | string
  description: string
  frequency: string
  id: string
  kind: string
  name: string
  provider: string
  region: string
  source_url: string
  symbol: string
  unit: string
}

export interface MarketEventsEditRequest {
  add: DeskSavedEvent[]
  remove: DeskSavedEvent[]
}

export interface MarketEventsRequest {
  series_id: string
}

export interface MarketEventsResponse {
  data: null | DataEvents
  status: MarketProviderStatus
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

export interface MarketProviderConnectRequest {
  provider: string
  session_id: string
}

export interface MarketProviderConnectResponse {
  stored: boolean
}

export interface MarketProviderStatus {
  message: null | string
  provider: string
  retry_after: null | number
  status: string
}

export interface MarketQuotesRequest {
  series: MarketSeriesRef[]
}

export interface MarketQuotesResponse {
  quotes: Quote[]
  statuses: MarketProviderStatus[]
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

export interface MarketSelectionApplyRequest {
  edit: DeskEdit
  expected_revision: string
}

export interface MarketSelectionApplyResponse {
  selection: DeskSelection
}

export interface MarketSelectionPreviewRequest {
  edit: DeskEdit
}

export interface MarketSelectionPreviewResponse {
  preview: DeskPreview
}

export interface MarketSelectionUpdateRequest {
  expected_revision: string
  patch: DeskPatch
}

export interface MarketSeriesRef {
  catalog_id?: string
  category?: string
  line?: string
  name?: string
  provider: string
  symbol: string
  unit?: string
}

export interface McpServerStatus {
  connected: boolean
  name: string
  tools: number
  transport: string
}

export interface MessageCompletePayload {
  durable_status?: string
  reasoning?: string
  rendered?: string
  status: string
  text: string
  turn_id?: string
  usage: Record<string, unknown>
  warning?: string
}

export interface MessageDeltaPayload {
  durable_status?: string
  rendered?: string
  text?: string
  turn_id?: string
}

export interface MessageStartPayload {
  durable_status?: string
  turn_id?: string
}

export interface ModelBuildResponse {
  model_id: string
  presentation?: null | Record<string, unknown>
  renarrated?: boolean
  status: string
  version?: null | number
}

export interface ModelChatRequest {
  id: string
  message: string
  params: null | ModelParameters
  session_id: null | string
}

export interface ModelCreateRequest {
  params: null | ModelParameters
  question: string
  session_id: null | string
}

export interface ModelDeleteResponse {
  deleted: boolean
}

export interface ModelDisconnectRequest {
  slug: string
}

export interface ModelDisconnectResponse {
  disconnected: boolean
  name: string
  slug: string
}

export interface ModelExportResponse {
  bytes: number
  path: string
}

export interface ModelForecastResponse {
  model_id: string
  model_run_id: null | string
  question_id: null | string
  reference_class_id: null | string
  seed: null | Record<string, unknown>
}

export interface ModelGetRequest {
  id: string
  session_id: null | string
  version: null | number
}

export interface ModelGetResponse {
  packet: Record<string, unknown>
}

export interface ModelIdentityRequest {
  id: string
}

export interface ModelListRequest {
  limit: number
  status: null | string
}

export interface ModelListResponse {
  models: Record<string, unknown>[]
}

export interface ModelOptionProvider {
  auth_type?: string
  authenticated?: boolean
  is_current?: boolean
  key_env?: string
  models?: string[]
  name: string
  reasoning_effort_models?: string[]
  reasoning_efforts?: string[]
  slug: string
  supports_reasoning_effort?: boolean
  total_models?: number
  warning?: string
}

export interface ModelOptionsRequest {
  session_id: null | string
}

export interface ModelOptionsResponse {
  model?: string
  provider?: string
  providers?: ModelOptionProvider[]
  reasoning_effort?: string
}

export interface ModelParameters {
  analysis_type: string
  assumptions: string
  depth: string
  horizon: string
  question: string
  tags?: string[]
  tickers: string[]
  title?: string
}

export interface ModelSaveKeyRequest {
  api_key: string
  session_id: null | string
  slug: string
}

export interface ModelSessionRequest {
  id: string
  session_id: null | string
}

export interface NewsArticle {
  source: string
  summary: string
  title: string
}

export interface NewsArticleResponse {
  message: string
  status: 'article' | 'excerpt' | 'unavailable'
  text: string
  url: string
}

export interface NewsConfigureRequest {
  action: 'add' | 'empty' | 'remove' | 'starter'
  feed: null | NewsSubscription
}

export interface NewsDeskRequest {
}

export interface NewsDeskResponse {
  feeds: NewsSubscription[]
  starter: NewsSubscription[]
  state: 'configured' | 'unconfigured'
}

export interface NewsFeedRequest {
  url: string
}

export interface NewsFeedResponse {
  url: string
  xml: string
}

export interface NewsSearchRequest {
  articles: NewsArticle[]
  limit: number
  query: string
}

export interface NewsSearchResponse {
  engine: string
  results: Record<string, unknown>[]
}

export interface NewsSubscription {
  addedAt: number
  category: string
  custom: boolean
  title: string
  url: string
}

export interface ObservationComparison {
  basis: 'last_transition' | 'previous_observation'
  current_period: string
  current_value: number
  previous_period: string
  previous_value: number
}

export interface ObsidianAppendRequest {
  rel_path: string
  text: string
}

export interface ObsidianCreateRequest {
  content: string
  rel_path: string
  title: string
}

export interface ObsidianNote {
  excerpt?: string
  folder?: string
  links?: string[]
  modified?: string
  rel_path?: string
  size?: number
  title?: string
}

export interface ObsidianNoteRequest {
  rel_path: null | string
}

export interface ObsidianNoteResponse {
  content?: string
  rel_path?: string
  size?: number
  truncated?: boolean
}

export interface ObsidianSearchRequest {
  limit: number
  query: null | string
}

export interface ObsidianSearchResponse {
  count?: number
  query?: string
  results?: ObsidianSearchResult[]
}

export interface ObsidianSearchResult {
  line?: number
  matched_terms?: number
  rel_path?: string
  score?: number
  snippet?: string
  title?: string
}

export interface ObsidianSetupResponse {
  created: string[]
  ok: boolean
  skipped: string[]
  vault: string
}

export interface ObsidianStatusRequest {
  limit: number
}

export interface ObsidianStatusResponse {
  count?: number
  exists?: boolean
  notes?: ObsidianNote[]
  vault?: null | string
}

export interface ObsidianWriteRequest {
  content: string
  expected_content: null | string
  rel_path: string
}

export interface ObsidianWriteResponse {
  ok: boolean
  rel_path: string
  size?: number
}

export interface OneShotRequest {
  input: string
  instructions: string
  max_tokens: number
  session_id: null | string
  task: string
  temperature: null | number
  template: null | string
  variables: null | Record<string, unknown>
}

export interface OperationSessionRequest {
  session_id: null | string
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

export interface PasteCollapseRequest {
  text: string
}

export interface PasteCollapseResponse {
  lines: number
  path: string
  placeholder: string
}

export interface PluginItem {
  enabled: boolean
  name: string
  version: string
}

export interface PluginsResponse {
  plugins: PluginItem[]
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

export interface ProcessStopRequest {
  session_id?: string
}

export interface ProcessStopResponse {
  killed?: number
}

export interface PromptBackgroundRequest {
  session_id: null | string
  text: null | string
}

export interface PromptSubmitRequest {
  session_id: null | string
  text: null | string
}

export interface PromptSubmitResponse {
  ok?: boolean
}

export interface Quote {
  asOf: number
  catalog_id: null | string
  category: string
  change: null | number
  changePct: null | number
  comparison: null | ObservationComparison
  currency: null | string
  dated_history: DatedValue[]
  dayHigh: null | number
  dayLow: null | number
  exchange: null | string
  history: number[]
  issue_time: null | string
  kind: string
  last_movement: null | ObservationComparison
  name: string
  prevClose: null | number
  provider: string
  published_at: null | string
  refresh_seconds: number
  retrieved_at: null | string
  revision_policy: string
  source_family: null | string
  source_url: null | string
  symbol: string
  unit: string
  valid_from: null | string
  valid_until: null | string
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

export interface ReloadEnvRequest {
}

export interface ReloadEnvResponse {
  updated?: number
}

export interface ReloadMcpRequest {
  always: boolean
  confirm: boolean
  session_id: null | string
}

export interface ReloadMcpResponse {
  message?: string
  status?: string
}

export interface ReviewSummaryPayload {
  text?: string
}

export interface ReviewSweepPayload {
  alerts?: number
  due_count?: number
  duration_ms?: number
  phase: string
  proposals?: number
}

export interface RollbackCheckpoint {
  hash: string
  message?: string
  timestamp?: string
}

export interface RollbackDiffRequest {
  hash: null | string
  session_id: null | string
}

export interface RollbackDiffResponse {
  diff?: string
  rendered?: string
  stat?: string
}

export interface RollbackListRequest {
  session_id: null | string
}

export interface RollbackListResponse {
  checkpoints?: RollbackCheckpoint[]
  enabled?: boolean
}

export interface RollbackRestoreRequest {
  file_path: null | string
  hash: null | string
  session_id: null | string
}

export interface RollbackRestoreResponse {
  error?: string
  history_removed?: number
  message?: string
  reason?: string
  restored_to?: string
  success?: boolean
}

export interface ScenarioCallResult {
  created_at: string
  estimate: ScenarioEstimate
  kind: 'ablation' | 'baseline' | 'conditional'
  output_tokens: null | number
  prompt_digest: string
  repetition: number
  request_receipt: ScenarioRouteReceipt
  response_model: string
  variant_id: string
}

export interface ScenarioComparison {
  dimensions: Record<string, ScenarioDimension>
  kind: 'ablation' | 'baseline' | 'conditional'
  repetitions: number
  variant_id: string
}

export interface ScenarioDimension {
  mean: number
  model_dispersion: null | number
  paired_delta: number
}

export interface ScenarioEstimate {
  categories: Record<string, number>
  evidence_refs: string[]
  outcome_type: 'binary' | 'categorical' | 'distribution' | 'numeric'
  probability: null | number
  q10: null | number
  q50: null | number
  q90: null | number
  rationale: string
  reference_class_refs: string[]
  units: null | string
  unresolved_questions: string[]
}

export interface ScenarioEvaluationOptions {
  model: InterviewGenerationOptions
  repetitions: number
  scenario_ids: string[]
}

export interface ScenarioReport {
  assumptions: InterviewAssumption[]
  comparisons: ScenarioComparison[]
  input_digest: string
  interview_id: string
  limitation: string
  matched: boolean
  results: ScenarioCallResult[]
  revision: number
  scenarios: InterviewScenario[]
}

export interface ScenarioRouteReceipt {
  fingerprint: string
  model: string
  provider: string
}

export interface SecretRequestPayload {
  env_var: string
  metadata?: Record<string, unknown>
  prompt: string
  request_id: string
}

export interface SecretRespondRequest {
  request_id: null | string
  session_id: null | string
  value: string
}

export interface SecretRespondResponse {
  ok?: boolean
}

export interface SecretResult {
  value: string
}

export interface SectionsResponse {
  sections: Record<string, unknown>[]
}

export interface SessionBranchRequest {
  name: string
  session_id: null | string
}

export interface SessionBranchResponse {
  parent?: string
  session_id?: string
  title?: string
}

export interface SessionCloseRequest {
  session_id: null | string
}

export interface SessionCloseResponse {
  ok?: boolean
}

export interface SessionCompressRequest {
  focus_topic: null | string
  session_id: null | string
}

export interface SessionCompressResponse {
  after_messages?: number
  after_tokens?: number
  before_messages?: number
  before_tokens?: number
  info?: SessionInfo
  messages?: GatewayTranscriptMessage[]
  removed?: number
  summary?: SessionCompressSummary
  usage?: Usage
}

export interface SessionCompressSummary {
  headline?: string
  noop?: boolean
  note?: null | string
  token_line?: string
}

export interface SessionCreateInfo {
  build?: BuildInfoPayload
  config_warning?: string
  credential_warning?: string
  cwd?: string
  durable_session_id?: string
  fast?: boolean
  lazy?: boolean
  mcp_servers?: McpServerStatus[]
  model: string
  profile_name?: string
  protocol_version?: number
  reasoning_effort?: string
  release_date?: string
  service_tier?: string
  skills: Record<string, string[]>
  system_prompt?: string
  tools: Record<string, string[]>
  update_behind?: null | number
  update_command?: string
  usage?: Usage
  version?: string
}

export interface SessionCreateRequest {
  cols: null | number
  server_requests: boolean
}

export interface SessionCreateResponse {
  info?: SessionCreateInfo
  session_id: string
}

export interface SessionDeleteRequest {
  session_id: string
}

export interface SessionDeleteResponse {
  deleted: string
}

export interface SessionHistoryRequest {
  session_id: null | string
}

export interface SessionHistoryResponse {
  messages?: GatewayTranscriptMessage[]
}

export interface SessionInfo {
  build?: BuildInfoPayload
  cwd?: string
  durable_session_id?: string
  fast?: boolean
  lazy?: boolean
  mcp_servers?: McpServerStatus[]
  model: string
  profile_name?: string
  protocol_version?: number
  reasoning_effort?: string
  release_date?: string
  service_tier?: string
  skills: Record<string, string[]>
  system_prompt?: string
  tools: Record<string, string[]>
  update_behind?: null | number
  update_command?: string
  usage?: Usage
  version?: string
}

export interface SessionInfoPayload {
  build?: BuildInfoPayload
  cwd: string
  durable_session_id?: string
  fast: boolean
  model: string
  profile_name: string
  protocol_version?: number
  reasoning_effort: string
  release_date: string
  service_tier: string
  skills: Record<string, unknown>
  tools: Record<string, unknown>
  update_behind: null | number
  update_command: string
  usage: Record<string, unknown>
  version: string
}

export interface SessionInterruptRequest {
  session_id: null | string
}

export interface SessionInterruptResponse {
  ok?: boolean
  status?: string
}

export interface SessionListItem {
  id: string
  message_count: number
  preview: string
  source?: string
  started_at: number
  title: string
}

export interface SessionListRequest {
  limit: number
}

export interface SessionListResponse {
  sessions?: SessionListItem[]
}

export interface SessionMostRecentRequest {
  limit: null | number
}

export interface SessionMostRecentResponse {
  session_id?: null | string
  source?: string
  started_at?: number
  title?: string
}

export interface SessionResumeRequest {
  cols: null | number
  replace_session_id: null | string
  server_requests: boolean
  session_id: string
}

export interface SessionResumeResponse {
  info?: SessionInfo
  message_count?: number
  messages: GatewayTranscriptMessage[]
  open_requests?: Record<string, unknown>[]
  recovery?: Record<string, unknown>
  resumed?: string
  session_id: string
}

export interface SessionSaveRequest {
  session_id: null | string
}

export interface SessionSaveResponse {
  file?: string
}

export interface SessionStatusRequest {
  session_id: null | string
}

export interface SessionStatusResponse {
  output?: string
}

export interface SessionSteerRequest {
  session_id: null | string
  text: null | string
}

export interface SessionSteerResponse {
  status?: 'queued' | 'rejected'
  text?: string
}

export interface SessionTitleRequest {
  session_id: null | string
  title: null | string
}

export interface SessionTitleResponse {
  pending?: boolean
  session_key?: string
  title?: string
}

export interface SessionUndoRequest {
  session_id: null | string
}

export interface SessionUndoResponse {
  removed?: number
}

export interface SessionUsageRequest {
  session_id: null | string
}

export interface SessionUsageResponse {
  cache_read?: number
  cache_write?: number
  calls?: number
  compressions?: number
  context_max?: number
  context_percent?: number
  context_used?: number
  cost_status?: 'estimated' | 'exact'
  cost_usd?: number
  input?: number
  model?: string
  output?: number
  total?: number
}

export interface SetupStatusRequest {
}

export interface SetupStatusResponse {
  provider_configured?: boolean
}

export interface SfpBand {
  high: number
  label: null | string
  low: number
}

export interface SfpEnvelope {
  body: Record<string, unknown>
  kind: string
  sender: SfpSender
  ts: string
  v: number
}

export interface SfpEvidenceRef {
  id: string
  title: null | string
}

export interface SfpFilePointer {
  bytes: number
  encoding: string
  filename: null | string
  kind: string
  sha256: string
}

export interface SfpMemberEstimate {
  agent: string
  instance_id: null | string
  probability: null | number
}

export interface SfpQuestionRef {
  criteria_hash: string
  question_id: null | string
  title: string
}

export interface SfpSender {
  agent: string
  instance_id: string
  team: null | string
}

export interface SharedFeed {
  kind: string
  name: string
  points: SharedObservation[]
  provider: string
  retrieved_at: null | string
  revision_policy: string
  source_url: null | string
  symbol: string
  unit: string
}

export interface SharedObservation {
  end: string
  start: string
  value: null | number
}

export interface SharedPeriod {
  end: string
  start: string
}

export interface ShellExecRequest {
  command: null | string
}

export interface ShellExecResponse {
  code: number
  stderr?: string
  stdout?: string
}

export interface SkillItem {
  description?: string
  name: string
  source?: string
  trust?: string
}

export interface SkillsManageRequest {
  action: 'browse' | 'inspect' | 'install' | 'list' | 'search'
  page: number
  page_size: number
  query: string
  session_id: null | string
}

export interface SkillsManageResponse {
  info?: Record<string, unknown>
  installed?: boolean
  items?: SkillItem[]
  name?: string
  page?: number
  results?: SkillItem[]
  skills?: Record<string, string[]>
  total?: number
  total_pages?: number
}

export interface SkillsReloadRequest {
}

export interface SkillsReloadResponse {
  output: string
  result: Record<string, unknown>
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

export interface SlashCategory {
  name: string
  pairs: [string, string][]
}

export interface SlashExecRequest {
  command: null | string
  session_id: null | string
}

export interface SlashExecResponse {
  output?: string
  warning?: string
}

export interface SpawnTreeListEntry {
  count: number
  finished_at?: number
  label?: string
  path: string
  session_id?: string
  started_at?: null | number
}

export interface SpawnTreeListRequest {
  cross_session: boolean
  limit: number
  session_id: null | string
}

export interface SpawnTreeListResponse {
  entries?: SpawnTreeListEntry[]
}

export interface SpawnTreeLoadRequest {
  path: null | string
}

export interface SpawnTreeLoadResponse {
  finished_at?: number
  label?: string
  session_id?: string
  started_at?: null | number
  subagents?: unknown[]
}

export interface SpawnTreeSaveRequest {
  finished_at: null | number
  label: string
  session_id: null | string
  started_at: null | number
  subagents: unknown[]
}

export interface SpawnTreeSaveResponse {
  path: string
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

export interface SubagentEventPayload {
  api_calls?: number
  cost_usd?: number
  depth?: number
  duration_seconds?: number
  files_read?: string[]
  files_written?: string[]
  goal: string
  input_tokens?: number
  iteration?: number
  model?: string
  output_tail?: SubagentOutputTailItem[]
  output_tokens?: number
  parent_id?: null | string
  reasoning_tokens?: number
  status?: 'cleanup_pending' | 'completed' | 'completion_pending' | 'error' | 'failed' | 'interrupted' | 'queued' | 'running' | 'timeout' | 'unconfirmed'
  subagent_id?: string
  summary?: string
  task_count?: number
  task_index: number
  text?: string
  tool_count?: number
  tool_name?: string
  tool_preview?: string
  toolsets?: string[]
}

export interface SubagentInterruptRequest {
  session_id?: string
  subagent_id: null | string
}

export interface SubagentInterruptResponse {
  found?: boolean
  subagent_id?: string
}

export interface SubagentOutputTailItem {
  is_error?: boolean
  preview?: string
  tool?: string
}

export interface SudoRequestPayload {
  request_id: string
}

export interface SudoRespondRequest {
  password: string
  request_id: null | string
  session_id: null | string
}

export interface SudoRespondResponse {
  ok?: boolean
}

export interface SudoResult {
  password: string
}

export interface TerminalResizeRequest {
  cols: null | number
  rows: null | number
  session_id: null | string
}

export interface TerminalResizeResponse {
  ok?: boolean
}

export interface TextResponse {
  text: string
}

export interface ThemeListRequest {
}

export interface ThemeListResponse {
  active?: string
  appearance?: string
  themes?: ThemeOption[]
}

export interface ThemeOption {
  branding?: Record<string, string>
  colors?: Record<string, string>
  description?: string
  name: string
  source?: string
}

export interface ThesisAggregateBody {
  aggregate: null | number
  aggregate_distribution: null | Record<string, unknown>
  disagreement: null | Record<string, unknown>
  member_estimates: SfpMemberEstimate[]
  method: string
  question_ref: SfpQuestionRef
  round: number
  spread: null | number
}

export interface ThesisRoundBody {
  deadline: null | string
  facilitator: null | string
  note: null | string
  participants: string[]
  question_refs: SfpQuestionRef[]
  round: number
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
  usage?: Usage
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

export interface ToolsConfigureRequest {
  action: null | string
  names: null | string[]
  session_id: null | string
}

export interface ToolsConfigureResponse {
  changed?: string[]
  enabled_toolsets?: string[]
  info?: SessionInfo
  missing_servers?: string[]
  reset?: boolean
  unknown?: string[]
}

export interface ToolsetsResponse {
  toolsets: Record<string, unknown>[]
}

export interface Usage {
  calls: number
  compressions?: number
  context_max?: number
  context_percent?: number
  context_used?: number
  cost_status?: string
  cost_usd?: number
  input: number
  output: number
  reasoning?: number
  total: number
}

export interface VoiceRecordRequest {
  action: string
  session_id: null | string
}

export interface VoiceRecordResponse {
  status?: 'busy' | 'recording' | 'stopped'
  text?: string
}

export interface VoiceStatusPayload {
  state?: string
}

export interface VoiceToggleRequest {
  action: string
  session_id: null | string
}

export interface VoiceToggleResponse {
  audio_available?: boolean
  available?: boolean
  details?: string
  enabled?: boolean
  record_key?: string
  stt_available?: boolean
  tts?: boolean
}

export interface VoiceTranscriptPayload {
  no_speech_limit?: boolean
  text?: string
}

export interface VoiceTtsRequest {
  session_id: null | string
  text: string
}

export interface VoiceTtsResponse {
  status: string
}

export interface WireModel {
}

export const SERVER_REQUEST_NAMES = ['approval', 'clarify', 'secret', 'sudo'] as const

export interface ServerRequestMethods {
  'approval': { params: Omit<ApprovalRequestPayload, 'request_id'> & { session_id: string }; result: ApprovalResult }
  'clarify': { params: Omit<ClarifyRequestPayload, 'request_id'> & { session_id: string }; result: ClarifyResult }
  'secret': { params: Omit<SecretRequestPayload, 'request_id'> & { session_id: string }; result: SecretResult }
  'sudo': { params: Omit<SudoRequestPayload, 'request_id'> & { session_id: string }; result: SudoResult }
}

export interface RpcMethods {
  'agents.active.summary': {
    params: Record<string, never>
    result: AgentsActiveSummaryResponse
  }
  'agents.list': {
    params: Record<string, never>
    result: AgentsListResponse
  }
  'approval.respond': {
    params: {
      all?: boolean
      choice?: string
      request_id?: null | string
      session_id?: null | string
    }
    result: ApprovalRespondResponse
  }
  'auth.poll': {
    params: {
      cancel?: boolean
      session_id?: null | string
    }
    result: AuthPollResponse
  }
  'auth.start': {
    params: {
      provider?: string
      session_id?: null | string
    }
    result: AuthStartResponse
  }
  'browser.manage': {
    params: {
      action?: null | string
      session_id?: null | string
      url?: null | string
    }
    result: BrowserManageResponse
  }
  'clarify.respond': {
    params: {
      answer?: string
      request_id?: null | string
      session_id?: null | string
    }
    result: ClarifyRespondResponse
  }
  'cli.exec': {
    params: {
      argv?: string[]
      timeout?: number
    }
    result: CliExecResponse
  }
  'clipboard.paste': {
    params: {
      session_id?: null | string
    }
    result: ClipboardPasteResponse
  }
  'command.dispatch': {
    params: {
      arg?: string
      name: string
      session_id?: null | string
    }
    result: CommandDispatchResponse
  }
  'command.resolve': {
    params: {
      name: string
    }
    result: CommandResolveResponse
  }
  'commands.catalog': {
    params: Record<string, never>
    result: CommandsCatalogResponse
  }
  'complete.path': {
    params: {
      text?: null | string
      word?: null | string
    }
    result: CompletionResponse
  }
  'complete.slash': {
    params: {
      text?: null | string
      word?: null | string
    }
    result: CompletionResponse
  }
  'config.get': {
    params: {
      key?: null | string
      session_id?: null | string
    }
    result: ConfigFullResponse
  }
  'config.set': {
    params: {
      key?: null | string
      session_id?: null | string
      value?: null | string
    }
    result: ConfigSetResponse
  }
  'config.show': {
    params: {
      session_id?: null | string
    }
    result: SectionsResponse
  }
  'cron.manage': {
    params: {
      action?: string
      name?: string
      prompt?: string
      schedule?: string
    }
    result: CronManageResponse
  }
  'delegation.pause': {
    params: {
      paused?: null | boolean
      session_id?: string
    }
    result: DelegationPauseResponse
  }
  'delegation.status': {
    params: {
      session_id?: string
    }
    result: DelegationStatusResponse
  }
  'events.replay': {
    params: {
      limit?: number
      session_id: string
      since_id?: number
      types?: null | string | string[]
    }
    result: EventsReplayResponse
  }
  'forecast.article.attach': {
    params: {
      article: ForecastArticleClaim
      prepare_update?: boolean
      question_id: string
    }
    result: ForecastArticleAttachResponse
  }
  'forecast.bench': {
    params: {
      limit?: null | number
    }
    result: ForecastBenchResponse
  }
  'forecast.calibration': {
    params: {
      domain?: null | string
      origin?: null | string
    }
    result: ForecastCalibrationResponse
  }
  'forecast.command': {
    params: {
      arg?: null | string
      argv?: null | string[]
    }
    result: ForecastCommandResponse
  }
  'forecast.config': {
    params: {
      id?: null | string
      question_id?: null | string
    }
    result: ForecastConfigResponse
  }
  'forecast.config.set': {
    params: {
      decision?: null | Record<string, unknown>
      hooks?: null | Record<string, unknown>
      id?: null | string
      question_id?: null | string
      review_cadence?: null | string
    }
    result: ForecastConfigResponse
  }
  'forecast.dashboard': {
    params: {
      fast?: null | boolean
      limit?: null | number
      summary_only?: null | boolean
    }
    result: ForecastDashboardResponse
  }
  'forecast.desk.task': {
    params: {
      instruction?: null | string
      max_iterations?: null | number
      model?: null | string
      provider?: null | string
      question_ids?: null | string[]
      session_id?: null | string
    }
    result: ForecastReforecastStartResponse
  }
  'forecast.hooks': {
    params: {
      question_id?: null | string
    }
    result: ForecastHooksResponse
  }
  'forecast.hooks.preview': {
    params: {
      max_scan?: null | number
      rule?: null | Record<string, unknown>
    }
    result: ForecastHooksPreviewResponse
  }
  'forecast.hooks.remove_rule': {
    params: {
      id?: null | string
    }
    result: ForecastHooksRemoveRuleResponse
  }
  'forecast.hooks.save_rule': {
    params: {
      edit_id?: null | string
      rule?: null | Record<string, unknown>
    }
    result: ForecastHooksSaveRuleResponse
  }
  'forecast.hooks.set': {
    params: {
      rule_id?: null | string
      target?: null | string
      value?: null | unknown
    }
    result: ForecastHooksSetResponse
  }
  'forecast.interview.answer': {
    params: {
      custom_text?: null | string
      expected_revision: number
      interview_id: string
      note?: string
      question_id: string
      request_id: string
      status: 'answered' | 'skipped' | 'unknown'
      value?: null | number | string | string[]
    }
    result: InterviewRecord
  }
  'forecast.interview.assumption.save': {
    params: {
      assumption: InterviewAssumption
      expected_revision: number
      interview_id: string
      request_id: string
    }
    result: InterviewRecord
  }
  'forecast.interview.begin': {
    params: {
      interview_id: string
      question_id?: null | string
      seed?: null | ForecastMarketSeed
      title?: string
    }
    result: InterviewRecord
  }
  'forecast.interview.commit': {
    params: {
      interview_id: string
      revision: number
    }
    result: InterviewCommitResponse
  }
  'forecast.interview.evaluate': {
    params: {
      interview_id: string
      options: ScenarioEvaluationOptions
      request_id: string
      revision: number
    }
    result: InterviewGenerateResponse
  }
  'forecast.interview.evaluation_status': {
    params: {
      interview_id: string
    }
    result: InterviewEvaluationStatusResponse
  }
  'forecast.interview.generate': {
    params: {
      interview_id: string
      options?: InterviewGenerationOptions
      request_id: string
      revision: number
    }
    result: InterviewGenerateResponse
  }
  'forecast.interview.generation_status': {
    params: {
      interview_id: string
    }
    result: InterviewGenerationStatusResponse
  }
  'forecast.interview.list': {
    params: {
      question_id?: null | string
    }
    result: InterviewListResponse
  }
  'forecast.interview.preview': {
    params: {
      interview_id: string
      revision: number
    }
    result: InterviewPreviewResponse
  }
  'forecast.interview.promote': {
    params: {
      job_id: string
      preview_digest: string
      repetition?: number
    }
    result: InterviewPromoteResponse
  }
  'forecast.interview.promotion_preview': {
    params: {
      job_id: string
      repetition?: number
    }
    result: InterviewPromotionPreviewResponse
  }
  'forecast.interview.read': {
    params: {
      interview_id: string
      revision?: null | number
    }
    result: InterviewRecord
  }
  'forecast.interview.scenario.delete': {
    params: {
      expected_revision: number
      interview_id: string
      request_id: string
      scenario_id: string
    }
    result: InterviewRecord
  }
  'forecast.interview.scenario.save': {
    params: {
      expected_revision: number
      interview_id: string
      request_id: string
      scenario: InterviewScenario
    }
    result: InterviewRecord
  }
  'forecast.onboard_commit': {
    params: {
      spec?: null | Record<string, unknown>
    }
    result: ForecastOnboardCommitResponse
  }
  'forecast.onboard_propose': {
    params: {
      prompt?: null | string
      spec?: null | Record<string, unknown>
    }
    result: ForecastOnboardProposeResponse
  }
  'forecast.operation': {
    params: {
      arg?: null | string
      argv?: null | string[]
      operation: string
    }
    result: ForecastOperationResponse
  }
  'forecast.question': {
    params: {
      id?: null | string
    }
    result: ForecastQuestionPacketResponse
  }
  'forecast.question.choices': {
    params: Record<string, never>
    result: ForecastQuestionChoicesResponse
  }
  'forecast.question.readiness': {
    params: {
      question_id?: null | string
    }
    result: ForecastQuestionReadinessResponse
  }
  'forecast.quorum.status': {
    params: {
      run_id?: null | string
    }
    result: ForecastQuorumStatusResponse
  }
  'forecast.reforecast': {
    params: {
      id?: null | string
    }
    result: ForecastReforecastMarkResponse
  }
  'forecast.reforecast.active': {
    params: {
      limit?: null | number
    }
    result: ForecastReforecastActiveResponse
  }
  'forecast.reforecast.start': {
    params: {
      max_iterations?: null | number
      model?: null | string
      provider?: null | string
      question_ids?: null | string[]
      session_id?: null | string
    }
    result: ForecastReforecastStartResponse
  }
  'forecast.reforecast.status': {
    params: {
      run_id?: null | string
    }
    result: ForecastReforecastStatusResponse
  }
  'forecast.resolve': {
    params: {
      auto_score?: boolean
      confidence?: null | number
      confirmed_by?: null | string
      correction_ref?: null | string
      criteria_satisfied?: boolean
      outcome: unknown
      question_id: string
      resolution_source?: null | string
      resolution_source_snapshot_ref?: null | string
      resolution_status?: string
      resolver_notes?: null | string
      resolver_type?: string
      scoreable?: boolean
      trusted_policy_id?: null | string
    }
    result: ForecastResolveResponse
  }
  'forecast.review': {
    params: {
      confidence_above?: null | number
      confidence_below?: null | number
      domain?: null | string
      horizon?: null | string
      large_delta_threshold?: null | number
      last_days?: number
      now?: null | string
      stale?: boolean
      topic?: null | string
    }
    result: ForecastReviewResponse
  }
  'forecast.reviews.next': {
    params: Record<string, never>
    result: ForecastReviewsNextResponse
  }
  'forecast.schedule.status': {
    params: {
      limit?: null | number
    }
    result: ForecastScheduleStatusResponse
  }
  'forecast.theses': {
    params: Record<string, never>
    result: ForecastThesesResponse
  }
  'forecast.triage.contested': {
    params: {
      limit?: null | number
      question?: null | string
      question_id?: null | string
    }
    result: ForecastTriageContestedResponse
  }
  'forecast.triage.relabel': {
    params: {
      adjudications?: null | Record<string, unknown>[]
      label?: null | string
      label_id?: null | string
    }
    result: ForecastTriageRelabelResponse
  }
  'forecast.warnings.aggregate': {
    params: {
      reason?: null | string
      scope?: null | string
    }
    result: ForecastWarningsAggregateResponse
  }
  'forecast.warnings.automode.cancel': {
    params: {
      job_id: string
    }
    result: AutomodeCancelResponse
  }
  'forecast.warnings.automode.run': {
    params: {
      dry_run?: null | boolean
      limit?: null | number
      reason?: null | string
      scope?: null | string
      session_id?: null | string
    }
    result: ForecastWarningsAutomodeRunResponse
  }
  'forecast.warnings.dismiss': {
    params: {
      actor?: null | string
      alert_id?: null | string
      alert_ids?: null | string[]
      kind?: null | unknown
      kinds?: null | unknown
      note?: null | string
      now?: null | string
      reason?: null | string | string[]
      scope?: null | string
      ttl_days?: null | number
    }
    result: ForecastWarningsDismissResponse
  }
  'forecast.warnings.list': {
    params: {
      limit?: null | number
      reason?: null | string
      scope?: null | string
    }
    result: ForecastWarningsListResponse
  }
  'forecast.warnings.resolve': {
    params: {
      alert_id?: null | string
      now?: null | string
    }
    result: ForecastWarningsResolveResponse
  }
  'forecast.workspace': {
    params: {
      limit?: null | number
    }
    result: ForecastWorkspaceResponse
  }
  'host.negotiate': {
    params: {
      protocol_version: number
      required_capabilities?: string[]
    }
    result: HostNegotiateResponse
  }
  'image.attach': {
    params: {
      path?: null | string
      session_id?: null | string
    }
    result: ImageAttachResponse
  }
  'input.detect_drop': {
    params: {
      session_id?: null | string
      text?: null | string
    }
    result: InputDetectDropResponse
  }
  'insights.get': {
    params: {
      days?: number
      source?: null | string
    }
    result: InsightsResponse
  }
  'jobs.active': {
    params: {
      types?: null | string[]
    }
    result: JobsActiveResponse
  }
  'jobs.cancel': {
    params: {
      job_id: string
    }
    result: JobsCancelResponse
  }
  'jobs.start': {
    params: {
      session_id?: null | string
      spec?: null | Record<string, unknown>
      type: string
    }
    result: JobsStartResponse
  }
  'jobs.status': {
    params: {
      job_id: string
    }
    result: JobsStatusResponse
  }
  'llm.oneshot': {
    params: {
      input?: string
      instructions?: string
      max_tokens?: number
      session_id?: null | string
      task?: string
      temperature?: null | number
      template?: null | string
      variables?: null | Record<string, unknown>
    }
    result: TextResponse
  }
  'market.catalog': {
    params: Record<string, never>
    result: MarketCatalogResponse
  }
  'market.discover': {
    params: {
      category?: string
      country?: string
      kind?: string
      provider?: string
      query: string
      region?: string
    }
    result: MarketDiscoverResponse
  }
  'market.events.list': {
    params: {
      series_id: string
    }
    result: MarketEventsResponse
  }
  'market.provider.connect': {
    params: {
      provider: string
      session_id: string
    }
    result: MarketProviderConnectResponse
  }
  'market.quotes': {
    params: {
      series: MarketSeriesRef[]
    }
    result: MarketQuotesResponse
  }
  'market.search': {
    params: {
      query: string
    }
    result: MarketSearchResponse
  }
  'market.selection.apply': {
    params: {
      edit: DeskEdit
      expected_revision: string
    }
    result: MarketSelectionApplyResponse
  }
  'market.selection.events.update': {
    params: {
      add: DeskSavedEvent[]
      remove: DeskSavedEvent[]
    }
    result: MarketSelectionApplyResponse
  }
  'market.selection.preview': {
    params: {
      edit: DeskEdit
    }
    result: MarketSelectionPreviewResponse
  }
  'market.selection.update': {
    params: {
      expected_revision: string
      patch: DeskPatch
    }
    result: MarketSelectionApplyResponse
  }
  'markets.model.chat': {
    params: {
      id: string
      message: string
      params?: null | ModelParameters
      session_id?: null | string
    }
    result: ModelBuildResponse
  }
  'markets.model.create': {
    params: {
      params?: null | ModelParameters
      question: string
      session_id?: null | string
    }
    result: ModelBuildResponse
  }
  'markets.model.delete': {
    params: {
      id: string
    }
    result: ModelDeleteResponse
  }
  'markets.model.export': {
    params: {
      id: string
    }
    result: ModelExportResponse
  }
  'markets.model.get': {
    params: {
      id: string
      session_id?: null | string
      version?: null | number
    }
    result: ModelGetResponse
  }
  'markets.model.list': {
    params: {
      limit?: number
      status?: null | string
    }
    result: ModelListResponse
  }
  'markets.model.renarrate': {
    params: {
      id: string
    }
    result: ModelBuildResponse
  }
  'markets.model.retry': {
    params: {
      id: string
      session_id?: null | string
    }
    result: ModelBuildResponse
  }
  'markets.model.to_forecast': {
    params: {
      id: string
    }
    result: ModelForecastResponse
  }
  'model.disconnect': {
    params: {
      slug: string
    }
    result: ModelDisconnectResponse
  }
  'model.options': {
    params: {
      session_id?: null | string
    }
    result: ModelOptionsResponse
  }
  'model.save_key': {
    params: {
      api_key: string
      session_id?: null | string
      slug: string
    }
    result: ModelOptionProvider
  }
  'news.article': {
    params: {
      url: string
    }
    result: NewsArticleResponse
  }
  'news.configure': {
    params: {
      action: 'add' | 'empty' | 'remove' | 'starter'
      feed?: null | NewsSubscription
    }
    result: NewsDeskResponse
  }
  'news.desk': {
    params: Record<string, never>
    result: NewsDeskResponse
  }
  'news.feed': {
    params: {
      url: string
    }
    result: NewsFeedResponse
  }
  'news.search': {
    params: {
      articles: NewsArticle[]
      limit?: number
      query: string
    }
    result: NewsSearchResponse
  }
  'obsidian.append': {
    params: {
      rel_path: string
      text: string
    }
    result: ObsidianWriteResponse
  }
  'obsidian.create': {
    params: {
      content?: string
      rel_path: string
      title?: string
    }
    result: ObsidianWriteResponse
  }
  'obsidian.note': {
    params: {
      rel_path?: null | string
    }
    result: ObsidianNoteResponse
  }
  'obsidian.search': {
    params: {
      limit?: number
      query?: null | string
    }
    result: ObsidianSearchResponse
  }
  'obsidian.setup': {
    params: {
      limit?: number
    }
    result: ObsidianSetupResponse
  }
  'obsidian.status': {
    params: {
      limit?: number
    }
    result: ObsidianStatusResponse
  }
  'obsidian.write': {
    params: {
      content: string
      expected_content?: null | string
      rel_path: string
    }
    result: ObsidianWriteResponse
  }
  'paste.collapse': {
    params: {
      text: string
    }
    result: PasteCollapseResponse
  }
  'plugins.list': {
    params: Record<string, never>
    result: PluginsResponse
  }
  'pm.book': {
    params: {
      market_id: string
      venue: string
    }
    result: PmBookResponse
  }
  'pm.detail': {
    params: {
      event_id: string
      venue: string
    }
    result: PmDetailResponse
  }
  'pm.history': {
    params: {
      interval?: null | string
      market_id: string
      max_points?: null | number
      period_interval?: null | number
      range?: null | string
      series_ticker?: null | string
      venue: string
    }
    result: PmHistoryResponse
  }
  'pm.list': {
    params: {
      limit?: null | number
      query?: null | string
      tag?: null | string
      venue?: null | string
    }
    result: PmListResponse
  }
  'pm.stream.start': {
    params: {
      market_ids?: null | string[]
      venue: string
    }
    result: PMStreamStart
  }
  'pm.stream.stop': {
    params: {
      market_ids?: null | string[]
      venue: string
    }
    result: PmStreamStopResponse
  }
  'process.stop': {
    params: {
      session_id?: string
    }
    result: ProcessStopResponse
  }
  'prompt.background': {
    params: {
      session_id?: null | string
      text?: null | string
    }
    result: BackgroundStartResponse
  }
  'prompt.submit': {
    params: {
      session_id?: null | string
      text?: null | string
    }
    result: PromptSubmitResponse
  }
  'reload.env': {
    params: Record<string, never>
    result: ReloadEnvResponse
  }
  'reload.mcp': {
    params: {
      always?: boolean
      confirm?: boolean
      session_id?: null | string
    }
    result: ReloadMcpResponse
  }
  'rollback.diff': {
    params: {
      hash?: null | string
      session_id?: null | string
    }
    result: RollbackDiffResponse
  }
  'rollback.list': {
    params: {
      session_id?: null | string
    }
    result: RollbackListResponse
  }
  'rollback.restore': {
    params: {
      file_path?: null | string
      hash?: null | string
      session_id?: null | string
    }
    result: RollbackRestoreResponse
  }
  'secret.respond': {
    params: {
      request_id?: null | string
      session_id?: null | string
      value?: string
    }
    result: SecretRespondResponse
  }
  'session.branch': {
    params: {
      name?: string
      session_id?: null | string
    }
    result: SessionBranchResponse
  }
  'session.branch_replace': {
    params: {
      name?: string
      session_id?: null | string
    }
    result: SessionBranchResponse
  }
  'session.close': {
    params: {
      session_id?: null | string
    }
    result: SessionCloseResponse
  }
  'session.compress': {
    params: {
      focus_topic?: null | string
      session_id?: null | string
    }
    result: SessionCompressResponse
  }
  'session.create': {
    params: {
      cols?: null | number
      server_requests?: boolean
    }
    result: SessionCreateResponse
  }
  'session.delete': {
    params: {
      session_id: string
    }
    result: SessionDeleteResponse
  }
  'session.history': {
    params: {
      session_id?: null | string
    }
    result: SessionHistoryResponse
  }
  'session.interrupt': {
    params: {
      session_id?: null | string
    }
    result: SessionInterruptResponse
  }
  'session.list': {
    params: {
      limit?: number
    }
    result: SessionListResponse
  }
  'session.most_recent': {
    params: {
      limit?: null | number
    }
    result: SessionMostRecentResponse
  }
  'session.resume': {
    params: {
      cols?: null | number
      replace_session_id?: null | string
      server_requests?: boolean
      session_id: string
    }
    result: SessionResumeResponse
  }
  'session.save': {
    params: {
      session_id?: null | string
    }
    result: SessionSaveResponse
  }
  'session.status': {
    params: {
      session_id?: null | string
    }
    result: SessionStatusResponse
  }
  'session.steer': {
    params: {
      session_id?: null | string
      text?: null | string
    }
    result: SessionSteerResponse
  }
  'session.title': {
    params: {
      session_id?: null | string
      title?: null | string
    }
    result: SessionTitleResponse
  }
  'session.undo': {
    params: {
      session_id?: null | string
    }
    result: SessionUndoResponse
  }
  'session.usage': {
    params: {
      session_id?: null | string
    }
    result: SessionUsageResponse
  }
  'setup.status': {
    params: Record<string, never>
    result: SetupStatusResponse
  }
  'shell.exec': {
    params: {
      command?: null | string
    }
    result: ShellExecResponse
  }
  'skills.manage': {
    params: {
      action?: 'browse' | 'inspect' | 'install' | 'list' | 'search'
      page?: number
      page_size?: number
      query?: string
      session_id?: null | string
    }
    result: SkillsManageResponse
  }
  'skills.reload': {
    params: Record<string, never>
    result: SkillsReloadResponse
  }
  'slash.exec': {
    params: {
      command?: null | string
      session_id?: null | string
    }
    result: SlashExecResponse
  }
  'spawn_tree.list': {
    params: {
      cross_session?: boolean
      limit?: number
      session_id?: null | string
    }
    result: SpawnTreeListResponse
  }
  'spawn_tree.load': {
    params: {
      path?: null | string
    }
    result: SpawnTreeLoadResponse
  }
  'spawn_tree.save': {
    params: {
      finished_at?: null | number
      label?: string
      session_id?: null | string
      started_at?: null | number
      subagents: unknown[]
    }
    result: SpawnTreeSaveResponse
  }
  'subagent.interrupt': {
    params: {
      session_id?: string
      subagent_id?: null | string
    }
    result: SubagentInterruptResponse
  }
  'sudo.respond': {
    params: {
      password?: string
      request_id?: null | string
      session_id?: null | string
    }
    result: SudoRespondResponse
  }
  'superforecasting_agent.tooling.toolsets.list': {
    params: {
      session_id?: null | string
    }
    result: ToolsetsResponse
  }
  'terminal.resize': {
    params: {
      cols?: null | number
      rows?: null | number
      session_id?: null | string
    }
    result: TerminalResizeResponse
  }
  'theme.list': {
    params: Record<string, never>
    result: ThemeListResponse
  }
  'tools.configure': {
    params: {
      action?: null | string
      names?: null | string[]
      session_id?: null | string
    }
    result: ToolsConfigureResponse
  }
  'tools.list': {
    params: {
      session_id?: null | string
    }
    result: ToolsetsResponse
  }
  'tools.show': {
    params: {
      session_id?: null | string
    }
    result: SectionsResponse
  }
  'toolsets.list': {
    params: {
      session_id?: null | string
    }
    result: ToolsetsResponse
  }
  'voice.record': {
    params: {
      action?: string
      session_id?: null | string
    }
    result: VoiceRecordResponse
  }
  'voice.stop': {
    params: {
      action?: string
      session_id?: null | string
    }
    result: VoiceRecordResponse
  }
  'voice.toggle': {
    params: {
      action?: string
      session_id?: null | string
    }
    result: VoiceToggleResponse
  }
  'voice.tts': {
    params: {
      session_id?: null | string
      text: string
    }
    result: VoiceTtsResponse
  }
}

export type RpcMethod = keyof RpcMethods

export type RpcArgs<M extends RpcMethod> = {} extends RpcMethods[M]['params'] ? [params?: RpcMethods[M]['params']] : [params: RpcMethods[M]['params']]

export type RpcRequest = <M extends RpcMethod>(method: M, ...args: RpcArgs<M>) => Promise<RpcMethods[M]['result']>
