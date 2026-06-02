/**
 * Forecast workspace data shapes for the web terminal.
 *
 * These are a STANDALONE COPY of the relevant gateway types from the ui-tui
 * package (ui-tui/src/gatewayTypes.ts). The web terminal owns its own copy and
 * must NOT depend on the ui-tui package — keep these in sync by hand when the
 * wire contract changes.
 *
 * Only the subset the render/format helpers in forecastFormat.ts actually need
 * is reproduced here, plus the closure types those reference.
 */

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

export interface ForecastWorkspacePanelEstimate {
  confidence_high?: null | number
  confidence_low?: null | number
  crux?: null | string
  perspective?: string
  probability?: null | number
  trimmed?: boolean
  weight?: null | number
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

// ── Thesis layer ─────────────────────────────────────────────────────────────
// A thesis aggregates the weighted beliefs of its member forecasts into a
// rolling macro health probability + a 0-100 score (see forecasting/thesis.py).

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

// Per-entity (stock / candidate / currency / sector ...) suitability: the same
// 0..1 weighted aggregate as the thesis, over the entity's own signal vector.
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

// A §10 trade trigger: a member signal moved -> entities better/less suited.
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
}

export interface ForecastWorkspaceResponse {
  active_count?: number
  closing_soon_count?: number
  forecasts?: ForecastWorkspaceItem[]
  generated_at?: string
  open_alert_count?: number
  output?: string
  product?: string
  thesis_count?: number
  theses?: ForecastThesis[]
}
