import type { SessionInfo, SlashCategory, SubagentStatus, Usage } from './types.js'

export interface GatewaySkin {
  appearance?: string
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

export interface ThemeOption {
  branding?: Record<string, string>
  colors?: Record<string, string>
  description?: string
  name: string
  source?: string
}

export interface ThemeListResponse {
  active?: string
  appearance?: string
  themes?: ThemeOption[]
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

// ── Warning-resolution RPCs (forecast.warnings.*) ────────────────────────────
// The TUI Warnings overlay drives the same gated dispatcher the CLI/cron use:
// resolve ONE alert, or run an interruptible AUTOMODE sweep that streams progress.

export interface ForecastWarningsListResponse {
  groups?: ForecastWarningGroup[]
  group_count?: number
  open_total?: number
}

export interface ForecastWarningGroup {
  reason?: string
  kind?: string
  severity?: string
  recommended_action?: string
  auto_resolvable?: boolean
  count?: number
  scope_refs?: string[]
}

// forecast.warnings.aggregate — the FULL open backlog folded into the 4 operator
// action tiers with per-tier + per-reason totals. Counts are server-side
// UNTRUNCATED (no limit); the headline must reflect the whole backlog.
//   free   — non-LLM gated close-outs (bookkeeping / score / postmortem / material)
//   agent  — REFORECAST (the opt-in LLM pass; folds the evidence-collection reasons)
//   manual — NO_AUTO (needs a human; never auto-resolved)
export interface ForecastWarningsTier {
  total?: number
  reasons?: ForecastWarningGroup[]
}

// The agent tier additionally carries a `stale` sub-bucket: the elapsed-time
// -staleness subset of its reforecast reasons (evidence_stale / last_update /
// close_time_within). Those reasons are STILL counted in the agent total — `stale`
// is a view over the tier, not a fourth tier.
export interface ForecastWarningsAgentTier extends ForecastWarningsTier {
  stale?: ForecastWarningsTier
}

export interface ForecastWarningsHeadline {
  total?: number
  free?: number
  agent?: number
  manual?: number
}

export interface ForecastWarningsAggregateResponse {
  headline?: ForecastWarningsHeadline
  free?: ForecastWarningsTier
  agent?: ForecastWarningsAgentTier
  manual?: ForecastWarningsTier
}

// One alert's resolution outcome (mirrors forecasting.warnings._result):
// status ∈ resolved | surfaced | failed | skipped; acked ONLY on real work.
export interface ForecastWarningResolveResult {
  alert_id?: string
  reason?: string
  scope_ref?: string
  kind?: string
  status?: string
  acknowledged?: boolean
  detail?: string
}

export interface ForecastWarningsResolveResponse {
  results?: ForecastWarningResolveResult[]
  count?: number
}

// forecast.warnings.dismiss — a RECORDED human silence (note + actor REQUIRED), NOT
// a resolution: it bulk-sets acknowledged_at on the selected open group without
// running any runner or moving any forecast. `matched` is the open group it
// selected; `count` is how many it actually silenced (re-surfaces after ttl_days).
export interface ForecastWarningDismissedItem {
  alert_id?: string
  reason?: string
  scope_ref?: string
  dismissed_at?: string
  dismiss_note?: string
  dismiss_actor?: string
  dismiss_reason?: string
  dismiss_ttl_days?: number
}

export interface ForecastWarningsDismissResponse {
  dismissed?: ForecastWarningDismissedItem[]
  count?: number
  matched?: number
}

export interface ForecastWarningsAutomodeRunResponse {
  job_id?: string
  dry_run?: boolean
}

// Streamed automode lifecycle (gw.on('forecast.warnings.automode.*')).
export interface ForecastWarningsAutomodeProgress {
  job_id?: string
  phase?: 'alert' | 'done' | 'reconcile' | 'start'
  done?: number
  total?: number
  remaining?: number
  alert_id?: string
  reason?: string
  status?: string
  cancelled?: boolean
  dry_run?: boolean
}

export interface ForecastWarningsAutomodeComplete {
  job_id?: string
  processed?: number
  total?: number
  cancelled?: boolean
  dry_run?: boolean
  tally?: Record<string, number>
}

export interface ForecastWarningsAutomodeError {
  job_id?: string
  message?: string
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

// ── forecast.calibration (the native calibration view) ──────────────────────

// One decile of the reliability curve: predicted vs observed frequency for
// binary forecasts whose P(yes) fell in `bucket`.
export interface ForecastCalibrationCurveRow {
  bucket?: string
  calibration_gap?: null | number
  count?: number
  mean_predicted?: null | number
  observed_frequency?: null | number
  sample_status?: 'empty' | 'low_sample' | 'ok'
}

export interface ForecastCalibrationBucketRow {
  bucket?: string
  count?: number
  mean_brier?: null | number
  sample_status?: 'empty' | 'low_sample' | 'ok'
}

// The signed calibration-bias report (forecasting/calibration_bias.py
// CalibrationBiasReport.to_payload). `status` is the measurement verdict;
// insufficient_evidence is a real state, not an error.
export interface ForecastCalibrationBias {
  advisory_text?: null | string
  ci_high?: null | number
  ci_low?: null | number
  curve_shape?: Record<string, unknown>[]
  direction?: 'over' | 'under' | null
  ece?: null | number
  ess?: number
  ess_min?: number
  horizon_label?: null | string
  n?: number
  notes?: string[]
  pvalue?: null | number
  scope_ref?: null | string
  scope_type?: string
  sce_raw?: null | number
  sce_shrunk?: null | number
  status?: 'calibrated' | 'insufficient_evidence' | 'overconfident' | 'underconfident'
}

// One recency window of the rolling calibration trend (ledger._calibration_trend).
export interface ForecastCalibrationTrendWindow {
  brier?: null | number
  n?: number
  period?: string
  sce?: null | number
}

// Rolling mean-Brier + signed-error over recency windows + a coarse direction.
export interface ForecastCalibrationTrend {
  direction?: 'improving' | 'insufficient' | 'stable' | 'worsening'
  windows?: ForecastCalibrationTrendWindow[]
}

// The full unsigned summary (forecasting/ledger.py calibration_summary).
export interface ForecastCalibrationSummary extends ForecastDashboardCalibration {
  buckets?: ForecastCalibrationBucketRow[]
  calibration_curve?: ForecastCalibrationCurveRow[]
  calibration_curve_sample_count?: number
  calibration_trend?: ForecastCalibrationTrend
  expected_calibration_error?: null | number
  max_calibration_error?: null | number
  mean_predicted?: null | number
  observed_frequency?: null | number
}

// A calibration lesson CORRECTING forecasts in scope + its measured coverage
// (forecasting/ledger.py calibration_correcting_lessons). `dormant` ⇒ never yet
// encountered at a commit (the recommended adjustment isn't biting yet).
export interface ForecastCalibrationLessonCoverage {
  application_rate?: number
  applied_count?: number
  in_scope_count?: number
  last_seen?: null | string
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

// A compact per-scope breakdown row (headline metrics only, no curve).
export interface ForecastCalibrationBreakdownRow {
  bias?: ForecastCalibrationBias | null
  calibration_curve_sample_count?: number
  count?: number
  domain?: string
  expected_calibration_error?: null | number
  mean_brier?: null | number
  mean_predicted?: null | number
  observed_frequency?: null | number
  origin?: string
}

export interface ForecastCalibrationResponse {
  bias?: ForecastCalibrationBias | null
  domain?: null | string
  domains?: ForecastCalibrationBreakdownRow[]
  lessons?: ForecastCalibrationLesson[]
  origin?: null | string
  origins?: ForecastCalibrationBreakdownRow[]
  summary?: ForecastCalibrationSummary
}

// ── forecast.triage.contested / .relabel (the contested-triage lens) ─────────

// One CONTESTED triage staging row awaiting an operator hand-label.
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

export interface ForecastTriageContestedResponse {
  contested?: ForecastTriageContestedRow[]
  count?: number
}

export type ForecastTriageLabel = 'irrelevant' | 'relevant_interesting' | 'relevant_uninteresting'

export interface ForecastTriageRelabelResponse {
  count?: number
  relabeled?: Record<string, unknown>[]
  success?: boolean
}

// ── forecast.schedule.status (schedule health) ───────────────────────────────

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

export interface ForecastScheduleCronHealth {
  errored?: string[]
  healthy?: boolean
  installed?: number
  jobs?: ForecastScheduleCronJob[]
  missed?: string[]
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

export interface ForecastScheduleStatusResponse {
  cron?: ForecastScheduleCronHealth
  healthy?: boolean
  scheduled_review_count?: number
  scheduled_reviews?: ForecastScheduleReviewRow[]
}

// ── forecast.quorum.status (the running-quorum chip) ─────────────────────────

// An in-flight auto-quorum reference attached to a desk forecast row.
export interface ForecastQuorumRunRef {
  created_at?: null | string
  run_id?: string
  status?: string
}

export interface ForecastQuorumStatusResult {
  aggregate_probability?: null | number
  committed_probability?: null | number
  disagreement?: null | number
  degraded?: boolean
  [key: string]: unknown
}

export interface ForecastQuorumStatusResponse {
  degraded?: boolean
  error?: null | string
  panel_run_id?: null | string
  progress?: { at?: string; detail?: string; stage?: string }[]
  question_id?: null | string
  result?: ForecastQuorumStatusResult
  run_id?: string
  status?: 'done' | 'error' | 'queued' | 'running'
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
  // The current snapshot's tail audit (categorical only). Optional: present only
  // when the dashboard payload carries it; the heuristics flag a question only
  // when this audit is present and failing (unearned mass over threshold).
  tail_audit?: ForecastTailAudit | null
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
  // Cross-pollination + scope-matched lessons for the detail modal — carried here
  // (per selected question) because forecast.workspace gates them out for speed.
  related?: ForecastRelated | null
  relevant_lessons?: ForecastDashboardLesson[]
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
  panel_runs?: ForecastQuestionPacketPanelRun[]
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
  change_my_mind?: string[]
  confidence?: null | number
  ensemble_components?: Record<string, unknown> | null
  evidence_refs?: string[]
  forecast_id?: string
  forecast_origin?: string
  // The full snapshot metadata blob. Categorical snapshots carry a `tail_audit`
  // here (probability-mass audit); older snapshots have neither, so the renderer
  // must treat both the blob and the audit as optional.
  metadata?: ForecastSnapshotMetadata | null
  method?: null | string
  probability_or_distribution?: null | number | Record<string, unknown> | string
  rationale?: string
  reasons_down?: string[]
  reasons_up?: string[]
}

export interface ForecastSnapshotMetadata {
  tail_audit?: ForecastTailAudit | null
  [key: string]: unknown
}

// The probability-mass audit for a categorical snapshot (see
// forecasting/tail_audit.py). Every field is optional so a malformed or partial
// blob degrades to an empty state rather than throwing.
export interface ForecastTailAudit {
  issues?: string[]
  null_model?: ForecastTailNullModel | null
  outcomes?: ForecastTailOutcome[]
  passes?: boolean
  residual_cap?: number
  threshold?: number
  total_mass?: number
  unearned_mass?: number
}

export type ForecastTailClassification =
  | 'edge_case'
  | 'live'
  | 'live_ish'
  | 'remote_tail'
  | 'residual'
  | 'unpriced'

export interface ForecastTailOutcome {
  classification?: ForecastTailClassification | string
  evidence_strength?: string
  has_path?: boolean
  name?: string
  note?: string
  path?: string
  probability?: number
  unearned?: boolean
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

// A raw `panel_runs` row from the exported question packet (the ledger's
// panel_run + estimates join). Source for the workspace's panel-spread
// fallback when the lighter workspace item carries no `panel`.
export interface ForecastQuestionPacketPanelRun {
  aggregate_probability?: null | number
  aggregation_method?: string
  created_at?: string
  estimates?: ForecastWorkspacePanelEstimate[]
  id?: string
  spread_summary?: Record<string, number>
  trim?: number
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

// ── ForecastBench scoreboard (read-only backtest results) ────────────────────
// Backs the desk's separate "Bench" lens via the `forecast.bench` RPC. Each row
// pairs the agent's closed-book forecast against the de-vigged market freeze price
// for a resolved ForecastBench question, with agent + market Brier; the aggregate
// is the mean agent Brier vs mean market Brier over the rows where both compute.
// This is NOT the live organic-forecast desk — it never mixes into the question list.
export interface ForecastBenchRow {
  id: string
  title?: string
  source?: null | string
  domain?: null | string
  topics?: string[]
  as_of?: null | string
  resolved_at?: null | string
  agent_probability?: null | number
  agent_probability_display?: string
  market_probability?: null | number
  market_probability_display?: string
  outcome?: null | number // 0.0 / 1.0 once resolved
  outcome_label?: null | string
  resolved?: boolean
  agent_brier?: null | number
  market_brier?: null | number
  brier_edge?: null | number // positive = agent beat the market freeze
}

export interface ForecastBenchAggregate {
  n?: number
  mean_agent_brier?: null | number
  mean_market_brier?: null | number
  mean_brier_edge?: null | number
}

export interface ForecastBenchResponse {
  product?: string
  generated_at?: string
  count?: number
  resolved_count?: number
  rows?: ForecastBenchRow[]
  aggregate?: ForecastBenchAggregate
  output?: string
}

export interface ForecastWorkspaceResponse {
  active_count?: number
  bench_count?: number
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
  aggregate_stale?: boolean
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
  aggregate_stale?: boolean
  constituents?: ForecastFactorConstituent[]
  question_ids?: string[]
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
  // Per-candidate 90% intervals for a vote-share PMF (lo=p05, hi=p95) → error bars.
  candidate_intervals?: null | Record<string, { hi: number; lo: number; mid?: number }>
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
  // The live next auto-reforecast time + cadence (desk NEXT column).
  next_review_at?: null | string
  review_cadence?: null | string
  headline_kind?: 'distribution' | 'probability'
  headline_probability?: null | number
  history?: ForecastWorkspaceHistoryPoint[]
  id?: string
  impact?: null | string
  lessons_count?: number
  method?: null | string
  open_alert_count?: number
  outcome_choices?: unknown[]
  // An in-flight auto-quorum run kicked off by this question's last commit, else
  // null — the desk summary chip polls forecast.quorum.status by this run_id.
  quorum_run?: ForecastQuorumRunRef | null
  relevant_lessons?: ForecastDashboardLesson[]
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
  // Observe-mode saturation score (0-100) recorded on the current snapshot +
  // whether it is under the alert bar — a glanceable "under-saturated" desk
  // signal (Wave 3). saturation_score is null when the snapshot was unscored.
  saturation_score?: null | number
  saturation_below_threshold?: boolean
  // Machine-readiness (the operator's hidden-parameter visibility): the active
  // watched-source count (SRC column; 0 = "no fuel") + the 0-100 composite with
  // an exact-fix gap list per missing dimension (RDY column + summary readiness
  // block). Absent on benchmark/market questions with no configurable profile.
  src_count?: number
  readiness?: ForecastReadiness | null
  scores?: ForecastWorkspaceScores | null
  snapshot_count?: number
  status?: string
  // The current snapshot's tail audit (categorical only). Optional: absent on
  // binary/distribution questions and on older snapshots; the desk shows the
  // "unearned tail" flag only when an audit is present and failing.
  tail_audit?: ForecastTailAudit | null
  title?: string
  topics?: string[]
  units?: null | string
  update_triggers?: ForecastWorkspaceTrigger[]
  // The theses this question is a weighted member of (the "member of" badge).
  thesis_ids?: ForecastThesisBadge[]
}

// ── Machine-readiness composite (forecasting/readiness_lens.py) ────────────────
// One unmet workability dimension: a stable key, a human label, and the EXACT
// operator fix (a concrete CLI command where one exists, always with "or a T task"
// as the universal fallback the operator can dispatch from the Desk).
export interface ForecastReadinessGap {
  key: string
  label: string
  fix_hint: string
}

// The 0-100 machine-readiness score + the gaps for every UNMET dimension, in
// weight order. A healthy question has an empty `gaps` list (the quiet desk).
export interface ForecastReadiness {
  score: number
  gaps: ForecastReadinessGap[]
}

// forecast.question.readiness — the single-question composite the settings modal
// fetches on open (READINESS section): the score, the active watched-source count,
// and the FULL gaps list with fix hints (plus the question id/title for display).
export interface ForecastQuestionReadinessResponse {
  question_id?: string
  title?: string
  score: number
  src_count?: number
  gaps: ForecastReadinessGap[]
}

// ── Detached Desk agent jobs (forecast.reforecast.* / forecast.desk.task) ──────
// forecast.reforecast.start / forecast.desk.task both return this immediately, then
// the caller polls forecast.reforecast.status by the run_id (the same job store —
// spec.mode distinguishes an agent re-run from a free-text task).
export interface ForecastReforecastStartResponse {
  run_id: string
  total: number
  note?: string
}

// One question's HONEST outcome inside a detached job: whether the gated commit
// landed, the resulting forecast id, an observe-mode saturation score, whether the
// commit auto-started a quorum, and any error. Nothing claims success it didn't earn.
export interface ForecastReforecastResultRow {
  question_id: string
  title?: string
  committed?: boolean
  forecast_id?: null | string
  saturation?: null | number
  quorum_autorun?: boolean | null
  error?: null | string
}

// forecast.reforecast.status — READ-ONLY progress for a detached job. `current` is
// the question+stage in flight; `results` accrues per-question outcomes; `progress`
// + `task_summary` are populated only in task mode (spec.mode === 'task').
export interface ForecastReforecastStatusResponse {
  run_id?: string
  status: 'done' | 'error' | 'queued' | 'running'
  total?: number
  done_count?: number
  current?: { question_id?: string; title?: string; stage?: string } | null
  results?: ForecastReforecastResultRow[]
  error?: null | string
  quorums_started?: number
  progress?: string[]
  task_summary?: string
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
  // Provenance for the spread section: a recorded multi-perspective panel run,
  // or ensemble components reconstructed from the current snapshot (the
  // workspace fallback when no panel run was persisted).
  kind?: 'ensemble' | 'panel'
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
  reasoning_effort_models?: string[]
  reasoning_efforts?: string[]
  slug: string
  supports_reasoning_effort?: boolean
  total_models?: number
  warning?: string
}

export interface ModelOptionsResponse {
  model?: string
  provider?: string
  providers?: ModelOptionProvider[]
  reasoning_effort?: string
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
  | { payload?: { count?: number }; session_id?: string; type: 'cron.fired' }
  | {
      // The gateway due-sweeper acting on due-ness (mirrors cron.fired). 'started'
      // carries how many reviews are due; 'done' carries the deterministic sweep's
      // result (refreshed count, opened alerts, wall time). Sessionless.
      payload:
        | { due_count?: number; phase: 'started' }
        | { alerts?: number; duration_ms?: number; phase: 'done'; refreshed?: number }
      session_id?: string
      type: 'review.sweep'
    }
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
  | {
      // A prediction-market websocket delta re-emitted by tui_gateway/pm_rpc.py
      // (one shared connection per venue). `kind` is the venue frame type
      // (book / price_change / …); `payload` is the raw delta the PM view folds
      // into the book ladders in place. `estimate` is the server-side honest YES
      // probability (canonical honest_yes_mid rule) — the ONLY price a consumer
      // may fold; null when the tick carries no estimate-grade info. Sessionless.
      payload: { estimate?: null | number; kind: string; market_id: string; payload?: Record<string, unknown>; venue: string }
      session_id?: string
      type: 'pm.tick'
    }

// ── obsidian.status (the Obsidian vault view) ───────────────────────────────
export interface ObsidianNote {
  excerpt?: string
  folder?: string
  links?: string[]
  modified?: string
  rel_path?: string
  size?: number
  title?: string
}

export interface ObsidianStatusResponse {
  count?: number
  exists?: boolean
  notes?: ObsidianNote[]
  vault?: null | string
}

export interface ObsidianNoteResponse {
  content?: string
  rel_path?: string
  size?: number
  truncated?: boolean
}

export interface ObsidianSearchResult {
  line?: number
  matched_terms?: number
  rel_path?: string
  score?: number
  snippet?: string
  title?: string
}

export interface ObsidianSearchResponse {
  count?: number
  query?: string
  results?: ObsidianSearchResult[]
}

// ── Per-forecast settings (forecast.config / forecast.config.set) ─────────────
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

export interface ForecastConfigDecision {
  action_threshold?: null | string
  decision_deadline?: null | string
  decision_owner?: null | string
  update_triggers?: unknown[]
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

// ── forecast.reviews.next (the desk review-sweep countdown + running state) ────
// READ-ONLY snapshot the Desk polls to render an honest NEXT column + a summary
// status line: the soonest DUE scheduled review, how many are due right now, the
// gateway sweeper's live state (enabled / interval / next-eligible tick / running),
// and the nightly self-check cron's next/last run. Combined with the review.sweep
// event stream to show "due · 4m" + a spinner while a sweep is in flight.
export interface ForecastReviewsNextResponse {
  due_count?: number
  next_due_at?: null | string
  nightly?: {
    installed?: boolean
    last_run_at?: null | string
    next_run_at?: null | string
  }
  sweeper?: {
    enabled?: boolean
    interval_minutes?: number
    next_tick_at?: null | string
    running?: boolean
  }
}
