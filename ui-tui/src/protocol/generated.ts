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

export interface ApprovalRespondResponse {
  ok?: boolean
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
  request_id: null | string
  session_id: null | string
}

export interface ClarifyRespondResponse {
  ok?: boolean
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
  config?: ConfigFullConfig
}

export interface ConfigGetValueRequest {
  key: null | string
}

export interface ConfigGetValueResponse {
  display?: string
  home?: string
  value?: string
}

export interface ConfigMtimeResponse {
  mtime?: number
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

export interface DelegationActiveEntry {
  depth?: number
  goal?: string
  model?: null | string
  parent_id?: null | string
  started_at?: number
  status?: string
  subagent_id?: string
  tool_count?: number
}

export interface DelegationPauseRequest {
  paused: null | boolean
}

export interface DelegationPauseResponse {
  paused?: boolean
}

export interface DelegationStatusRequest {
}

export interface DelegationStatusResponse {
  active?: DelegationActiveEntry[]
  max_concurrent_children?: number
  max_spawn_depth?: number
  paused?: boolean
}

export interface ErrorPayload {
  durable_status?: string
  message: string
  turn_id?: string
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
  quorum_autorun?: null | boolean
  saturation?: null | number
  title?: string
}

export interface ForecastReforecastStartRequest {
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
  reason: null | string
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

export interface ImageAttachRequest {
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
}

export interface ModelOptionsResponse {
  model?: string
  provider?: string
  providers?: ModelOptionProvider[]
  reasoning_effort?: string
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

export interface ObsidianStatusRequest {
}

export interface ObsidianStatusResponse {
  count?: number
  exists?: boolean
  notes?: ObsidianNote[]
  vault?: null | string
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

export interface ProcessStopRequest {
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

export interface ReloadEnvRequest {
}

export interface ReloadEnvResponse {
  updated?: number
}

export interface ReloadMcpRequest {
}

export interface ReloadMcpResponse {
  message?: string
  status?: string
}

export interface RespondRequest {
  request_id: null | string
  session_id: null | string
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
}

export interface RollbackDiffResponse {
  diff?: string
  rendered?: string
  stat?: string
}

export interface RollbackListRequest {
}

export interface RollbackListResponse {
  checkpoints?: RollbackCheckpoint[]
  enabled?: boolean
}

export interface RollbackRestoreRequest {
  hash: null | string
}

export interface RollbackRestoreResponse {
  error?: string
  history_removed?: number
  message?: string
  reason?: string
  restored_to?: string
  success?: boolean
}

export interface SecretRequestPayload {
  env_var: string
  metadata?: Record<string, unknown>
  prompt: string
  request_id: string
}

export interface SecretRespondResponse {
  ok?: boolean
}

export interface SessionBranchRequest {
  session_id: null | string
}

export interface SessionBranchResponse {
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
  update_behind: null | boolean
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
}

export interface SessionListResponse {
  sessions?: SessionListItem[]
}

export interface SessionMostRecentRequest {
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
  session_id: string
}

export interface SessionResumeResponse {
  info?: SessionInfo
  message_count?: number
  messages: GatewayTranscriptMessage[]
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

export interface ShellExecRequest {
  command: null | string
}

export interface ShellExecResponse {
  code: number
  stderr?: string
  stdout?: string
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
  status?: 'completed' | 'error' | 'failed' | 'interrupted' | 'queued' | 'running' | 'timeout'
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

export interface SudoRespondResponse {
  ok?: boolean
}

export interface TerminalResizeRequest {
  cols: null | number
  rows: null | number
  session_id: null | string
}

export interface TerminalResizeResponse {
  ok?: boolean
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
