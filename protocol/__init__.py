"""Protocol-first gateway contract: one source of truth for every RPC and event
crossing the gateway wire, with TypeScript types generated from it.

The registry below drives both the server-side ``@rpc-model`` validation
(``tui_gateway/pm_rpc.py``) and the TypeScript codegen (``protocol.codegen`` →
``ui-tui/src/protocol/generated.ts``). Drift between the two becomes a build
error (the staleness gate) instead of a runtime mystery.
"""

from __future__ import annotations

from dataclasses import dataclass

from protocol.events import commands as _events_commands
from protocol.events import desk as _events_desk
from protocol.events import gateway as _events_gateway
from protocol.events import jobs as _events_jobs
from protocol.events import markets as _events_markets
from protocol.events import pm as _events_pm
from protocol.events import prompts as _events_prompts
from protocol.events import subagents as _events_subagents
from protocol.events import tools as _events_tools
from protocol.events import turn as _events_turn
from protocol.events import voice as _events_voice
from protocol.events import warnings as _events_warnings
from protocol.rpc import agents as _rpc_agents
from protocol.rpc import commands as _rpc_commands
from protocol.rpc import config as _rpc_config
from protocol.rpc import forecast as _rpc_forecast
from protocol.rpc import interact as _rpc_interact
from protocol.rpc import host as _rpc_host
from protocol.rpc import jobs as _rpc_jobs
from protocol.rpc import markets as _rpc_markets
from protocol.rpc import model as _rpc_model
from protocol.rpc import obsidian as _rpc_obsidian
from protocol.rpc import pm as _rpc_pm
from protocol.rpc import rollback as _rpc_rollback
from protocol.rpc import session as _rpc_session
from protocol.rpc import theme as _rpc_theme
from protocol.rpc import voice as _rpc_voice
from protocol.rpc import warnings as _rpc_warnings
from protocol import collab as _collab
from protocol.types import WireModel
from protocol.version import MIN_SUPPORTED, PROTOCOL_VERSION


@dataclass(frozen=True)
class RpcSpec:
    """One registered RPC: its method name and its request/response models.

    ``exclude_none`` drops ``None``-valued keys when serialising the response —
    used for the venue models that emit conditional keys (``StreamStart`` omits
    an empty ``subscribed``; ``PMStreamHub.stop`` emits one of
    ``closed``/``remaining``). Everything else keeps ``null`` on the wire.
    """

    method: str
    request: type[WireModel]
    response: type[WireModel]
    exclude_none: bool = False


@dataclass(frozen=True)
class EventSpec:
    """One registered sessionless event: its wire name and payload model."""

    name: str
    model: type[WireModel]


RPC_SPECS: list[RpcSpec] = [
    RpcSpec("host.negotiate", _rpc_host.HostNegotiateRequest, _rpc_host.HostNegotiateResponse),
    RpcSpec("pm.list", _rpc_pm.PmListRequest, _rpc_pm.PmListResponse),
    RpcSpec("pm.detail", _rpc_pm.PmDetailRequest, _rpc_pm.PmDetailResponse),
    RpcSpec("pm.book", _rpc_pm.PmBookRequest, _rpc_pm.PmBookResponse),
    RpcSpec("pm.history", _rpc_pm.PmHistoryRequest, _rpc_pm.PmHistoryResponse),
    RpcSpec(
        "pm.stream.start",
        _rpc_pm.PmStreamStartRequest,
        _rpc_pm.PmStreamStartResponse,
        exclude_none=True,
    ),
    RpcSpec(
        "pm.stream.stop",
        _rpc_pm.PmStreamStopRequest,
        _rpc_pm.PmStreamStopResponse,
        exclude_none=True,
    ),
    # ── jobs.* — the detached-job runtime (Arc B) ────────────────────────────
    RpcSpec("jobs.start", _rpc_jobs.JobsStartRequest, _rpc_jobs.JobsStartResponse),
    RpcSpec("jobs.status", _rpc_jobs.JobsStatusRequest, _rpc_jobs.JobsStatusResponse),
    RpcSpec("jobs.active", _rpc_jobs.JobsActiveRequest, _rpc_jobs.JobsActiveResponse),
    RpcSpec("jobs.cancel", _rpc_jobs.JobsCancelRequest, _rpc_jobs.JobsCancelResponse),
    # ── market.* — the server-side data plane (Arc C) ────────────────────────
    RpcSpec(
        "market.quotes",
        _rpc_markets.MarketQuotesRequest,
        _rpc_markets.MarketQuotesResponse,
    ),
    RpcSpec(
        "market.search",
        _rpc_markets.MarketSearchRequest,
        _rpc_markets.MarketSearchResponse,
    ),
    # ── forecast.* — the forecast-desk family (Arc A3), the biggest ──────────
    # Wrapped in tui_gateway/server.py with VALIDATE-ONLY semantics (the wrapper
    # logs drift and returns the original result untouched — the big partial
    # payloads never re-serialise, so the wire can never regress).
    RpcSpec("forecast.dashboard", _rpc_forecast.ForecastDashboardRequest, _rpc_forecast.ForecastDashboardResponse),
    RpcSpec("forecast.workspace", _rpc_forecast.ForecastWorkspaceRequest, _rpc_forecast.ForecastWorkspaceResponse),
    RpcSpec("forecast.theses", _rpc_forecast.ForecastThesesRequest, _rpc_forecast.ForecastThesesResponse),
    RpcSpec("forecast.bench", _rpc_forecast.ForecastBenchRequest, _rpc_forecast.ForecastBenchResponse),
    RpcSpec("forecast.quorum.status", _rpc_forecast.ForecastQuorumStatusRequest, _rpc_forecast.ForecastQuorumStatusResponse),
    RpcSpec("forecast.question.readiness", _rpc_forecast.ForecastQuestionReadinessRequest, _rpc_forecast.ForecastQuestionReadinessResponse),
    RpcSpec("forecast.triage.contested", _rpc_forecast.ForecastTriageContestedRequest, _rpc_forecast.ForecastTriageContestedResponse),
    RpcSpec("forecast.triage.relabel", _rpc_forecast.ForecastTriageRelabelRequest, _rpc_forecast.ForecastTriageRelabelResponse),
    RpcSpec("forecast.schedule.status", _rpc_forecast.ForecastScheduleStatusRequest, _rpc_forecast.ForecastScheduleStatusResponse),
    RpcSpec("forecast.reviews.next", _rpc_forecast.ForecastReviewsNextRequest, _rpc_forecast.ForecastReviewsNextResponse),
    RpcSpec("forecast.calibration", _rpc_forecast.ForecastCalibrationRequest, _rpc_forecast.ForecastCalibrationResponse),
    RpcSpec("forecast.operation", _rpc_forecast.ForecastOperationRequest, _rpc_forecast.ForecastOperationResponse),
    RpcSpec("forecast.review", _rpc_forecast.ForecastReviewRequest, _rpc_forecast.ForecastReviewResponse),
    RpcSpec("forecast.resolve", _rpc_forecast.ForecastResolveRequest, _rpc_forecast.ForecastResolveResponse),
    RpcSpec("forecast.command", _rpc_forecast.ForecastCommandRequest, _rpc_forecast.ForecastCommandResponse),
    RpcSpec("forecast.reforecast", _rpc_forecast.ForecastReforecastRequest, _rpc_forecast.ForecastReforecastMarkResponse),
    RpcSpec("forecast.config", _rpc_forecast.ForecastConfigRequest, _rpc_forecast.ForecastConfigResponse),
    RpcSpec("forecast.config.set", _rpc_forecast.ForecastConfigSetRequest, _rpc_forecast.ForecastConfigResponse),
    RpcSpec("forecast.question", _rpc_forecast.ForecastQuestionRequest, _rpc_forecast.ForecastQuestionPacketResponse),
    RpcSpec("forecast.onboard_propose", _rpc_forecast.ForecastOnboardProposeRequest, _rpc_forecast.ForecastOnboardProposeResponse),
    RpcSpec("forecast.onboard_commit", _rpc_forecast.ForecastOnboardCommitRequest, _rpc_forecast.ForecastOnboardCommitResponse),
    RpcSpec("forecast.hooks", _rpc_forecast.ForecastHooksRequest, _rpc_forecast.ForecastHooksResponse),
    RpcSpec("forecast.hooks.set", _rpc_forecast.ForecastHooksSetRequest, _rpc_forecast.ForecastHooksSetResponse),
    RpcSpec("forecast.hooks.save_rule", _rpc_forecast.ForecastHooksSaveRuleRequest, _rpc_forecast.ForecastHooksSaveRuleResponse),
    RpcSpec("forecast.hooks.remove_rule", _rpc_forecast.ForecastHooksRemoveRuleRequest, _rpc_forecast.ForecastHooksRemoveRuleResponse),
    RpcSpec("forecast.hooks.preview", _rpc_forecast.ForecastHooksPreviewRequest, _rpc_forecast.ForecastHooksPreviewResponse),
    # ── forecast.warnings.* ──────────────────────────────────────────────────
    RpcSpec("forecast.warnings.list", _rpc_warnings.ForecastWarningsListRequest, _rpc_warnings.ForecastWarningsListResponse),
    RpcSpec("forecast.warnings.aggregate", _rpc_warnings.ForecastWarningsAggregateRequest, _rpc_warnings.ForecastWarningsAggregateResponse),
    RpcSpec("forecast.warnings.resolve", _rpc_warnings.ForecastWarningsResolveRequest, _rpc_warnings.ForecastWarningsResolveResponse),
    RpcSpec("forecast.warnings.dismiss", _rpc_warnings.ForecastWarningsDismissRequest, _rpc_warnings.ForecastWarningsDismissResponse),
    # ── Arc-B ALIASES: handlers live in jobs_rpc.py (NOT wrapped here) — typed
    # + registered only so the desk/alerts views reference generated types. ───
    RpcSpec("forecast.warnings.automode.run", _rpc_warnings.ForecastWarningsAutomodeRunRequest, _rpc_warnings.ForecastWarningsAutomodeRunResponse),
    RpcSpec("forecast.reforecast.start", _rpc_forecast.ForecastReforecastStartRequest, _rpc_forecast.ForecastReforecastStartResponse),
    RpcSpec("forecast.reforecast.status", _rpc_forecast.ForecastReforecastStatusRequest, _rpc_forecast.ForecastReforecastStatusResponse),
    RpcSpec("forecast.reforecast.active", _rpc_forecast.ForecastReforecastActiveRequest, _rpc_forecast.ForecastReforecastActiveResponse),
    RpcSpec("forecast.desk.task", _rpc_forecast.ForecastDeskTaskRequest, _rpc_forecast.ForecastReforecastStartResponse),
    # ── ARC A4 — the arc closer: session / config / agents / everything left ──
    # ── session.* — the session lifecycle family ─────────────────────────────
    RpcSpec("session.create", _rpc_session.SessionCreateRequest, _rpc_session.SessionCreateResponse),
    RpcSpec("session.resume", _rpc_session.SessionResumeRequest, _rpc_session.SessionResumeResponse),
    RpcSpec("session.list", _rpc_session.SessionListRequest, _rpc_session.SessionListResponse),
    RpcSpec("session.delete", _rpc_session.SessionDeleteRequest, _rpc_session.SessionDeleteResponse),
    RpcSpec("session.most_recent", _rpc_session.SessionMostRecentRequest, _rpc_session.SessionMostRecentResponse),
    RpcSpec("session.title", _rpc_session.SessionTitleRequest, _rpc_session.SessionTitleResponse),
    RpcSpec("session.save", _rpc_session.SessionSaveRequest, _rpc_session.SessionSaveResponse),
    RpcSpec("session.undo", _rpc_session.SessionUndoRequest, _rpc_session.SessionUndoResponse),
    RpcSpec("session.usage", _rpc_session.SessionUsageRequest, _rpc_session.SessionUsageResponse),
    RpcSpec("session.status", _rpc_session.SessionStatusRequest, _rpc_session.SessionStatusResponse),
    RpcSpec("session.compress", _rpc_session.SessionCompressRequest, _rpc_session.SessionCompressResponse),
    RpcSpec("session.branch", _rpc_session.SessionBranchRequest, _rpc_session.SessionBranchResponse),
    RpcSpec("session.branch_replace", _rpc_session.SessionBranchRequest, _rpc_session.SessionBranchResponse),
    RpcSpec("session.close", _rpc_session.SessionCloseRequest, _rpc_session.SessionCloseResponse),
    RpcSpec("session.interrupt", _rpc_session.SessionInterruptRequest, _rpc_session.SessionInterruptResponse),
    RpcSpec("session.steer", _rpc_session.SessionSteerRequest, _rpc_session.SessionSteerResponse),
    RpcSpec("session.history", _rpc_session.SessionHistoryRequest, _rpc_session.SessionHistoryResponse),
    # ── config.* + setup.status ──────────────────────────────────────────────
    # config.get is POLYMORPHIC (its shape depends on the `key` param) so it is
    # registered for TS types only (handler stays @method, unwrapped); its two
    # alternate shapes ride EXTRA_MODELS below.
    RpcSpec("config.get", _rpc_config.ConfigGetValueRequest, _rpc_config.ConfigFullResponse),
    RpcSpec("config.set", _rpc_config.ConfigSetRequest, _rpc_config.ConfigSetResponse),
    RpcSpec("setup.status", _rpc_config.SetupStatusRequest, _rpc_config.SetupStatusResponse),
    # ── theme / model / voice ────────────────────────────────────────────────
    RpcSpec("theme.list", _rpc_theme.ThemeListRequest, _rpc_theme.ThemeListResponse),
    RpcSpec("model.options", _rpc_model.ModelOptionsRequest, _rpc_model.ModelOptionsResponse),
    RpcSpec("voice.toggle", _rpc_voice.VoiceToggleRequest, _rpc_voice.VoiceToggleResponse),
    RpcSpec("voice.record", _rpc_voice.VoiceRecordRequest, _rpc_voice.VoiceRecordResponse),
    RpcSpec("voice.stop", _rpc_voice.VoiceRecordRequest, _rpc_voice.VoiceRecordResponse),
    # ── obsidian.* ───────────────────────────────────────────────────────────
    RpcSpec("obsidian.status", _rpc_obsidian.ObsidianStatusRequest, _rpc_obsidian.ObsidianStatusResponse),
    RpcSpec("obsidian.note", _rpc_obsidian.ObsidianNoteRequest, _rpc_obsidian.ObsidianNoteResponse),
    RpcSpec("obsidian.search", _rpc_obsidian.ObsidianSearchRequest, _rpc_obsidian.ObsidianSearchResponse),
    # ── agents.* / delegation.* / subagent.* / spawn_tree.* ──────────────────
    RpcSpec("agents.list", _rpc_agents.AgentsListRequest, _rpc_agents.AgentsListResponse),
    RpcSpec("agents.active.summary", _rpc_agents.AgentsActiveSummaryRequest, _rpc_agents.AgentsActiveSummaryResponse),
    RpcSpec("delegation.status", _rpc_agents.DelegationStatusRequest, _rpc_agents.DelegationStatusResponse),
    RpcSpec("delegation.pause", _rpc_agents.DelegationPauseRequest, _rpc_agents.DelegationPauseResponse),
    RpcSpec("subagent.interrupt", _rpc_agents.SubagentInterruptRequest, _rpc_agents.SubagentInterruptResponse),
    RpcSpec("spawn_tree.list", _rpc_agents.SpawnTreeListRequest, _rpc_agents.SpawnTreeListResponse),
    RpcSpec("spawn_tree.load", _rpc_agents.SpawnTreeLoadRequest, _rpc_agents.SpawnTreeLoadResponse),
    # ── commands / completion / slash ────────────────────────────────────────
    RpcSpec("commands.catalog", _rpc_commands.CommandsCatalogRequest, _rpc_commands.CommandsCatalogResponse),
    RpcSpec("complete.slash", _rpc_commands.CompletionRequest, _rpc_commands.CompletionResponse),
    RpcSpec("complete.path", _rpc_commands.CompletionRequest, _rpc_commands.CompletionResponse),
    RpcSpec("slash.exec", _rpc_commands.SlashExecRequest, _rpc_commands.SlashExecResponse),
    # ── rollback.* ───────────────────────────────────────────────────────────
    RpcSpec("rollback.list", _rpc_rollback.RollbackListRequest, _rpc_rollback.RollbackListResponse),
    RpcSpec("rollback.diff", _rpc_rollback.RollbackDiffRequest, _rpc_rollback.RollbackDiffResponse),
    RpcSpec("rollback.restore", _rpc_rollback.RollbackRestoreRequest, _rpc_rollback.RollbackRestoreResponse),
    # ── interaction / utility RPCs ───────────────────────────────────────────
    RpcSpec("prompt.submit", _rpc_interact.PromptSubmitRequest, _rpc_interact.PromptSubmitResponse),
    RpcSpec("prompt.background", _rpc_interact.PromptBackgroundRequest, _rpc_interact.BackgroundStartResponse),
    RpcSpec("clarify.respond", _rpc_interact.ClarifyRespondRequest, _rpc_interact.ClarifyRespondResponse),
    RpcSpec("approval.respond", _rpc_interact.RespondRequest, _rpc_interact.ApprovalRespondResponse),
    RpcSpec("sudo.respond", _rpc_interact.RespondRequest, _rpc_interact.SudoRespondResponse),
    RpcSpec("secret.respond", _rpc_interact.RespondRequest, _rpc_interact.SecretRespondResponse),
    RpcSpec("shell.exec", _rpc_interact.ShellExecRequest, _rpc_interact.ShellExecResponse),
    RpcSpec("clipboard.paste", _rpc_interact.ClipboardPasteRequest, _rpc_interact.ClipboardPasteResponse),
    RpcSpec("input.detect_drop", _rpc_interact.InputDetectDropRequest, _rpc_interact.InputDetectDropResponse),
    RpcSpec("terminal.resize", _rpc_interact.TerminalResizeRequest, _rpc_interact.TerminalResizeResponse),
    RpcSpec("image.attach", _rpc_interact.ImageAttachRequest, _rpc_interact.ImageAttachResponse),
    RpcSpec("tools.configure", _rpc_interact.ToolsConfigureRequest, _rpc_interact.ToolsConfigureResponse),
    RpcSpec("reload.mcp", _rpc_interact.ReloadMcpRequest, _rpc_interact.ReloadMcpResponse),
    RpcSpec("reload.env", _rpc_interact.ReloadEnvRequest, _rpc_interact.ReloadEnvResponse),
    RpcSpec("process.stop", _rpc_interact.ProcessStopRequest, _rpc_interact.ProcessStopResponse),
    RpcSpec("browser.manage", _rpc_interact.BrowserManageRequest, _rpc_interact.BrowserManageResponse),
]

# Models that MUST be emitted to TS but are not a single RPC's primary
# request/response: config.get's polymorphic alternates, and the two shapes the
# TS-only ``GatewayEvent`` union nests (``SubagentEventPayload``/``GatewaySkin``,
# which the server emits under the ``subagent.*``/``skin.changed`` events using
# their own leaner event models). Listed here so the codegen collector reaches
# them.
EXTRA_MODELS: list[type[WireModel]] = [
    _rpc_config.ConfigMtimeResponse,
    _rpc_config.ConfigGetValueResponse,
    _rpc_agents.SubagentEventPayload,
    _rpc_interact.GatewaySkin,
    # ── sfp/1 collab wire (multiplayer M2) ───────────────────────────────────
    # The peer-to-peer protocol rides Slack message metadata, not the gateway
    # wire, so its models are not RPCs/events — but the TUI + docs still want the
    # typed shapes, so they ride EXTRA_MODELS (the codegen collector reaches the
    # nested value objects from the top-level models listed in COLLAB_MODELS).
    *_collab.COLLAB_MODELS,
]

EVENT_SPECS: list[EventSpec] = [
    EventSpec("command.started", _events_commands.CommandStarted),
    EventSpec("command.output", _events_commands.CommandOutput),
    EventSpec("command.finished", _events_commands.CommandFinished),
    # ── pm.* + jobs.* (A1 / Arc B) ───────────────────────────────────────────
    EventSpec("pm.tick", _events_pm.PmTick),
    EventSpec("jobs.progress", _events_jobs.JobProgress),
    EventSpec("jobs.complete", _events_jobs.JobComplete),
    EventSpec("jobs.error", _events_jobs.JobError),
    # ── gateway lifecycle / session ──────────────────────────────────────────
    EventSpec("gateway.ready", _events_gateway.GatewayReady),
    EventSpec("skin.changed", _events_gateway.Skin),
    EventSpec("session.info", _events_gateway.SessionInfo),
    EventSpec("gateway.stderr", _events_gateway.GatewayStderr),
    EventSpec("gateway.start_timeout", _events_gateway.GatewayStartTimeout),
    EventSpec("gateway.protocol_error", _events_gateway.GatewayProtocolError),
    # ── per-turn streaming ───────────────────────────────────────────────────
    EventSpec("thinking.delta", _events_turn.ThinkingDelta),
    EventSpec("message.start", _events_turn.MessageStart),
    EventSpec("message.delta", _events_turn.MessageDelta),
    EventSpec("message.complete", _events_turn.MessageComplete),
    EventSpec("reasoning.delta", _events_turn.ReasoningDelta),
    EventSpec("reasoning.available", _events_turn.ReasoningAvailable),
    EventSpec("status.update", _events_turn.StatusUpdate),
    EventSpec("error", _events_turn.ErrorEvent),
    EventSpec("browser.progress", _events_turn.BrowserProgress),
    # ── tool execution ───────────────────────────────────────────────────────
    EventSpec("tool.progress", _events_tools.ToolProgress),
    EventSpec("tool.generating", _events_tools.ToolGenerating),
    EventSpec("tool.start", _events_tools.ToolStart),
    EventSpec("tool.complete", _events_tools.ToolComplete),
    # ── blocking prompts ─────────────────────────────────────────────────────
    EventSpec("clarify.request", _events_prompts.ClarifyRequest),
    EventSpec("approval.request", _events_prompts.ApprovalRequest),
    EventSpec("sudo.request", _events_prompts.SudoRequest),
    EventSpec("secret.request", _events_prompts.SecretRequest),
    # ── delegation / subagents ───────────────────────────────────────────────
    EventSpec("subagent.spawn_requested", _events_subagents.SubagentEvent),
    EventSpec("subagent.start", _events_subagents.SubagentEvent),
    EventSpec("subagent.thinking", _events_subagents.SubagentEvent),
    EventSpec("subagent.tool", _events_subagents.SubagentEvent),
    EventSpec("subagent.progress", _events_subagents.SubagentEvent),
    EventSpec("subagent.complete", _events_subagents.SubagentEvent),
    EventSpec("background.complete", _events_subagents.BackgroundComplete),
    # ── voice ────────────────────────────────────────────────────────────────
    EventSpec("voice.status", _events_voice.VoiceStatus),
    EventSpec("voice.transcript", _events_voice.VoiceTranscript),
    # ── forecast desk (sessionless) ──────────────────────────────────────────
    EventSpec("cron.fired", _events_desk.CronFired),
    EventSpec("review.sweep", _events_desk.ReviewSweep),
    EventSpec("review.summary", _events_desk.ReviewSummary),
    # ── markets "Models" tab ─────────────────────────────────────────────────
    EventSpec("markets.model.progress", _events_markets.MarketModelProgress),
    EventSpec("markets.model.complete", _events_markets.MarketModelComplete),
    EventSpec("markets.model.refreshed", _events_markets.MarketModelRefreshed),
    EventSpec("markets.model.error", _events_markets.MarketModelError),
    # ── DEPRECATED legacy warning-automode aliases (Arc B compat) ─────────────
    EventSpec("forecast.warnings.automode.progress", _events_warnings.AutomodeProgress),
    EventSpec("forecast.warnings.automode.complete", _events_warnings.AutomodeComplete),
    EventSpec("forecast.warnings.automode.error", _events_warnings.AutomodeError),
]

RPC_BY_METHOD: dict[str, RpcSpec] = {spec.method: spec for spec in RPC_SPECS}


def registered_models() -> list[type[WireModel]]:
    """Every top-level model in the registry (nested models are discovered by
    the codegen collector)."""

    models: list[type[WireModel]] = []
    for spec in RPC_SPECS:
        models.append(spec.request)
        models.append(spec.response)
    for event in EVENT_SPECS:
        models.append(event.model)
    models.extend(EXTRA_MODELS)
    return models


__all__ = [
    "PROTOCOL_VERSION",
    "MIN_SUPPORTED",
    "RpcSpec",
    "EventSpec",
    "RPC_SPECS",
    "EVENT_SPECS",
    "EXTRA_MODELS",
    "RPC_BY_METHOD",
    "registered_models",
]
