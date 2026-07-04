import { WireEvent } from './protocol/generated.js'
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

// ── Warning-resolution RPCs (forecast.warnings.*) ────────────────────────────
// The TUI Warnings overlay drives the same gated dispatcher the CLI/cron use:
// resolve ONE alert, or run an interruptible AUTOMODE sweep that streams progress.

// forecast.warnings.aggregate — the FULL open backlog folded into the 4 operator
// action tiers with per-tier + per-reason totals. Counts are server-side
// UNTRUNCATED (no limit); the headline must reflect the whole backlog.
//   free   — non-LLM gated close-outs (bookkeeping / score / postmortem / material)
//   agent  — REFORECAST (the opt-in LLM pass; folds the evidence-collection reasons)
//   manual — NO_AUTO (needs a human; never auto-resolved)
// The agent tier additionally carries a `stale` sub-bucket: the elapsed-time
// -staleness subset of its reforecast reasons (evidence_stale / last_update /
// close_time_within). Those reasons are STILL counted in the agent total — `stale`
// is a view over the tier, not a fourth tier.
// One alert's resolution outcome (mirrors forecasting.warnings._result):
// status ∈ resolved | surfaced | failed | skipped; acked ONLY on real work.
// forecast.warnings.dismiss — a RECORDED human silence (note + actor REQUIRED), NOT
// a resolution: it bulk-sets acknowledged_at on the selected open group without
// running any runner or moving any forecast. `matched` is the open group it
// selected; `count` is how many it actually silenced (re-surfaces after ttl_days).
// Streamed automode lifecycle (gw.on('forecast.warnings.automode.*')).
// ── forecast.calibration (the native calibration view) ──────────────────────

// One decile of the reliability curve: predicted vs observed frequency for
// binary forecasts whose P(yes) fell in `bucket`.
// The signed calibration-bias report (forecasting/calibration_bias.py
// CalibrationBiasReport.to_payload). `status` is the measurement verdict;
// insufficient_evidence is a real state, not an error.
// One recency window of the rolling calibration trend (ledger._calibration_trend).
// Rolling mean-Brier + signed-error over recency windows + a coarse direction.
// The full unsigned summary (forecasting/ledger.py calibration_summary).
// A calibration lesson CORRECTING forecasts in scope + its measured coverage
// (forecasting/ledger.py calibration_correcting_lessons). `dormant` ⇒ never yet
// encountered at a commit (the recommended adjustment isn't biting yet).
// A compact per-scope breakdown row (headline metrics only, no curve).
// ── forecast.triage.contested / .relabel (the contested-triage lens) ─────────

// One CONTESTED triage staging row awaiting an operator hand-label.
export type ForecastTriageLabel = 'irrelevant' | 'relevant_interesting' | 'relevant_uninteresting'

// ── forecast.schedule.status (schedule health) ───────────────────────────────

// ── forecast.quorum.status (the running-quorum chip) ─────────────────────────

// An in-flight auto-quorum reference attached to a desk forecast row.
// A time-indexed analyst write-up ("desk note"): the model's prose read on a
// forecast. `brief` is written on every update, `retrospective` once it resolves.
// One related forecast's world-view, surfaced for cross-pollination on the desk.
// The probability-mass audit for a categorical snapshot (see
// forecasting/tail_audit.py). Every field is optional so a malformed or partial
// blob degrades to an empty state rather than throwing.
export type ForecastTailClassification =
  | 'edge_case'
  | 'live'
  | 'live_ish'
  | 'remote_tail'
  | 'residual'
  | 'unpriced'

// A raw `panel_runs` row from the exported question packet (the ledger's
// panel_run + estimates join). Source for the workspace's panel-spread
// fallback when the lighter workspace item carries no `panel`.
// ── ForecastBench scoreboard (read-only backtest results) ────────────────────
// Backs the desk's separate "Bench" lens via the `forecast.bench` RPC. Each row
// pairs the agent's closed-book forecast against the de-vigged market freeze price
// for a resolved ForecastBench question, with agent + market Brier; the aggregate
// is the mean agent Brier vs mean market Brier over the rows where both compute.
// This is NOT the live organic-forecast desk — it never mixes into the question list.
// ── Thesis layer ─────────────────────────────────────────────────────────────
// A thesis aggregates the weighted beliefs of its member forecasts into a
// rolling macro health probability + a 0-100 score (see forecasting/thesis.py).
// These shapes mirror the web terminal's forecastTypes.ts field-for-field.

// Per-entity (stock / candidate / currency / sector …) suitability: the same
// 0..1 weighted aggregate as the thesis, computed over the entity's own signal
// vector. The §22 per-name read ("BE/IREN/CORZ better suited when the
// power-bottleneck rises"). A withheld suitability stays null — never faked.
// A §10 trade trigger: a member signal moved → entities better / less suited.
// ── Factor layer ─────────────────────────────────────────────────────────────
// A factor is a weighted basket whose RETURN distribution + volatility +
// downside is the portfolio aggregate of its constituents' return
// distributions. Mirrors the thesis shapes but in return/volatility units
// rather than a health probability. Withheld moments stay null — never faked.

// ── Machine-readiness composite (forecasting/readiness_lens.py) ────────────────
// One unmet workability dimension: a stable key, a human label, and the EXACT
// operator fix (a concrete CLI command where one exists, always with "or a T task"
// as the universal fallback the operator can dispatch from the Desk).
// The 0-100 machine-readiness score + the gaps for every UNMET dimension, in
// weight order. A healthy question has an empty `gaps` list (the quiet desk).
// forecast.question.readiness — the single-question composite the settings modal
// fetches on open (READINESS section): the score, the active watched-source count,
// and the FULL gaps list with fix hints (plus the question id/title for display).
// ── Detached Desk agent jobs (forecast.reforecast.* / forecast.desk.task) ──────
// forecast.reforecast.start / forecast.desk.task both return this immediately, then
// the caller polls forecast.reforecast.status by the run_id (the same job store —
// spec.mode distinguishes an agent re-run from a free-text task).
// One question's HONEST outcome inside a detached job: whether the gated commit
// landed, the resulting forecast id, an observe-mode saturation score, whether the
// commit auto-started a quorum, and any error. Nothing claims success it didn't earn.
// forecast.reforecast.status — READ-ONLY progress for a detached job. `current` is
// the question+stage in flight; `results` accrues per-question outcomes; `progress`
// + `task_summary` are populated only in task mode (spec.mode === 'task').
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
  | { payload?: { skin?: GatewaySkin }; session_id?: string; type: typeof WireEvent.GATEWAY_READY }
  | { payload?: GatewaySkin; session_id?: string; type: typeof WireEvent.SKIN_CHANGED }
  | { payload: SessionInfo; session_id?: string; type: typeof WireEvent.SESSION_INFO }
  | { payload?: { text?: string }; session_id?: string; type: typeof WireEvent.THINKING_DELTA }
  | { payload?: undefined; session_id?: string; type: typeof WireEvent.MESSAGE_START }
  | { payload?: { kind?: string; text?: string }; session_id?: string; type: typeof WireEvent.STATUS_UPDATE }
  | { payload?: { state?: 'idle' | 'listening' | 'transcribing' }; session_id?: string; type: typeof WireEvent.VOICE_STATUS }
  | { payload?: { no_speech_limit?: boolean; text?: string }; session_id?: string; type: typeof WireEvent.VOICE_TRANSCRIPT }
  | { payload: { line: string }; session_id?: string; type: typeof WireEvent.GATEWAY_STDERR }
  | {
      payload?: { level?: 'error' | 'info' | 'warn'; message?: string }
      session_id?: string
      type: typeof WireEvent.BROWSER_PROGRESS
    }
  | {
      payload?: { cwd?: string; python?: string; stderr_tail?: string }
      session_id?: string
      type: typeof WireEvent.GATEWAY_START_TIMEOUT
    }
  | { payload?: { preview?: string }; session_id?: string; type: typeof WireEvent.GATEWAY_PROTOCOL_ERROR }
  | { payload?: { text?: string }; session_id?: string; type: typeof WireEvent.REASONING_DELTA | typeof WireEvent.REASONING_AVAILABLE }
  | { payload: { name?: string; preview?: string }; session_id?: string; type: typeof WireEvent.TOOL_PROGRESS }
  | { payload: { name?: string }; session_id?: string; type: typeof WireEvent.TOOL_GENERATING }
  | {
      payload: { context?: string; name?: string; tool_id: string; todos?: unknown[] }
      session_id?: string
      type: typeof WireEvent.TOOL_START
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
      type: typeof WireEvent.TOOL_COMPLETE
    }
  | {
      payload: { choices: string[] | null; question: string; request_id: string }
      session_id?: string
      type: typeof WireEvent.CLARIFY_REQUEST
    }
  | { payload: { command: string; description: string }; session_id?: string; type: typeof WireEvent.APPROVAL_REQUEST }
  | { payload: { request_id: string }; session_id?: string; type: typeof WireEvent.SUDO_REQUEST }
  | { payload: { env_var: string; prompt: string; request_id: string }; session_id?: string; type: typeof WireEvent.SECRET_REQUEST }
  | { payload: { task_id: string; text: string }; session_id?: string; type: typeof WireEvent.BACKGROUND_COMPLETE }
  | { payload?: { text?: string }; session_id?: string; type: typeof WireEvent.REVIEW_SUMMARY }
  | { payload?: { count?: number }; session_id?: string; type: typeof WireEvent.CRON_FIRED }
  | {
      // The gateway due-sweeper acting on due-ness (mirrors cron.fired). 'started'
      // carries how many reviews are due; 'done' carries the deterministic sweep's
      // result (refreshed count, opened alerts, wall time). Sessionless.
      payload:
        | { due_count?: number; phase: 'started' }
        | { alerts?: number; duration_ms?: number; phase: 'done'; refreshed?: number }
      session_id?: string
      type: typeof WireEvent.REVIEW_SWEEP
    }
  | { payload: SubagentEventPayload; session_id?: string; type: typeof WireEvent.SUBAGENT_SPAWN_REQUESTED }
  | { payload: SubagentEventPayload; session_id?: string; type: typeof WireEvent.SUBAGENT_START }
  | { payload: SubagentEventPayload; session_id?: string; type: typeof WireEvent.SUBAGENT_THINKING }
  | { payload: SubagentEventPayload; session_id?: string; type: typeof WireEvent.SUBAGENT_TOOL }
  | { payload: SubagentEventPayload; session_id?: string; type: typeof WireEvent.SUBAGENT_PROGRESS }
  | { payload: SubagentEventPayload; session_id?: string; type: typeof WireEvent.SUBAGENT_COMPLETE }
  | { payload: { rendered?: string; text?: string }; session_id?: string; type: typeof WireEvent.MESSAGE_DELTA }
  | {
      payload?: { reasoning?: string; rendered?: string; text?: string; usage?: Usage }
      session_id?: string
      type: typeof WireEvent.MESSAGE_COMPLETE
    }
  | { payload?: { message?: string }; session_id?: string; type: typeof WireEvent.ERROR }
  | {
      // A prediction-market websocket delta re-emitted by tui_gateway/pm_rpc.py
      // (one shared connection per venue). `kind` is the venue frame type
      // (book / price_change / …); `payload` is the raw delta the PM view folds
      // into the book ladders in place. `estimate` is the server-side honest YES
      // probability (canonical honest_yes_mid rule) — the ONLY price a consumer
      // may fold; null when the tick carries no estimate-grade info. Sessionless.
      payload: { estimate?: null | number; kind: string; market_id: string; payload?: Record<string, unknown>; venue: string }
      session_id?: string
      type: typeof WireEvent.PM_TICK
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
// ── forecast.reviews.next (the desk review-sweep countdown + running state) ────
// READ-ONLY snapshot the Desk polls to render an honest NEXT column + a summary
// status line: the soonest DUE scheduled review, how many are due right now, the
// gateway sweeper's live state (enabled / interval / next-eligible tick / running),
// and the nightly self-check cron's next/last run. Combined with the review.sweep
// event stream to show "due · 4m" + a spinner while a sweep is in flight.

// ── Arc A3: forecast.* / forecast.warnings.* wire shapes are GENERATED ─────────
// The hand-written mirrors were deleted; these types now have ONE source of truth
// (protocol/ pydantic models → protocol/generated.ts). Re-exported here so the
// long tail of consumers keeps a stable import site while A4 finishes the carve.
export type {
  ForecastAnalystNote,
  ForecastBenchAggregate,
  ForecastBenchResponse,
  ForecastBenchRow,
  ForecastCalibrationBias,
  ForecastCalibrationBreakdownRow,
  ForecastCalibrationBucketRow,
  ForecastCalibrationCurveRow,
  ForecastCalibrationLesson,
  ForecastCalibrationLessonCoverage,
  ForecastCalibrationResponse,
  ForecastCalibrationSummary,
  ForecastCalibrationTrend,
  ForecastCalibrationTrendWindow,
  ForecastCommandResponse,
  ForecastConfigDecision,
  ForecastConfigGate,
  ForecastConfigResponse,
  ForecastConfigThreshold,
  ForecastDashboardAlert,
  ForecastDashboardBacktest,
  ForecastDashboardCalibration,
  ForecastDashboardCalibrationComponent,
  ForecastDashboardClaimStatus,
  ForecastDashboardDoctor,
  ForecastDashboardErrorProfile,
  ForecastDashboardEvidenceStatus,
  ForecastDashboardFactor,
  ForecastDashboardLearning,
  ForecastDashboardLesson,
  ForecastDashboardLiveBaseline,
  ForecastDashboardLivePerformance,
  ForecastDashboardQuestion,
  ForecastDashboardQuestionTypeCalibration,
  ForecastDashboardResponse,
  ForecastDashboardReview,
  ForecastDashboardScheduleRun,
  ForecastDashboardSummary,
  ForecastDashboardThesis,
  ForecastFactor,
  ForecastFactorConstituent,
  ForecastFactorHistoryPoint,
  ForecastQuestionPacket,
  ForecastQuestionPacketAssumption,
  ForecastQuestionPacketEvidence,
  ForecastQuestionPacketPanelRun,
  ForecastQuestionPacketQuestion,
  ForecastQuestionPacketReferenceClass,
  ForecastQuestionPacketResponse,
  ForecastQuestionPacketSnapshot,
  ForecastQuestionReadinessResponse,
  ForecastQuorumRunRef,
  ForecastQuorumStatusResponse,
  ForecastQuorumStatusResult,
  ForecastReadiness,
  ForecastReadinessGap,
  ForecastReforecastResultRow,
  ForecastReforecastStartResponse,
  ForecastReforecastStatusResponse,
  ForecastRelated,
  ForecastRelatedView,
  ForecastReviewsNextResponse,
  ForecastScheduleCronHealth,
  ForecastScheduleCronJob,
  ForecastScheduleReviewRow,
  ForecastScheduleStatusResponse,
  ForecastSharedSource,
  ForecastSnapshotMetadata,
  ForecastTailAudit,
  ForecastTailNullModel,
  ForecastTailOutcome,
  ForecastThesis,
  ForecastThesisBadge,
  ForecastThesisComponent,
  ForecastThesisEntity,
  ForecastThesisHistoryPoint,
  ForecastThesisTrigger,
  ForecastTriageContestedResponse,
  ForecastTriageContestedRow,
  ForecastTriageRelabelResponse,
  ForecastWarningDismissedItem,
  ForecastWarningGroup,
  ForecastWarningResolveResult,
  ForecastWarningsAgentTier,
  ForecastWarningsAggregateResponse,
  ForecastWarningsAutomodeRunResponse,
  ForecastWarningsDismissResponse,
  ForecastWarningsHeadline,
  ForecastWarningsListResponse,
  ForecastWarningsResolveResponse,
  ForecastWarningsTier,
  ForecastWorkspaceDistribution,
  ForecastWorkspaceEvidence,
  ForecastWorkspaceHistoryPoint,
  ForecastWorkspaceItem,
  ForecastWorkspacePanel,
  ForecastWorkspacePanelEstimate,
  ForecastWorkspaceResolution,
  ForecastWorkspaceResponse,
  ForecastWorkspaceScores,
  ForecastWorkspaceTrigger,
} from './protocol/generated.js'
// The automode job events keep their legacy TUI names, aliased onto the generated
// jobs-runtime payloads (protocol/events/warnings.py).
export type {
  AutomodeProgressPayload as ForecastWarningsAutomodeProgress,
  AutomodeCompletePayload as ForecastWarningsAutomodeComplete,
  AutomodeErrorPayload as ForecastWarningsAutomodeError,
} from './protocol/generated.js'

