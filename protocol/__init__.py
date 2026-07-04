"""Protocol-first gateway contract: one source of truth for every RPC and event
crossing the gateway wire, with TypeScript types generated from it.

The registry below drives both the server-side ``@rpc-model`` validation
(``tui_gateway/pm_rpc.py``) and the TypeScript codegen (``protocol.codegen`` →
``ui-tui/src/protocol/generated.ts``). Drift between the two becomes a build
error (the staleness gate) instead of a runtime mystery.
"""

from __future__ import annotations

from dataclasses import dataclass

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
from protocol.rpc import forecast as _rpc_forecast
from protocol.rpc import jobs as _rpc_jobs
from protocol.rpc import markets as _rpc_markets
from protocol.rpc import pm as _rpc_pm
from protocol.rpc import warnings as _rpc_warnings
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
]

EVENT_SPECS: list[EventSpec] = [
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
    return models


__all__ = [
    "PROTOCOL_VERSION",
    "MIN_SUPPORTED",
    "RpcSpec",
    "EventSpec",
    "RPC_SPECS",
    "EVENT_SPECS",
    "RPC_BY_METHOD",
    "registered_models",
]
