"""Conformance for the ARC A4 families — the arc closer.

Covers the session / config / theme / model / voice / obsidian / agents /
commands / rollback / interaction RPCs that A4 modelled, plus:
* the VERSION HANDSHAKE (PROTOCOL_VERSION rides gateway.ready + session.info);
* the VALIDATE-ONLY wrapper leaving a wrapped handler's wire result UNCHANGED;
* the tolerant-model contract (a rich real frame validates; extras ignored);
* the codegen additions (Literal string-unions, tuple pairs, the generated
  SessionInfo/Usage the whole app now re-exports).
"""

from __future__ import annotations

import types

import pytest
from pydantic import ValidationError

from protocol import RPC_BY_METHOD
from protocol.rpc import agents as A
from protocol.rpc import commands as C
from protocol.rpc import config as CFG
from protocol.rpc import session as S
from protocol.version import PROTOCOL_VERSION

# Every method A4 registered — the arc-closing inventory (must all resolve).
A4_METHODS = [
    "session.create", "session.resume", "session.list", "session.delete",
    "session.most_recent", "session.title", "session.save", "session.undo",
    "session.usage", "session.status", "session.compress", "session.branch",
    "session.close", "session.interrupt", "session.steer", "session.history",
    "config.get", "config.set", "setup.status",
    "theme.list", "model.options",
    "voice.toggle", "voice.record", "voice.stop",
    "obsidian.status", "obsidian.note", "obsidian.search",
    "agents.list", "agents.active.summary", "delegation.status", "delegation.pause",
    "subagent.interrupt", "spawn_tree.list", "spawn_tree.load",
    "commands.catalog", "complete.slash", "complete.path", "slash.exec",
    "rollback.list", "rollback.diff", "rollback.restore",
    "prompt.submit", "prompt.background", "clarify.respond", "approval.respond",
    "sudo.respond", "secret.respond", "shell.exec", "clipboard.paste",
    "input.detect_drop", "terminal.resize", "image.attach", "tools.configure",
    "reload.mcp", "reload.env", "process.stop", "browser.manage",
]


@pytest.mark.parametrize("method", A4_METHODS)
def test_every_a4_method_is_registered(method):
    spec = RPC_BY_METHOD[method]
    assert spec.request is not None and spec.response is not None


# ── real-frame validation (tolerant models) ───────────────────────────────────


def test_session_create_frame_validates_with_rich_info():
    frame = {
        "session_id": "sess-1",
        "info": {
            "model": "anthropic/claude-sonnet-4",
            "skills": {}, "tools": {},
            "usage": {"calls": 1, "input": 2, "output": 3, "total": 5},
            "update_behind": None,
            "config_warning": "check your key",
            # an extra the model never declared — tolerated (extra='ignore')
            "mystery_field": 42,
        },
    }
    model = RPC_BY_METHOD["session.create"].response.model_validate(frame)
    assert model.info.model == "anthropic/claude-sonnet-4"
    assert model.info.config_warning == "check your key"


def test_config_display_union_and_setup_frames_validate():
    # the multi-typed display keys (mouse_tracking bool|num|str|null, tui_statusbar
    # literal|bool) all validate against real hand-edited values.
    for mt in (True, 1, "on", None):
        CFG.ConfigDisplayConfig.model_validate({"mouse_tracking": mt, "tui_statusbar": "top"})
    CFG.ConfigDisplayConfig.model_validate({"tui_statusbar": True})
    CFG.SetupStatusResponse.model_validate({"provider_configured": False})


def test_agents_active_summary_frame_validates():
    frame = {"count": 2, "kinds": {"procs": 1, "reforecast": 1, "quorum": 0}, "headline": "2 agents running · quorum"}
    model = RPC_BY_METHOD["agents.active.summary"].response.model_validate(frame)
    assert model.count == 2 and model.kinds.reforecast == 1


def test_slash_category_tuple_pairs_validate():
    cat = C.SlashCategory.model_validate({"name": "session", "pairs": [["/resume", "resume a session"]]})
    assert cat.pairs[0] == ("/resume", "resume a session")


def test_subagent_status_literal_rejects_bogus_value():
    A.SubagentEventPayload.model_validate({"goal": "g", "task_index": 0, "status": "running"})  # ok
    with pytest.raises(ValidationError) as exc:
        A.SubagentEventPayload.model_validate({"goal": "g", "task_index": 0, "status": "sprinting"})
    locs = {str(p) for e in exc.value.errors() for p in e["loc"]}
    assert "status" in locs


# ── request validation names the field ────────────────────────────────────────


def test_session_resume_request_requires_session_id():
    S.SessionResumeRequest.model_validate({"session_id": "s"})  # ok
    with pytest.raises(ValidationError) as exc:
        S.SessionResumeRequest.model_validate({})
    locs = {str(p) for e in exc.value.errors() for p in e["loc"]}
    assert "session_id" in locs


# ── the version handshake ─────────────────────────────────────────────────────


def test_gateway_ready_and_session_info_carry_protocol_version():
    from protocol.events.gateway import GatewayReady, SessionInfo as SessionInfoEvent

    assert "protocol_version" in GatewayReady.model_fields
    assert "protocol_version" in SessionInfoEvent.model_fields
    assert "protocol_version" in S.SessionInfo.model_fields
    # a ready frame round-trips the version
    ready = GatewayReady.model_validate({"skin": {}, "protocol_version": PROTOCOL_VERSION})
    assert ready.protocol_version == PROTOCOL_VERSION


def test_session_info_emission_advertises_protocol_version():
    import tui_gateway.server as server

    info = server._session_info(types.SimpleNamespace())
    assert info["protocol_version"] == PROTOCOL_VERSION


# ── VALIDATE-ONLY wrapper leaves the wire UNCHANGED ───────────────────────────


def test_validate_only_wrapper_returns_handler_result_unchanged():
    import tui_gateway.server as server

    # agents.active.summary is fail-safe (no session needed) and is wrapped with
    # @rpc_validated — the wrapper VALIDATES then returns the handler's ORIGINAL
    # result dict byte-for-byte (the forecast/A4 families never re-dump).
    resp = server.handle_request({"id": "1", "method": "agents.active.summary", "params": {}})
    result = resp["result"]
    assert set(result) == {"count", "kinds", "headline"}
    assert set(result["kinds"]) == {"procs", "reforecast", "quorum"}
    # the exact shape validates against the registered response model
    RPC_BY_METHOD["agents.active.summary"].response.model_validate(result)


# ── codegen additions present in the generated TS ─────────────────────────────


def test_generated_ts_carries_a4_shapes_and_version():
    from protocol.codegen import generated_path

    text = generated_path().read_text(encoding="utf-8")
    assert f"export const PROTOCOL_VERSION = {PROTOCOL_VERSION}" in text
    # the app-unified composites + a tuple + a literal union + the agents family
    assert "export interface SessionInfo {" in text
    assert "export interface Usage {" in text
    assert "pairs: [string, string][]" in text
    assert "protocol_version?: number" in text
    for name in ("AgentsActiveSummaryResponse", "SubagentEventPayload", "GatewaySkin", "ThemeListResponse"):
        assert f"export interface {name} {{" in text
