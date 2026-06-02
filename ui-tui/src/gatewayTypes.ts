import type { SessionInfo, SlashCategory, SubagentStatus, Usage } from './types.js'

export interface GatewaySkin {
  banner_hero?: string
  banner_logo?: string
  branding?: Record<string, string>
  colors?: Record<string, string>
  help_header?: string
  tool_prefix?: string
}

export interface GatewayCompletionItem {
  display: string
  meta?: string
  text: string
}

export interface GatewayTranscriptMessage {
  context?: string
  name?: string
  role: 'assistant' | 'system' | 'tool' | 'user'
  text?: string
}

// ── Commands / completion ────────────────────────────────────────────

export interface CommandsCatalogResponse {
  canon?: Record<string, string>
  categories?: SlashCategory[]
  pairs?: [string, string][]
  skill_count?: number
  sub?: Record<string, string[]>
  warning?: string
}

export interface CompletionResponse {
  items?: GatewayCompletionItem[]
  replace_from?: number
}

export interface SlashExecResponse {
  output?: string
  warning?: string
}

export type CommandDispatchResponse =
  | { output?: string; type: 'exec' | 'plugin' }
  | { target: string; type: 'alias' }
  | { message?: string; name: string; type: 'skill' }
  | { message: string; notice?: string; type: 'send' }

// ── Config ───────────────────────────────────────────────────────────

export interface ConfigDisplayConfig {
  bell_on_complete?: boolean
  busy_input_mode?: string
  details_mode?: string
  inline_diffs?: boolean
  mouse_tracking?: boolean | null | number | string
  sections?: Record<string, string>
  show_cost?: boolean
  show_reasoning?: boolean
  streaming?: boolean
  thinking_mode?: string
  tui_auto_resume_recent?: boolean
  tui_compact?: boolean
  /** Legacy alias for display.mouse_tracking. */
  tui_mouse?: boolean | null | number | string
  // Forward-compat: backend may send styles this client doesn't know yet.
  // `normalizeIndicatorStyle` falls back to 'unicode' for those, but the
  // wire type is documented as `string` so consumers don't get a false
  // narrowing-and-autocomplete contract on a value that requires runtime
  // validation anyway.
  tui_status_indicator?: string
  tui_statusbar?: 'bottom' | 'off' | 'on' | 'top' | boolean
}

export interface ConfigVoiceConfig {
  // Raw `yaml.safe_load()` value from config; may be non-string if hand-edited.
  // Callers must normalize/validate at runtime (parseVoiceRecordKey()).
  record_key?: unknown
}

export interface ConfigFullResponse {
  config?: { display?: ConfigDisplayConfig; voice?: ConfigVoiceConfig }
}

export interface ConfigMtimeResponse {
  mtime?: number
}

export interface ConfigGetValueResponse {
  display?: string
  home?: string
  value?: string
}

export interface ConfigSetResponse {
  credential_warning?: string
  history_reset?: boolean
  info?: SessionInfo
  value?: string
  warning?: string
}

export interface SetupStatusResponse {
  provider_configured?: boolean
}

// ── Session lifecycle ────────────────────────────────────────────────

export interface SessionCreateResponse {
  info?: SessionInfo & { config_warning?: string; credential_warning?: string }
  session_id: string
}

export interface SessionResumeResponse {
  info?: SessionInfo
  message_count?: number
  messages: GatewayTranscriptMessage[]
  resumed?: string
  session_id: string
}

export interface SessionListItem {
  id: string
  message_count: number
  preview: string
  source?: string
  started_at: number
  title: string
}

export interface SessionListResponse {
  sessions?: SessionListItem[]
}

export interface SessionDeleteResponse {
  deleted: string
}

export interface SessionMostRecentResponse {
  session_id?: null | string
  source?: string
  started_at?: number
  title?: string
}

export interface SessionTitleResponse {
  pending?: boolean
  session_key?: string
  title?: string
}

export interface SessionSaveResponse {
  file?: string
}

export interface SessionUndoResponse {
  removed?: number
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

export interface SessionStatusResponse {
  output?: string
}

export interface ForecastDashboardResponse {
  output?: string
  summary?: ForecastDashboardSummary
}

export interface ForecastDashboardSummary {
  active_count?: number
  alerts?: ForecastDashboardAlert[]
  calibration?: ForecastDashboardCalibration
  doctor?: ForecastDashboardDoctor
  evidence_status?: ForecastDashboardEvidenceStatus
  live_performance?: ForecastDashboardLivePerformance
  learning?: ForecastDashboardLearning
  closing_soon_count?: number
  open_alert_count?: number
  open_assumption_count?: number
  open_reference_class_count?: number
  product?: string
  questions?: ForecastDashboardQuestion[]
  review_queue?: ForecastDashboardReview[]
  review_queue_count?: number
  recent_backtests?: ForecastDashboardBacktest[]
  scheduled_review_run_count?: number
  scheduled_review_runs?: ForecastDashboardScheduleRun[]
  stale_assumption_count?: number
  stale_reference_class_count?: number
  // Thesis layer summary (the macro aggregates over the book).
  question_total?: number
  thesis_count?: number
  factor_count?: number
  entity_count?: number
  theses?: ForecastDashboardThesis[]
  factors?: ForecastDashboardFactor[]
}

export interface ForecastDashboardThesis {
  id?: string
  title?: string
  domain?: null | string
  health_probability?: null | number
  health_display?: string
  thesis_score?: null | number
  coverage?: null | number
  n_eff?: null | number
  delta?: null | number
  member_count?: number
  status?: string
}

export interface ForecastDashboardFactor {
  id?: string
  title?: string
  domain?: null | string
  units?: null | string
  mean?: null | number
  sd?: null | number
  q05?: null | number
  q95?: null | number
  downside?: null | number
  cvar?: null | number
  coverage?: null | number
  delta?: null | number
  member_count?: number
  status?: string
}

export interface ForecastDashboardDoctor {
  claim_live_superforecasting?: boolean
  doctor_status?: string
  next_action?: string
  next_actions?: Array<{
    action?: string
    requirement_id?: string
    source?: string
  }>
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

export interface ForecastDashboardEvidenceStatus {
  backtests?: {
    agent_protocol_scored_count?: number
    distinct_dataset_count?: number
    external_dataset_count?: number
    external_source_family_count?: number
    leakage_free_run_count?: number
    positive_best_baseline_edge_run_count?: number
    run_count?: number
    source_families?: string[]
  }
  can_claim_live_superforecasting?: boolean
  gaps?: string[]
  message?: string
  next_actions?: Array<{
    action?: string
    requirement_id?: string
  }>
  requirements?: Array<{
    description?: string
    id?: string
    observed?: number
    passed?: boolean
    required?: number
    recommended_action?: string
  }>
  score_counts?: {
    backtest?: number
    imported_baseline?: number
    live?: number
  }
  verdict?: string
}

export interface ForecastDashboardLivePerformance {
  agent?: {
    mean_brier?: null | number
    mean_log_score?: null | number
  }
  baselines?: ForecastDashboardLiveBaseline[]
  claim_status?: ForecastDashboardClaimStatus
  score_count?: number
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

export interface ForecastDashboardCalibration {
  calibration_eligible?: boolean | null
  count?: number
  domain?: null | string
  ensemble_component_contributions?: ForecastDashboardCalibrationComponent[]
  forecast_origin?: null | string
  horizon?: null | string
  mean_brier?: null | number
  mean_log_score?: null | number
  mean_sharpness?: null | number
  probability_movement_count?: number
  mean_probability_movement_before_close?: null | number
  mean_abs_probability_movement_before_close?: null | number
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

export interface ForecastDashboardClaimStatus {
  can_claim_live_superforecasting?: boolean
  case_count?: number
  evidence_type?: string
  leakage_checks_passed?: boolean
  message?: string
  scored_count?: number
  verdict?: string
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

export interface ForecastDashboardLearning {
  active_lessons?: number
  invalidated_lessons?: number
  recent_lessons?: ForecastDashboardLesson[]
  tentative_lessons?: number
  top_error_profiles?: ForecastDashboardErrorProfile[]
  total_lessons?: number
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
  probability?: null | number | Record<string, unknown> | string
  resolution_time?: null | string
  stale_assumption_count?: number
  stale_reference_class_count?: number
  status?: string
  title?: string
  topics?: string[]
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
  probability?: null | number | Record<string, unknown> | string
  reasons?: string[]
  resolution_time?: null | string
  title?: string
}

export interface ForecastCommandResponse {
  code?: number
  output?: string
}

export interface ForecastQuestionPacketResponse {
  packet?: ForecastQuestionPacket
}

// A time-indexed analyst write-up ("desk note"): the model's prose read on a
// forecast. `brief` is written on every update, `retrospective` once it resolves.
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
  kind?: 'brief' | 'retrospective'
  looking_for?: string
  stance?: 'lean_no' | 'lean_yes' | 'toss_up' | null
  verdict?: 'close' | 'far' | 'right' | 'wrong' | null
}

// One related forecast's world-view, surfaced for cross-pollination on the desk.
export interface ForecastRelatedView {
  as_of?: null | string
  be_aware?: null | string
  headline_kind?: 'distribution' | 'probability'
  headline_probability?: null | number
  id?: string
  link_label?: null | string
  link_type?: 'auto' | 'explicit'
  note_headline?: null | string
  probability_display?: string
  reasons_down?: string[]
  reasons_up?: string[]
  relationship?: 'child' | 'correlated_sibling' | 'parent'
  stance?: 'lean_no' | 'lean_yes' | 'toss_up' | null
  title?: string
  verdict?: 'close' | 'far' | 'right' | 'wrong' | null
}

export interface ForecastSharedSource {
  kind?: string
  shared_with?: string[]
  source?: string
}

export interface ForecastRelated {
  forecasts?: ForecastRelatedView[]
  informed_by?: string[]
  shared_sources?: ForecastSharedSource[]
}

export interface ForecastQuestionPacket {
  analyst_note?: ForecastAnalystNote | null
  analyst_notes?: ForecastAnalystNote[]
  assumptions?: ForecastQuestionPacketAssumption[]
  baseline_comparisons?: Record<string, unknown>[]
  calibration_lessons?: ForecastDashboardLesson[]
  corrections?: Record<string, unknown>[]
  domain_error_profiles?: ForecastDashboardErrorProfile[]
  evidence?: ForecastQuestionPacketEvidence[]
  forecast_history?: ForecastQuestionPacketSnapshot[]
  informed_by?: string[]
  model_runs?: Record<string, unknown>[]
  postmortems?: Record<string, unknown>[]
  question?: ForecastQuestionPacketQuestion
  reference_classes?: ForecastQuestionPacketReferenceClass[]
  related_forecasts?: ForecastRelatedView[]
  related_shared_sources?: ForecastSharedSource[]
  resolution?: Record<string, unknown> | null
  retrospective?: ForecastAnalystNote | null
  scores?: Record<string, unknown>[]
  watched_sources?: Record<string, unknown>[]
}

export interface ForecastQuestionPacketQuestion {
  close_time?: null | string
  created_at?: string
  description?: string
  domain?: null | string
  id?: string
  impact?: null | string
  next_review_at?: null | string
  outcome_space?: {
    choices?: unknown[]
    type?: string
  }
  resolution_criteria?: string
  resolution_source?: null | string
  resolution_time?: null | string
  review_cadence?: null | string
  status?: string
  tags?: string[]
  title?: string
  topics?: string[]
}

export interface ForecastQuestionPacketSnapshot {
  as_of?: string
  confidence?: null | number
  evidence_refs?: string[]
  forecast_id?: string
  forecast_origin?: string
  method?: null | string
  probability_or_distribution?: null | number | Record<string, unknown> | string
  rationale?: string
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

export interface ForecastQuestionPacketAssumption {
  id?: string
  status?: string
  text?: string
}

export interface ForecastWorkspaceResponse {
  active_count?: number
  closing_soon_count?: number
  factor_count?: number
  factors?: ForecastFactor[]
  forecasts?: ForecastWorkspaceItem[]
  generated_at?: string
  open_alert_count?: number
  output?: string
  product?: string
  thesis_count?: number
  theses?: ForecastThesis[]
}

// ── Thesis layer ─────────────────────────────────────────────────────────────
// A thesis aggregates the weighted beliefs of its member forecasts into a
// rolling macro health probability + a 0-100 score (see forecasting/thesis.py).
// These shapes mirror the web terminal's forecastTypes.ts field-for-field.

export interface ForecastThesisBadge {
  thesis_id: string
  thesis_title?: string
  direction?: 'support' | 'inverted'
  weight?: null | number
  role?: null | string
}

export interface ForecastThesisComponent {
  id?: string
  title?: null | string
  direction?: 'support' | 'inverted'
  role?: null | string
  weight?: null | number
  w_norm?: null | number
  s_raw?: null | number
  s_i?: null | number
  sigma?: null | number
  contribution_pts?: null | number
  marginal_health_delta?: null | number
  status?: string
  flags?: string[]
  as_of?: null | string
  outcome_type?: null | string
  latest_belief_display?: string
  latest_headline?: null | number
}

export interface ForecastThesisHistoryPoint {
  as_of?: string
  created_at?: string
  headline_probability?: null | number // the health probability series
  thesis_score?: null | number
  score_low?: null | number
  score_high?: null | number
}

// Per-entity (stock / candidate / currency / sector …) suitability: the same
// 0..1 weighted aggregate as the thesis, computed over the entity's own signal
// vector. The §22 per-name read ("BE/IREN/CORZ better suited when the
// power-bottleneck rises"). A withheld suitability stays null — never faked.
export interface ForecastThesisEntity {
  name?: string
  label?: string
  kind?: string
  suitability?: null | number
  suitability_display?: string
  score?: null | number
  band?: null | number[]
  coverage?: null | number
  n_eff?: null | number
  delta?: null | number
  stance?: string
  trend?: string
  action?: string
  top_driver?: null | string
  top_driver_id?: null | string
  weight_count?: number
  contributions?: ForecastThesisComponent[]
}

// A §10 trade trigger: a member signal moved → entities better / less suited.
export interface ForecastThesisTrigger {
  member_id?: string
  signal?: string
  delta?: null | number
  direction?: 'down' | 'up'
  note?: string
  better?: string[]
  less?: string[]
}

export interface ForecastThesis {
  id?: string
  title?: string
  domain?: null | string
  topics?: string[]
  status?: string
  as_of?: null | string
  freshness?: string
  health_probability?: null | number
  health_display?: string
  thesis_score?: null | number
  score_band?: { q05?: null | number; q50?: null | number; q95?: null | number } | null
  coverage?: null | number
  n_eff?: null | number
  rho?: null | number
  delta?: null | number
  member_count?: number
  components?: ForecastThesisComponent[]
  spread?: Record<string, unknown> | null
  history?: ForecastThesisHistoryPoint[]
  analyst_note?: ForecastAnalystNote | null
  rationale?: null | string
  snapshot_count?: number
  entities?: ForecastThesisEntity[]
  triggers?: ForecastThesisTrigger[]
  // Every question in the thesis ecosystem (members + entity-weighted questions).
  question_ids?: string[]
}

// ── Factor layer ─────────────────────────────────────────────────────────────
// A factor is a weighted basket whose RETURN distribution + volatility +
// downside is the portfolio aggregate of its constituents' return
// distributions. Mirrors the thesis shapes but in return/volatility units
// rather than a health probability. Withheld moments stay null — never faked.

export interface ForecastFactorConstituent {
  id?: string
  title?: null | string
  direction?: 'long' | 'short'
  weight?: null | number
  w_norm?: null | number
  mean?: null | number
  sd?: null | number
  contribution?: null | number
  status?: string
  flags?: string[]
}

export interface ForecastFactorHistoryPoint {
  as_of?: string
  created_at?: string
  headline_probability?: null | number // the factor return (mean) series
  band_low?: null | number // q05
  band_high?: null | number // q95
  volatility?: null | number
}

export interface ForecastFactor {
  id?: string
  title?: string
  domain?: null | string
  topics?: string[]
  units?: null | string
  as_of?: null | string
  freshness?: string
  mean?: null | number
  sd?: null | number
  volatility?: null | number
  q05?: null | number
  q50?: null | number
  q95?: null | number
  downside?: null | number
  cvar?: null | number
  coverage?: null | number
  n_eff?: null | number
  delta?: null | number
  member_count?: number
  constituents?: ForecastFactorConstituent[]
  history?: ForecastFactorHistoryPoint[]
  analyst_note?: ForecastAnalystNote | null
  rationale?: null | string
  snapshot_count?: number
}

export interface ForecastWorkspaceItem {
  action_threshold?: null | string
  analyst_note?: ForecastAnalystNote | null
  analyst_notes?: ForecastAnalystNote[]
  as_of?: null | string
  change_my_mind?: string[]
  close_time?: null | string
  closing_soon?: boolean
  confidence?: null | number
  decision_deadline?: null | string
  decision_owner?: null | string
  decision_readiness_issues?: string[]
  delta?: null | number
  distribution?: ForecastWorkspaceDistribution | null
  domain?: null | string
  evidence?: ForecastWorkspaceEvidence[]
  evidence_count?: number
  freshness?: string
  headline_kind?: 'distribution' | 'probability'
  headline_probability?: null | number
  history?: ForecastWorkspaceHistoryPoint[]
  id?: string
  impact?: null | string
  method?: null | string
  open_alert_count?: number
  outcome_choices?: unknown[]
  outcome_type?: string
  panel?: ForecastWorkspacePanel | null
  probability?: null | number | Record<string, unknown> | string
  probability_display?: string
  rationale?: null | string
  reasons_down?: string[]
  reasons_up?: string[]
  related?: ForecastRelated | null
  resolution?: ForecastWorkspaceResolution | null
  resolution_criteria?: string
  resolution_time?: null | string
  retrospective?: ForecastAnalystNote | null
  scores?: ForecastWorkspaceScores | null
  snapshot_count?: number
  status?: string
  title?: string
  topics?: string[]
  units?: null | string
  update_triggers?: ForecastWorkspaceTrigger[]
  // The theses this question is a weighted member of (the "member of" badge).
  thesis_ids?: ForecastThesisBadge[]
}

export interface ForecastWorkspaceDistribution {
  ci50?: number[] | null
  ci90?: number[] | null
  mean?: null | number
  median?: null | number
  pmf?: Array<{ label: string; probability: number }> | null
  sd?: null | number
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
  probability?: null | number | Record<string, unknown> | string
  rationale?: string
  reasons_down_count?: number
  reasons_up_count?: number
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

export interface ForecastWorkspacePanel {
  aggregate_probability?: null | number
  aggregation_method?: string
  created_at?: string
  estimates?: ForecastWorkspacePanelEstimate[]
  id?: string
  spread?: Record<string, number>
  trim?: number
}

export interface ForecastWorkspacePanelEstimate {
  confidence_high?: null | number
  confidence_low?: null | number
  crux?: null | string
  perspective?: string
  probability?: null | number
  trimmed?: boolean
  weight?: null | number
}

export interface ForecastWorkspaceScores {
  count?: number
  last_bucket?: null | string
  last_scored_at?: null | string
  mean_brier?: null | number
  mean_log_score?: null | number
}

export interface ForecastWorkspaceResolution {
  outcome?: unknown
  resolution_status?: string
  resolved_at?: string
  scoreable?: boolean
}

export interface ForecastWorkspaceTrigger {
  action?: string
  mechanism?: string
  notes?: string
  source_ref?: string
  threshold?: string
  window?: string
}

export interface ForecastQuestionPacketReferenceClass {
  base_rate?: null | number
  id?: string
  name?: string
  status?: string
}

export interface SessionCompressResponse {
  after_messages?: number
  after_tokens?: number
  before_messages?: number
  before_tokens?: number
  info?: SessionInfo
  messages?: GatewayTranscriptMessage[]
  removed?: number
  summary?: {
    headline?: string
    noop?: boolean
    note?: null | string
    token_line?: string
  }
  usage?: Usage
}

export interface SessionBranchResponse {
  session_id?: string
  title?: string
}

export interface SessionCloseResponse {
  ok?: boolean
}

export interface SessionInterruptResponse {
  ok?: boolean
}

export interface SessionSteerResponse {
  status?: 'queued' | 'rejected'
  text?: string
}

// ── Prompt / submission ──────────────────────────────────────────────

export interface PromptSubmitResponse {
  ok?: boolean
}

export interface BackgroundStartResponse {
  task_id?: string
}

export interface ClarifyRespondResponse {
  ok?: boolean
}

export interface ApprovalRespondResponse {
  ok?: boolean
}

export interface SudoRespondResponse {
  ok?: boolean
}

export interface SecretRespondResponse {
  ok?: boolean
}

// ── Shell / clipboard / input ────────────────────────────────────────

export interface ShellExecResponse {
  code: number
  stderr?: string
  stdout?: string
}

export interface ClipboardPasteResponse {
  attached?: boolean
  count?: number
  height?: number
  message?: string
  token_estimate?: number
  width?: number
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

export interface TerminalResizeResponse {
  ok?: boolean
}

// ── Image attach ─────────────────────────────────────────────────────

export interface ImageAttachResponse {
  height?: number
  name?: string
  remainder?: string
  token_estimate?: number
  width?: number
}

// ── Voice ────────────────────────────────────────────────────────────

export interface VoiceToggleResponse {
  audio_available?: boolean
  available?: boolean
  details?: string
  enabled?: boolean
  record_key?: string
  stt_available?: boolean
  tts?: boolean
}

export interface VoiceRecordResponse {
  status?: 'busy' | 'recording' | 'stopped'
  text?: string
}

// ── Tools (TS keeps configure since it resets local history) ─────────

export interface ToolsConfigureResponse {
  changed?: string[]
  enabled_toolsets?: string[]
  info?: SessionInfo
  missing_servers?: string[]
  reset?: boolean
  unknown?: string[]
}

// ── Model picker ─────────────────────────────────────────────────────

export interface ModelOptionProvider {
  auth_type?: string
  authenticated?: boolean
  is_current?: boolean
  key_env?: string
  models?: string[]
  name: string
  slug: string
  total_models?: number
  warning?: string
}

export interface ModelOptionsResponse {
  model?: string
  provider?: string
  providers?: ModelOptionProvider[]
}

// ── MCP ──────────────────────────────────────────────────────────────

export interface ReloadMcpResponse {
  status?: string
  message?: string
}

export interface ReloadEnvResponse {
  updated?: number
}

export interface ProcessStopResponse {
  killed?: number
}

export interface BrowserManageResponse {
  connected?: boolean
  messages?: string[]
  url?: string
}

export interface RollbackCheckpoint {
  hash: string
  message?: string
  timestamp?: string
}

export interface RollbackListResponse {
  checkpoints?: RollbackCheckpoint[]
  enabled?: boolean
}

export interface RollbackDiffResponse {
  diff?: string
  rendered?: string
  stat?: string
}

export interface RollbackRestoreResponse {
  error?: string
  history_removed?: number
  message?: string
  reason?: string
  restored_to?: string
  success?: boolean
}

// ── Subagent events ──────────────────────────────────────────────────

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
  output_tail?: { is_error?: boolean; preview?: string; tool?: string }[]
  output_tokens?: number
  parent_id?: null | string
  reasoning_tokens?: number
  status?: SubagentStatus
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

// ── Delegation control RPCs ──────────────────────────────────────────

export interface DelegationStatusResponse {
  active?: {
    depth?: number
    goal?: string
    model?: null | string
    parent_id?: null | string
    started_at?: number
    status?: string
    subagent_id?: string
    tool_count?: number
  }[]
  max_concurrent_children?: number
  max_spawn_depth?: number
  paused?: boolean
}

export interface DelegationPauseResponse {
  paused?: boolean
}

export interface SubagentInterruptResponse {
  found?: boolean
  subagent_id?: string
}

// ── Spawn-tree snapshots ─────────────────────────────────────────────

export interface SpawnTreeListEntry {
  count: number
  finished_at?: number
  label?: string
  path: string
  session_id?: string
  started_at?: number | null
}

export interface SpawnTreeListResponse {
  entries?: SpawnTreeListEntry[]
}

export interface SpawnTreeLoadResponse {
  finished_at?: number
  label?: string
  session_id?: string
  started_at?: null | number
  subagents?: unknown[]
}

export type GatewayEvent =
  | { payload?: { skin?: GatewaySkin }; session_id?: string; type: 'gateway.ready' }
  | { payload?: GatewaySkin; session_id?: string; type: 'skin.changed' }
  | { payload: SessionInfo; session_id?: string; type: 'session.info' }
  | { payload?: { text?: string }; session_id?: string; type: 'thinking.delta' }
  | { payload?: undefined; session_id?: string; type: 'message.start' }
  | { payload?: { kind?: string; text?: string }; session_id?: string; type: 'status.update' }
  | { payload?: { state?: 'idle' | 'listening' | 'transcribing' }; session_id?: string; type: 'voice.status' }
  | { payload?: { no_speech_limit?: boolean; text?: string }; session_id?: string; type: 'voice.transcript' }
  | { payload: { line: string }; session_id?: string; type: 'gateway.stderr' }
  | {
      payload?: { level?: 'info' | 'warn' | 'error'; message?: string }
      session_id?: string
      type: 'browser.progress'
    }
  | {
      payload?: { cwd?: string; python?: string; stderr_tail?: string }
      session_id?: string
      type: 'gateway.start_timeout'
    }
  | { payload?: { preview?: string }; session_id?: string; type: 'gateway.protocol_error' }
  | { payload?: { text?: string }; session_id?: string; type: 'reasoning.delta' | 'reasoning.available' }
  | { payload: { name?: string; preview?: string }; session_id?: string; type: 'tool.progress' }
  | { payload: { name?: string }; session_id?: string; type: 'tool.generating' }
  | {
      payload: { context?: string; name?: string; tool_id: string; todos?: unknown[] }
      session_id?: string
      type: 'tool.start'
    }
  | {
      payload: {
        duration_s?: number
        error?: string
        inline_diff?: string
        name?: string
        summary?: string
        tool_id: string
        todos?: unknown[]
      }
      session_id?: string
      type: 'tool.complete'
    }
  | {
      payload: { choices: string[] | null; question: string; request_id: string }
      session_id?: string
      type: 'clarify.request'
    }
  | { payload: { command: string; description: string }; session_id?: string; type: 'approval.request' }
  | { payload: { request_id: string }; session_id?: string; type: 'sudo.request' }
  | { payload: { env_var: string; prompt: string; request_id: string }; session_id?: string; type: 'secret.request' }
  | { payload: { task_id: string; text: string }; session_id?: string; type: 'background.complete' }
  | { payload?: { text?: string }; session_id?: string; type: 'review.summary' }
  | { payload: SubagentEventPayload; session_id?: string; type: 'subagent.spawn_requested' }
  | { payload: SubagentEventPayload; session_id?: string; type: 'subagent.start' }
  | { payload: SubagentEventPayload; session_id?: string; type: 'subagent.thinking' }
  | { payload: SubagentEventPayload; session_id?: string; type: 'subagent.tool' }
  | { payload: SubagentEventPayload; session_id?: string; type: 'subagent.progress' }
  | { payload: SubagentEventPayload; session_id?: string; type: 'subagent.complete' }
  | { payload: { rendered?: string; text?: string }; session_id?: string; type: 'message.delta' }
  | {
      payload?: { reasoning?: string; rendered?: string; text?: string; usage?: Usage }
      session_id?: string
      type: 'message.complete'
    }
  | { payload?: { message?: string }; session_id?: string; type: 'error' }
