"""Regression tests for the reasoning-budget-aware Codex stream-idle watchdog.

The openai-codex / ChatGPT-OAuth backend serves only REASONING models
(gpt-5.x). After the opening SSE frame they think *silently* server-side
(no SSE events — the ``_on_event`` marker in ``codex_runtime`` only advances on
real events) before streaming tokens. That silent gap scales with the reasoning
BUDGET, which is uncorrelated with context size. The legacy idle floor was
purely context-sized (12s at small context), so a small-context long-think was
killed mid-reason.

These tests pin the pure timeout-resolution helpers
(``_compute_codex_idle_floor`` / ``_compute_codex_stale_floor`` /
``_resolve_codex_reasoning_effort`` / ``_is_codex_reasoning_request``) and the
end-to-end env-override authority, while asserting the non-reasoning path is
byte-identical to the old context-size behavior.
"""

from __future__ import annotations

import sys
import time
import types
from types import SimpleNamespace

import pytest

# Stub optional heavy imports so run_agent imports cleanly in isolation.
sys.modules.setdefault("fire", types.SimpleNamespace(Fire=lambda *a, **k: None))
sys.modules.setdefault("firecrawl", types.SimpleNamespace(Firecrawl=object))
sys.modules.setdefault("fal_client", types.SimpleNamespace())


# ── Pure idle-floor helper ──────────────────────────────────────────────────

def test_idle_floor_non_reasoning_small_context_is_legacy_12s():
    """A non-reasoning small-context request keeps the legacy 12s floor."""
    from agent.chat_completion_helpers import _compute_codex_idle_floor

    assert _compute_codex_idle_floor(6_000, is_reasoning=False, effort=None) == 12.0


def test_idle_floor_non_reasoning_context_tiers_byte_identical():
    """Non-reasoning floors match the old inline context tiers verbatim."""
    from agent.chat_completion_helpers import _compute_codex_idle_floor

    f = lambda toks: _compute_codex_idle_floor(toks, is_reasoning=False, effort=None)
    assert f(5_000) == 12.0
    assert f(10_001) == 60.0
    assert f(50_001) == 120.0
    assert f(100_001) == 180.0


def test_idle_floor_reasoning_small_context_is_not_12s():
    """A reasoning small-context request gets the reasoning floor, NOT 12s."""
    from agent.chat_completion_helpers import _compute_codex_idle_floor

    # Unknown effort -> single safe reasoning default.
    floor = _compute_codex_idle_floor(6_000, is_reasoning=True, effort=None)
    assert floor == 180.0
    assert floor != 12.0


def test_idle_floor_scales_with_effort():
    """The reasoning floor scales monotonically with effort."""
    from agent.chat_completion_helpers import _compute_codex_idle_floor

    low = _compute_codex_idle_floor(6_000, is_reasoning=True, effort="low")
    medium = _compute_codex_idle_floor(6_000, is_reasoning=True, effort="medium")
    high = _compute_codex_idle_floor(6_000, is_reasoning=True, effort="high")
    xhigh = _compute_codex_idle_floor(6_000, is_reasoning=True, effort="xhigh")

    assert (low, medium, high, xhigh) == (45.0, 120.0, 240.0, 360.0)
    assert low < medium < high < xhigh
    # Every effort tier is strictly above the legacy small-context 12s floor.
    assert all(v > 12.0 for v in (low, medium, high, xhigh))


def test_idle_floor_never_lowers_context_value():
    """The reasoning floor only ever raises the context-size floor."""
    from agent.chat_completion_helpers import _compute_codex_idle_floor

    # Large context (180s) with a small reasoning effort (low=45s): keep 180.
    floor = _compute_codex_idle_floor(120_000, is_reasoning=True, effort="low")
    assert floor == 180.0
    # Large context with high effort (240s): take the larger reasoning floor.
    floor_high = _compute_codex_idle_floor(120_000, is_reasoning=True, effort="high")
    assert floor_high == 240.0


def test_idle_floor_minimal_effort_clamped_to_low():
    """``minimal`` resolves to the ``low`` floor (matches transport clamp)."""
    from agent.chat_completion_helpers import _compute_codex_idle_floor

    assert _compute_codex_idle_floor(
        6_000, is_reasoning=True, effort="minimal"
    ) == 45.0


# ── Pure stale-floor helper ─────────────────────────────────────────────────

def test_stale_floor_at_least_idle_floor_for_reasoning():
    """For reasoning requests the wall-clock stale backstop is >= idle floor
    so the overall timeout cannot fire before the idle watchdog."""
    from agent.chat_completion_helpers import _compute_codex_stale_floor

    idle = 240.0  # high effort, small context
    stale = _compute_codex_stale_floor(
        60.0, 6_000, is_reasoning=True, idle_floor=idle
    )
    assert stale >= idle


def test_stale_floor_non_reasoning_unchanged_small_context():
    """Non-reasoning small-context requests keep the base stale timeout."""
    from agent.chat_completion_helpers import _compute_codex_stale_floor

    stale = _compute_codex_stale_floor(
        60.0, 6_000, is_reasoning=False, idle_floor=12.0
    )
    assert stale == 60.0


def test_stale_floor_large_context_tiers_preserved():
    """The existing large-context stale tiers are unchanged."""
    from agent.chat_completion_helpers import _compute_codex_stale_floor

    g = lambda toks: _compute_codex_stale_floor(
        60.0, toks, is_reasoning=False, idle_floor=12.0
    )
    assert g(30_000) == 600.0
    assert g(60_000) == 900.0
    assert g(120_000) == 1200.0


# ── Reasoning detection / effort resolution ─────────────────────────────────

def test_resolve_effort_prefers_payload():
    """The effort actually sent on the wire wins over the configured dial."""
    from agent.chat_completion_helpers import _resolve_codex_reasoning_effort

    agent = SimpleNamespace(reasoning_config={"effort": "low"})
    api_kwargs = {"reasoning": {"effort": "high", "summary": "auto"}}
    assert _resolve_codex_reasoning_effort(agent, api_kwargs) == "high"


def test_resolve_effort_falls_back_to_config():
    """With no payload reasoning, fall back to the agent's reasoning_config."""
    from agent.chat_completion_helpers import _resolve_codex_reasoning_effort

    agent = SimpleNamespace(reasoning_config={"effort": "medium"})
    assert _resolve_codex_reasoning_effort(agent, {"input": "hi"}) == "medium"


def test_resolve_effort_disabled_returns_none():
    """Explicitly disabled reasoning resolves to None."""
    from agent.chat_completion_helpers import _resolve_codex_reasoning_effort

    agent = SimpleNamespace(reasoning_config={"enabled": False, "effort": "high"})
    assert _resolve_codex_reasoning_effort(agent, {"input": "hi"}) is None


def test_is_reasoning_request_true_for_openai_codex_backend():
    """The openai-codex backend serves only reasoning models -> always True,
    even with no reasoning_config and no payload reasoning block."""
    from agent.chat_completion_helpers import _is_codex_reasoning_request

    agent = SimpleNamespace(
        provider="openai-codex",
        _base_url_lower="https://chatgpt.com/backend-api/codex",
        _base_url_hostname="chatgpt.com",
        reasoning_config=None,
    )
    assert _is_codex_reasoning_request(agent, {"model": "gpt-5.5", "input": "hi"})


def test_is_reasoning_request_false_for_plain_request():
    """A non-codex backend with no reasoning enabled is not a reasoning request."""
    from agent.chat_completion_helpers import _is_codex_reasoning_request

    agent = SimpleNamespace(
        provider="xai-oauth",
        _base_url_lower="https://api.x.ai/v1",
        _base_url_hostname="api.x.ai",
        reasoning_config={"enabled": False},
    )
    assert not _is_codex_reasoning_request(agent, {"model": "grok-4", "input": "hi"})


def test_is_reasoning_request_true_for_native_reasoner_on_codex_path():
    """The MAJOR-fix regression: a native reasoner (e.g. grok) on the
    codex_responses path with NO dialed effort and NO openai-codex backend is STILL
    reasoning-aware — that transport serves only reasoning models, which reason
    silently, so it must not be left at the 12s context-size floor."""
    from agent.chat_completion_helpers import _is_codex_reasoning_request

    agent = SimpleNamespace(
        provider="xai-oauth",
        _base_url_lower="https://api.x.ai/v1",
        _base_url_hostname="api.x.ai",
        reasoning_config=None,
        api_mode="codex_responses",
    )
    assert _is_codex_reasoning_request(agent, {"model": "grok-4", "input": "hi"})
    # ...but an EXPLICITLY-disabled reasoning dial on the same path opts out.
    agent.reasoning_config = {"enabled": False}
    assert not _is_codex_reasoning_request(agent, {"model": "grok-4", "input": "hi"})


# ── End-to-end: env overrides win, TTFB unchanged ───────────────────────────

def _make_codex_agent(tmp_path, monkeypatch, *, reasoning_config=None):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / ".env").write_text("", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("{}\n", encoding="utf-8")
    from run_agent import AIAgent

    agent = AIAgent(
        model="gpt-5.5",
        provider="openai-codex",
        api_key="sk-dummy",
        base_url="https://chatgpt.com/backend-api/codex",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
        platform="cli",
        reasoning_config=reasoning_config,
    )
    agent.api_mode = "codex_responses"
    monkeypatch.setattr(agent, "_emit_status", lambda *a, **k: None)
    monkeypatch.setattr(
        agent, "_compute_non_stream_stale_timeout", lambda *a, **k: 60.0
    )
    return agent


def test_explicit_idle_env_override_wins_for_reasoning(tmp_path, monkeypatch):
    """An explicit CODEX_EVENT_STALE_TIMEOUT override beats the reasoning-aware
    default: an opening frame then silence is killed at the 1s override even
    though the reasoning default floor would be 180s+."""
    from agent import chat_completion_helpers as h

    agent = _make_codex_agent(tmp_path, monkeypatch)
    monkeypatch.setenv("HERMES_CODEX_TTFB_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("HERMES_CODEX_EVENT_STALE_TIMEOUT_SECONDS", "1")

    closes: list = []
    dummy_client = SimpleNamespace()
    monkeypatch.setattr(agent, "_create_request_openai_client", lambda **k: dummy_client)
    monkeypatch.setattr(
        agent, "_close_request_openai_client",
        lambda c, reason=None: closes.append(reason),
    )

    stop = {"flag": False}

    def fake_stream(api_kwargs, client=None, on_first_delta=None):
        agent._codex_stream_last_event_ts = time.time()
        deadline = time.time() + 30
        while time.time() < deadline and not stop["flag"] and not agent._interrupt_requested:
            time.sleep(0.02)
        raise RuntimeError("connection closed")

    monkeypatch.setattr(agent, "_run_codex_stream", fake_stream)

    t0 = time.time()
    try:
        with pytest.raises(TimeoutError) as excinfo:
            h.interruptible_api_call(agent, {"model": "gpt-5.5", "input": "hi"})
        elapsed = time.time() - t0
        assert "after first byte" in str(excinfo.value)
        assert "threshold: 1s" in str(excinfo.value)
        assert "codex_stream_idle_kill" in closes
        assert elapsed < 15, f"explicit idle override ignored ({elapsed:.1f}s)"
    finally:
        stop["flag"] = True


def test_idle_env_zero_disables_for_reasoning(tmp_path, monkeypatch):
    """CODEX_EVENT_STALE_TIMEOUT=0 disables the idle watchdog entirely even for
    a reasoning request; a short post-frame silence is NOT killed by it."""
    from agent import chat_completion_helpers as h

    agent = _make_codex_agent(tmp_path, monkeypatch)
    monkeypatch.setenv("HERMES_CODEX_TTFB_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("HERMES_CODEX_EVENT_STALE_TIMEOUT_SECONDS", "0")

    closes: list = []
    dummy_client = SimpleNamespace()
    monkeypatch.setattr(agent, "_create_request_openai_client", lambda **k: dummy_client)
    monkeypatch.setattr(
        agent, "_close_request_openai_client",
        lambda c, reason=None: closes.append(reason),
    )

    sentinel = SimpleNamespace(ok=True)

    def fake_stream(api_kwargs, client=None, on_first_delta=None):
        agent._codex_stream_last_event_ts = time.time()
        time.sleep(2.0)
        return sentinel

    monkeypatch.setattr(agent, "_run_codex_stream", fake_stream)

    resp = h.interruptible_api_call(agent, {"model": "gpt-5.5", "input": "hi"})
    assert resp is sentinel
    assert "codex_stream_idle_kill" not in closes


def test_reasoning_small_context_long_think_survives(tmp_path, monkeypatch):
    """The regression: a reasoning call that goes silent LONGER than the
    context-size floor after the opening frame must NOT be killed — the
    reasoning-aware floor (high effort => 240s) supersedes it.

    Made fast yet DEFINITIVE by shrinking the legacy context-size idle floor to
    1s: a 1.5s silent gap then genuinely distinguishes fixed (survives, because the
    reasoning floor is 240s) from broken (would die at the 1s context floor)."""
    from agent import chat_completion_helpers as h

    agent = _make_codex_agent(
        tmp_path, monkeypatch, reasoning_config={"effort": "high"}
    )
    monkeypatch.setenv("HERMES_CODEX_TTFB_TIMEOUT_SECONDS", "60")
    # Shrink ONLY the legacy context-size floor; the reasoning floor (240s) is what
    # must keep the call alive past it. Without the fix the gap would trip this 1s.
    monkeypatch.setattr(h, "_codex_context_idle_floor", lambda est: 1.0)

    closes: list = []
    dummy_client = SimpleNamespace()
    monkeypatch.setattr(agent, "_create_request_openai_client", lambda **k: dummy_client)
    monkeypatch.setattr(
        agent, "_close_request_openai_client",
        lambda c, reason=None: closes.append(reason),
    )

    sentinel = SimpleNamespace(ok=True)

    def fake_stream(api_kwargs, client=None, on_first_delta=None):
        # Opening frame, then a silent gap > the 1s context floor but << the 240s
        # reasoning floor: only the reasoning-aware floor keeps it alive.
        agent._codex_stream_last_event_ts = time.time()
        if on_first_delta:
            on_first_delta()
        time.sleep(1.5)
        return sentinel

    monkeypatch.setattr(agent, "_run_codex_stream", fake_stream)

    resp = h.interruptible_api_call(agent, {"model": "gpt-5.5", "input": "hi"})
    assert resp is sentinel
    assert "codex_stream_idle_kill" not in closes


def test_ttfb_no_first_byte_unchanged_for_reasoning(tmp_path, monkeypatch):
    """TTFB (no first byte AT ALL) behavior is unchanged: a reasoning backend
    that accepts then sends nothing is still killed promptly at the TTFB
    cutoff, regardless of the reasoning-aware idle floor."""
    from agent import chat_completion_helpers as h

    agent = _make_codex_agent(
        tmp_path, monkeypatch, reasoning_config={"effort": "high"}
    )
    monkeypatch.setenv("HERMES_CODEX_TTFB_TIMEOUT_SECONDS", "1")

    closes: list = []
    dummy_client = SimpleNamespace()
    monkeypatch.setattr(agent, "_create_request_openai_client", lambda **k: dummy_client)
    monkeypatch.setattr(
        agent, "_close_request_openai_client",
        lambda c, reason=None: closes.append(reason),
    )

    stop = {"flag": False}

    def fake_hang(api_kwargs, client=None, on_first_delta=None):
        # Never set _codex_stream_last_event_ts: zero events arrive.
        deadline = time.time() + 30
        while time.time() < deadline and not stop["flag"] and not agent._interrupt_requested:
            time.sleep(0.02)
        raise RuntimeError("connection closed")

    monkeypatch.setattr(agent, "_run_codex_stream", fake_hang)

    t0 = time.time()
    try:
        with pytest.raises(TimeoutError) as excinfo:
            h.interruptible_api_call(agent, {"model": "gpt-5.5", "input": "hi"})
        elapsed = time.time() - t0
        assert "TTFB" in str(excinfo.value)
        assert "codex_ttfb_kill" in closes
        assert elapsed < 15, f"TTFB watchdog took {elapsed:.1f}s"
    finally:
        stop["flag"] = True
