"""Protocol-first gateway contract: one source of truth for every RPC and event
crossing the gateway wire, with TypeScript types generated from it.

The registry below drives both the server-side ``@rpc-model`` validation
(``tui_gateway/pm_rpc.py``) and the TypeScript codegen (``protocol.codegen`` →
``ui-tui/src/protocol/generated.ts``). Drift between the two becomes a build
error (the staleness gate) instead of a runtime mystery.
"""

from __future__ import annotations

from dataclasses import dataclass

from protocol.events import jobs as _events_jobs
from protocol.events import pm as _events_pm
from protocol.rpc import jobs as _rpc_jobs
from protocol.rpc import markets as _rpc_markets
from protocol.rpc import pm as _rpc_pm
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
]

EVENT_SPECS: list[EventSpec] = [
    EventSpec("pm.tick", _events_pm.PmTick),
    EventSpec("jobs.progress", _events_jobs.JobProgress),
    EventSpec("jobs.complete", _events_jobs.JobComplete),
    EventSpec("jobs.error", _events_jobs.JobError),
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
