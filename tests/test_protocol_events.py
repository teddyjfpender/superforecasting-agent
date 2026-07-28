"""Conformance for the gateway EVENT models (Arc A2).

Guarantees, per event family:
* every event emitted by ``tui_gateway`` (and the three client-synthesised
  transport events) is REGISTERED with a payload model;
* a captured REAL frame — the exact dict the server's ``_emit`` puts on the wire
  — round-trips through the model and ``model_dump`` reproduces it (the wire never
  changes shape). ``exclude_none`` mirrors the server's conditional-key emission
  for the models built by conditional insertion.

These frames are lifted verbatim from the emission sites in
``tui_gateway/server.py`` / ``jobs_rpc.py`` (line refs in each model's docstring).
"""

from __future__ import annotations

import pytest

from protocol import EVENT_SPECS
from protocol.events.desk import CronFired, ReviewSummary, ReviewSweep
from protocol.events.gateway import (
    GatewayProtocolError,
    GatewayReady,
    GatewayStartTimeout,
    GatewayStderr,
    SessionInfo,
    Skin,
)
from protocol.events.markets import (
    MarketModelComplete,
    MarketModelError,
    MarketModelProgress,
    MarketModelRefreshed,
)
from protocol.events.prompts import (
    ApprovalRequest,
    ClarifyRequest,
    SecretRequest,
    SudoRequest,
)
from protocol.events.subagents import BackgroundComplete, SubagentEvent
from protocol.events.tools import ToolComplete, ToolGenerating, ToolProgress, ToolStart
from protocol.events.turn import (
    BrowserProgress,
    ErrorEvent,
    MessageComplete,
    MessageDelta,
    MessageStart,
    ReasoningAvailable,
    ReasoningDelta,
    StatusUpdate,
    ThinkingDelta,
)
from protocol.events.voice import VoiceStatus, VoiceTranscript
from protocol.events.warnings import AutomodeComplete, AutomodeError, AutomodeProgress

# Every registered event name — the codegen emits a `WireEvent.<KEY>` constant for
# each, and the TUI references ONLY those constants (the A2 grep-proof).
EXPECTED_EVENT_NAMES = {
    "pm.tick",
    "jobs.progress",
    "jobs.complete",
    "jobs.error",
    "gateway.ready",
    "skin.changed",
    "session.info",
    "gateway.stderr",
    "gateway.start_timeout",
    "gateway.protocol_error",
    "thinking.delta",
    "message.start",
    "message.delta",
    "message.complete",
    "reasoning.delta",
    "reasoning.available",
    "status.update",
    "error",
    "browser.progress",
    "tool.progress",
    "tool.generating",
    "tool.start",
    "tool.complete",
    "clarify.request",
    "approval.request",
    "sudo.request",
    "secret.request",
    "subagent.spawn_requested",
    "subagent.start",
    "subagent.thinking",
    "subagent.tool",
    "subagent.progress",
    "subagent.complete",
    "background.complete",
    "voice.status",
    "voice.transcript",
    "cron.fired",
    "review.sweep",
    "review.summary",
    "markets.model.progress",
    "markets.model.complete",
    "markets.model.refreshed",
    "markets.model.error",
    "forecast.warnings.automode.progress",
    "forecast.warnings.automode.complete",
    "forecast.warnings.automode.error",
}


def test_every_event_name_registered_exactly_once():
    names = [e.name for e in EVENT_SPECS]
    assert len(names) == len(set(names)), "duplicate event registration"
    assert set(names) == EXPECTED_EVENT_NAMES


# (model, frame, exclude_none) — the frame is the server's actual _emit payload.
CASES: list[tuple[type, dict, bool]] = [
    # ── gateway lifecycle ────────────────────────────────────────────────────
    (Skin, {"name": "aurora", "appearance": "dark", "banner_logo": "L", "banner_hero": "H",
            "tool_prefix": "◇", "help_header": "?", "colors": {"fg": "#fff"}, "branding": {"x": "y"}}, True),
    (Skin, {}, True),  # resolve_skin() returns {} on failure
    (GatewayReady, {"skin": {"name": "aurora", "appearance": "auto"}}, True),
    (GatewayReady, {"skin": {"name": "aurora"}, "protocol_version": 1,
                    "build": {"version": "0.19.0", "release_date": "2026.7.24",
                              "install_method": "git", "latest_version": "0.19.0",
                              "behind": 0, "stale": False, "remedy": "x"}}, True),
    # A cold-cache / offline gateway.ready: the version alone, nothing resolved.
    (GatewayReady, {"build": {"version": "0.19.0"}}, True),
    (GatewayReady, {}, True),
    (SessionInfo, {"model": "anthropic/claude-sonnet-4", "reasoning_effort": "", "service_tier": "",
                   "fast": False, "cwd": "/x", "version": "1.2.3", "release_date": "2026-07-04",
                   "update_behind": None, "update_command": "", "profile_name": "default",
                   "usage": {"input_tokens": 10}, "tools": {}, "skills": {},
                   "protocol_version": 1,
                   "build": {"version": "1.2.3", "release_date": "2026-07-04",
                             "install_method": "pip", "latest_version": "1.3.0",
                             "behind": -1, "stale": True, "remedy": "curl … | bash"}}, False),
    (GatewayStderr, {"line": "traceback…"}, False),
    (GatewayStartTimeout, {"cwd": "/x", "python": "/py", "stderr_tail": "boom"}, True),
    (GatewayStartTimeout, {}, True),
    (GatewayProtocolError, {"preview": "not json{"}, True),
    # ── per-turn ─────────────────────────────────────────────────────────────
    (ThinkingDelta, {"text": "hm"}, True),
    (MessageStart, {}, True),
    (MessageDelta, {"text": "hel", "rendered": "hel"}, True),
    (MessageDelta, {"text": "hel"}, True),
    (MessageComplete, {"text": "done", "status": "complete", "usage": {"input_tokens": 3}}, True),
    (MessageComplete, {"text": "done", "status": "complete", "usage": {}, "rendered": "R",
                       "reasoning": "because", "warning": "note"}, True),
    (ReasoningDelta, {"text": "step"}, True),
    (ReasoningAvailable, {"text": "block"}, True),
    (StatusUpdate, {"kind": "process", "text": "reforecasting…"}, False),
    (StatusUpdate, {"kind": "goal", "text": "✓ done"}, False),
    (ErrorEvent, {"message": "agent init failed: boom"}, False),
    (BrowserProgress, {"message": "loaded", "level": "info"}, True),
    # ── tools ────────────────────────────────────────────────────────────────
    (ToolProgress, {"name": "web_search", "preview": "querying…"}, True),
    (ToolGenerating, {"name": "edit"}, True),
    (ToolStart, {"tool_id": "tc_1", "name": "todo", "context": "3 items", "todos": [{"t": "x"}]}, True),
    (ToolStart, {"tool_id": "tc_1"}, True),
    (ToolComplete, {"tool_id": "tc_1", "name": "edit", "duration_s": 0.42, "summary": "ok",
                    "inline_diff": "- a\n+ b", "todos": [{"t": "x", "status": "completed"}]}, True),
    (ToolComplete, {"tool_id": "tc_1", "name": "bash"}, True),
    # tool.complete now ships the cumulative session usage (same Usage shape as
    # message.complete) so the TUI can climb its liveness counter mid-turn.
    (ToolComplete, {"tool_id": "tc_1", "name": "web_search",
                    "usage": {"calls": 3, "input": 1_200, "output": 340, "total": 1_540,
                              "reasoning": 64}}, True),
    # ── blocking prompts ─────────────────────────────────────────────────────
    (ClarifyRequest, {"request_id": "r1", "question": "which?", "choices": ["a", "b"]}, False),
    (ClarifyRequest, {"request_id": "r1", "question": "which?", "choices": None}, False),
    (ApprovalRequest, {"command": "rm -rf x", "description": "dangerous", "request_id": "r2"}, True),
    (ApprovalRequest, {"command": "rm -rf x", "description": "dangerous"}, True),
    (SudoRequest, {"request_id": "r3"}, False),
    (SecretRequest, {"request_id": "r4", "prompt": "API key?", "env_var": "OPENAI_API_KEY",
                     "metadata": {"provider": "openai"}}, True),
    (SecretRequest, {"request_id": "r4", "prompt": "API key?", "env_var": "X"}, True),
    # ── subagents ────────────────────────────────────────────────────────────
    (SubagentEvent, {"goal": "research", "task_index": 0, "task_count": 1}, True),
    (SubagentEvent, {"goal": "research", "task_index": 0, "task_count": 2, "subagent_id": "sa_1",
                     "parent_id": "sa_0", "depth": 1, "model": "gpt-5", "tool_count": 4,
                     "toolsets": ["web"], "input_tokens": 100, "output_tokens": 50,
                     "reasoning_tokens": 10, "api_calls": 3, "cost_usd": 0.01,
                     "files_read": ["a.py"], "files_written": ["b.py"],
                     "output_tail": [{"tool": "bash", "preview": "ok", "is_error": False}],
                     "tool_name": "bash", "tool_preview": "ls", "text": "listing",
                     "status": "completed", "summary": "done", "duration_seconds": 2.5}, True),
    (BackgroundComplete, {"task_id": "bg_1", "text": "final answer"}, False),
    (BackgroundComplete, {"task_id": "bg_1", "text": "error: boom"}, False),
    # ── voice ────────────────────────────────────────────────────────────────
    (VoiceStatus, {"state": "listening"}, True),
    (VoiceTranscript, {"text": "open markets"}, True),
    (VoiceTranscript, {"no_speech_limit": True}, True),
    # ── forecast desk (sessionless) ──────────────────────────────────────────
    (CronFired, {"count": 3}, True),
    (ReviewSweep, {"phase": "started", "due_count": 5}, True),
    (ReviewSweep, {"phase": "done", "refreshed": 4, "alerts": 1, "duration_ms": 1200}, True),
    (ReviewSummary, {"text": "💾 Self-improvement review: …"}, True),
    # ── markets "Models" tab ─────────────────────────────────────────────────
    (MarketModelProgress, {"id": "m1", "phase": "starting", "message": "starting"}, True),
    (MarketModelProgress, {"id": "m1", "message": "step 2"}, True),
    (MarketModelComplete, {"id": "m1", "version": 2, "status": "ready"}, True),
    (MarketModelRefreshed, {"id": "m1", "presentation": {"blocks": []}}, True),
    (MarketModelError, {"id": "m1", "message": "failed"}, True),
    # ── DEPRECATED warning-automode aliases ──────────────────────────────────
    (AutomodeProgress, {"job_id": "wj_1", "phase": "alert", "done": 1, "total": 3,
                        "remaining": 2, "alert_id": "al_1", "reason": "stale", "status": "acked"}, True),
    (AutomodeComplete, {"job_id": "wj_1", "processed": 3, "total": 3, "cancelled": False,
                        "dry_run": False, "tally": {"acked": 2, "skipped": 1}}, True),
    (AutomodeError, {"job_id": "wj_1", "message": "boom"}, True),
]


@pytest.mark.parametrize(
    "model,frame,exclude_none",
    CASES,
    ids=[f"{m.__name__}-{i}" for i, (m, _, _) in enumerate(CASES)],
)
def test_real_event_frame_is_wire_identical(model, frame, exclude_none):
    """A real _emit payload parses through the model and model_dump reproduces
    it EXACTLY — proving a typed emission would never mutate the wire."""

    dumped = model.model_validate(frame).model_dump(mode="json", exclude_none=exclude_none)
    assert dumped == frame


def test_session_info_ignores_extra_keys():
    """The real session.info frame carries MORE keys than the (partial) model;
    extra='ignore' lets it validate, and model_dump exposes the declared subset."""

    fuller = {
        "model": "m", "reasoning_effort": "", "service_tier": "", "fast": False, "cwd": "/x",
        "version": "1", "release_date": "d", "update_behind": None, "update_command": "",
        "profile_name": "p", "usage": {}, "tools": {}, "skills": {},
        # extra keys the server also emits (mcp_servers, system_prompt, …):
        "mcp_servers": [], "system_prompt": "you are…",
    }
    model = SessionInfo.model_validate(fuller)  # must not raise
    dumped = model.model_dump(mode="json")
    assert "mcp_servers" not in dumped and dumped["model"] == "m"


def test_review_sweep_started_and_done_share_one_model():
    """The phase-discriminated review.sweep folds both shapes into one model."""

    started = ReviewSweep.model_validate({"phase": "started", "due_count": 2})
    done = ReviewSweep.model_validate({"phase": "done", "refreshed": 1, "alerts": 0, "duration_ms": 9})
    assert started.model_dump(mode="json", exclude_none=True) == {"phase": "started", "due_count": 2}
    assert done.model_dump(mode="json", exclude_none=True) == {
        "phase": "done", "refreshed": 1, "alerts": 0, "duration_ms": 9,
    }
