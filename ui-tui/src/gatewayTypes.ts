// ── Arc A ENDGAME (A4): gatewayTypes.ts is now a THIN RE-EXPORT SHIM ──────────
// Every RPC/event wire shape is GENERATED from the `protocol/` pydantic models
// (single source of truth → ./protocol/generated.ts). This file survives ONLY
// as (1) a stable import site — the long tail of consumers keeps
// `from '../gatewayTypes.js'` working via the re-export blocks below — and
// (2) the home of the TWO irreducibly-TS-only type ALIASES that have no single
// pydantic-model form: `GatewayEvent` (a discriminated union over the generated
// `WireEvent.*` event-name literals) and `CommandDispatchResponse` (a 4-arm
// union discriminated on `type`). Both are `type` aliases, never `interface`s,
// so the A4 grep-proof (no hand-written wire-shape INTERFACE outside
// generated.ts) holds. The forecast value-enums re-export from ./types.js.
import type { WireEvent } from './protocol/generated.js'
import type { BuildInfoPayload, GatewaySkin, SubagentEventPayload } from './protocol/generated.js'
import type { SessionInfo, Usage } from './types.js'

// ── generated wire shapes — every hand-written interface mirror is DELETED; the
// one source of truth is ./protocol/generated.ts. Re-exported here so consumers
// keep one stable import site while the arc's endgame lands. ──────────────────
export type {
  // prompt / blocking-prompt acks / shell / clipboard / input / image
  ApprovalRespondResponse,
  BackgroundStartResponse,
  // voice / model / tools / reload / process / browser
  BrowserManageResponse,
  // the running application build + staleness verdict (gateway.ready / session.info)
  BuildInfoPayload,
  ClarifyRespondResponse,
  ClipboardPasteResponse,
  // commands / completion / slash
  CommandsCatalogResponse,
  CompletionResponse,
  // config / setup / theme
  ConfigDisplayConfig,
  ConfigFullResponse,
  ConfigGetValueResponse,
  ConfigMtimeResponse,
  ConfigSetResponse,
  ConfigVoiceConfig,
  // agents / delegation / subagents / spawn-tree
  DelegationPauseResponse,
  DelegationStatusResponse,
  // gateway / skin / completion / transcript
  GatewayCompletionItem,
  GatewaySkin,
  GatewayTranscriptMessage,
  ImageAttachResponse,
  InputDetectDropResponse,
  ModelOptionProvider,
  ModelOptionsResponse,
  // obsidian
  ObsidianNote,
  ObsidianNoteResponse,
  ObsidianSearchResponse,
  ObsidianSearchResult,
  ObsidianStatusResponse,
  ProcessStopResponse,
  PromptSubmitResponse,
  ReloadEnvResponse,
  ReloadMcpResponse,
  // rollback
  RollbackCheckpoint,
  RollbackDiffResponse,
  RollbackListResponse,
  RollbackRestoreResponse,
  SecretRespondResponse,
  // session lifecycle
  SessionBranchResponse,
  SessionCloseResponse,
  SessionCompressResponse,
  SessionCreateResponse,
  SessionDeleteResponse,
  SessionInterruptResponse,
  SessionListItem,
  SessionListResponse,
  SessionMostRecentResponse,
  SessionResumeResponse,
  SessionSaveResponse,
  SessionStatusResponse,
  SessionSteerResponse,
  SessionTitleResponse,
  SessionUndoResponse,
  SessionUsageResponse,
  SetupStatusResponse,
  ShellExecResponse,
  SlashExecResponse,
  SpawnTreeListEntry,
  SpawnTreeListResponse,
  SpawnTreeLoadResponse,
  SubagentEventPayload,
  SubagentInterruptResponse,
  SudoRespondResponse,
  TerminalResizeResponse,
  ThemeListResponse,
  ThemeOption,
  ToolsConfigureResponse,
  VoiceRecordResponse,
  VoiceToggleResponse
} from './protocol/generated.js'

// ── Arc A3: forecast.* / forecast.warnings.* wire shapes are GENERATED ─────────
// The hand-written mirrors were deleted; these types now have ONE source of truth
// (protocol/ pydantic models → protocol/generated.ts). Re-exported here so the
// long tail of consumers keeps a stable import site.
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
  ForecastCohortScoreboard,
  ForecastCommandResponse,
  ForecastConfigDecision,
  ForecastConfigGate,
  ForecastConfigResponse,
  ForecastConfigThreshold,
  ForecastContinuousScorecard,
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
  ForecastPooledDiagnostic,
  ForecastQuarantineSummary,
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
  ForecastWorkspaceTrigger
} from './protocol/generated.js'

// ── TS-ONLY ALIAS #1: command.dispatch's 4-arm discriminated union ────────────
// No single pydantic-model form (the arms carry disjoint keys keyed on `type`);
// stays hand-written as a `type` alias.
export type CommandDispatchResponse =
  | { output?: string; type: 'exec' | 'plugin' }
  | { target: string; type: 'alias' }
  | { message?: string; name: string; type: 'skill' }
  | { message: string; notice?: string; type: 'send' }

// The automode job events keep their legacy TUI names, aliased onto the generated
// jobs-runtime payloads (protocol/events/warnings.py).
export type {
  AutomodeCompletePayload as ForecastWarningsAutomodeComplete,
  AutomodeErrorPayload as ForecastWarningsAutomodeError,
  AutomodeProgressPayload as ForecastWarningsAutomodeProgress
} from './protocol/generated.js'
// ── the forecast-desk value enums (moved to types.ts; re-exported here so the
// historical `from '../gatewayTypes.js'` import sites keep resolving) ─────────
export type { ForecastTailClassification, ForecastTriageLabel } from './types.js'

// ── TS-ONLY ALIAS #2: the GatewayEvent discriminated union ────────────────────
// One union over EVERY server→client event, discriminated on the generated
// `WireEvent.*` name literals. Cannot be a single pydantic model (each arm has
// its own payload); the payloads reference generated shapes (GatewaySkin,
// SubagentEventPayload, SessionInfo, Usage) where they are non-trivial.
export type GatewayEvent =
  | {
      payload?: { build?: BuildInfoPayload; protocol_version?: number; skin?: GatewaySkin }
      session_id?: string
      type: typeof WireEvent.GATEWAY_READY
    }
  | { payload?: GatewaySkin; session_id?: string; type: typeof WireEvent.SKIN_CHANGED }
  | { payload: SessionInfo; session_id?: string; type: typeof WireEvent.SESSION_INFO }
  | { payload?: { text?: string }; session_id?: string; type: typeof WireEvent.THINKING_DELTA }
  | { payload?: undefined; session_id?: string; type: typeof WireEvent.MESSAGE_START }
  | { payload?: { kind?: string; text?: string }; session_id?: string; type: typeof WireEvent.STATUS_UPDATE }
  | {
      payload?: { state?: 'idle' | 'listening' | 'transcribing' }
      session_id?: string
      type: typeof WireEvent.VOICE_STATUS
    }
  | {
      payload?: { no_speech_limit?: boolean; text?: string }
      session_id?: string
      type: typeof WireEvent.VOICE_TRANSCRIPT
    }
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
  | {
      payload?: { text?: string }
      session_id?: string
      type: typeof WireEvent.REASONING_DELTA | typeof WireEvent.REASONING_AVAILABLE
    }
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
        // Cumulative session usage as of tool-complete time — folded into the
        // usage store just like message.complete, so the liveness counter's
        // reported delta climbs mid-turn (once per tool call) instead of only
        // landing at end-of-turn.
        usage?: Usage
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
  | {
      payload: { env_var: string; prompt: string; request_id: string }
      session_id?: string
      type: typeof WireEvent.SECRET_REQUEST
    }
  | { payload: { task_id: string; text: string }; session_id?: string; type: typeof WireEvent.BACKGROUND_COMPLETE }
  | { payload?: { text?: string }; session_id?: string; type: typeof WireEvent.REVIEW_SUMMARY }
  | { payload?: { count?: number }; session_id?: string; type: typeof WireEvent.CRON_FIRED }
  | {
      // The gateway due-sweeper acting on due-ness (mirrors cron.fired). 'started'
      // carries how many reviews are due; 'done' carries the deterministic sweep's
      // result (proposal count, opened alerts, wall time). Sessionless.
      payload:
        | { due_count?: number; phase: 'started' }
        | { alerts?: number; duration_ms?: number; phase: 'done'; proposals?: number }
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
      payload?: {
        reasoning?: string
        rendered?: string
        text?: string
        usage?: Usage
        status?: string
        durable_status?: string
        turn_id?: string
      }
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
      payload: {
        estimate?: null | number
        kind: string
        market_id: string
        payload?: Record<string, unknown>
        venue: string
      }
      session_id?: string
      type: typeof WireEvent.PM_TICK
    }
