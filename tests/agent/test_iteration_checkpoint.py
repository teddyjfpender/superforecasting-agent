"""Checkpoint-continuation for the agent tool-call budget.

Covers the redesign of the old hard iteration cap: the per-turn soft cap is now
appconfig-tunable (``FORECAST_AGENT_MAX_TOOL_ITERATIONS``), and a breach becomes a
CHECKPOINT (surface progress + reset the budget + continue) instead of a stop —
gated by interactive presence or the spend policy, and backstopped by a 10× hard
ceiling that still stops with a key-naming message.
"""

import os
import types

import pytest

from agent import chat_completion_helpers as cch
from agent.iteration_budget import (
    DEFAULT_MAX_TOOL_ITERATIONS,
    IterationBudget,
    decide_checkpoint_continuation,
    resolve_hard_ceiling,
    resolve_max_tool_iterations,
)

_FAMILY = (
    "FORECAST_AGENT_MAX_TOOL_ITERATIONS",
    "SUPERFORECASTING_AGENT_MAX_ITERATIONS",
    "FORECAST_MAX_ITERATIONS",
    "HERMES_MAX_ITERATIONS",
    "FORECAST_AGENT_MAX_TOOL_ITERATIONS_HARD_MULTIPLIER",
    "FORECAST_RUN_MODE",
    "FORECAST_POLICY_CYCLE_LLM_SPEND",
    "FORECAST_POLICY_CRON_LLM_SPEND",
    "FORECAST_POLICY_INTERACTIVE_LLM_SPEND",
)


@pytest.fixture
def env_only(monkeypatch):
    """Make config reads reflect ONLY os.environ (neutralise any on-disk
    config.yaml) and start from a clean iteration-budget env."""

    import forecasting.appconfig as ac

    monkeypatch.setattr(ac, "get_str", lambda name, default=None: os.environ.get(name, default))
    for name in _FAMILY:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _fake_agent(soft_cap=5, delegate_depth=0, exhausted=False):
    a = types.SimpleNamespace()
    a.max_iterations = soft_cap
    a._iteration_soft_cap = soft_cap
    a.iteration_budget = IterationBudget(soft_cap)
    if exhausted:
        for _ in range(soft_cap):
            a.iteration_budget.consume()
    a._delegate_depth = delegate_depth
    a._checkpoint_continuations = 0
    a._checkpoint_stop_reason = None
    a._checkpoint_hard_ceiling = None
    a._emit_status = lambda *args, **kw: None
    return a


# ── Config resolution ─────────────────────────────────────────────────────────


class TestResolveSoftCap:
    def test_default_is_200(self, env_only):
        assert resolve_max_tool_iterations() == 200
        assert DEFAULT_MAX_TOOL_ITERATIONS == 200

    def test_canonical_key_override(self, env_only):
        env_only.setenv("FORECAST_AGENT_MAX_TOOL_ITERATIONS", "350")
        assert resolve_max_tool_iterations() == 350

    def test_legacy_alias_honoured(self, env_only):
        env_only.setenv("HERMES_MAX_ITERATIONS", "42")
        assert resolve_max_tool_iterations() == 42

    def test_canonical_precedes_legacy(self, env_only):
        env_only.setenv("FORECAST_AGENT_MAX_TOOL_ITERATIONS", "350")
        env_only.setenv("HERMES_MAX_ITERATIONS", "42")
        assert resolve_max_tool_iterations() == 350

    def test_invalid_falls_back_to_default(self, env_only):
        env_only.setenv("FORECAST_AGENT_MAX_TOOL_ITERATIONS", "not-a-number")
        assert resolve_max_tool_iterations() == 200

    def test_nonpositive_falls_back_to_default(self, env_only):
        env_only.setenv("FORECAST_AGENT_MAX_TOOL_ITERATIONS", "0")
        assert resolve_max_tool_iterations() == 200


class TestResolveHardCeiling:
    def test_default_is_10x(self, env_only):
        assert resolve_hard_ceiling(200) == 2000

    def test_multiplier_override(self, env_only):
        env_only.setenv("FORECAST_AGENT_MAX_TOOL_ITERATIONS_HARD_MULTIPLIER", "3")
        assert resolve_hard_ceiling(200) == 600

    def test_floored_above_soft_cap(self, env_only):
        env_only.setenv("FORECAST_AGENT_MAX_TOOL_ITERATIONS_HARD_MULTIPLIER", "1")
        # 1x would equal the soft cap; the ceiling must leave room to continue.
        assert resolve_hard_ceiling(5) == 6


# ── Pure decision ─────────────────────────────────────────────────────────────


class TestDecision:
    def test_interactive_continues(self):
        d = decide_checkpoint_continuation(
            api_call_count=5, soft_cap=5, hard_ceiling=50,
            interactive=True, policy_allows=False,
        )
        assert d.should_continue and d.reason == "interactive"

    def test_policy_auto_continues_when_unattended(self):
        d = decide_checkpoint_continuation(
            api_call_count=5, soft_cap=5, hard_ceiling=50,
            interactive=False, policy_allows=True,
        )
        assert d.should_continue and d.reason == "policy_auto"

    def test_policy_denied_stops(self):
        d = decide_checkpoint_continuation(
            api_call_count=5, soft_cap=5, hard_ceiling=50,
            interactive=False, policy_allows=False,
        )
        assert not d.should_continue and d.reason == "policy_denied"

    def test_hard_ceiling_stops_even_interactive(self):
        d = decide_checkpoint_continuation(
            api_call_count=50, soft_cap=5, hard_ceiling=50,
            interactive=True, policy_allows=True,
        )
        assert not d.should_continue and d.reason == "hard_ceiling"


# ── loop_should_continue / _checkpoint_and_extend ─────────────────────────────


class TestLoopGate:
    def test_fast_path_no_side_effects(self, env_only):
        agent = _fake_agent(soft_cap=5)
        messages = [{"role": "user", "content": "go"}]
        assert cch.loop_should_continue(agent, messages, 0) is True
        assert len(messages) == 1          # no checkpoint injected
        assert agent.iteration_budget.remaining == 5
        assert agent.max_iterations == 5

    def test_interactive_checkpoint_resets_budget_and_continues(self, env_only):
        env_only.setattr(cch, "_is_unattended_run", lambda: False)  # operator present
        agent = _fake_agent(soft_cap=5, exhausted=True)
        messages = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "x"}]},
            {"role": "tool", "tool_call_id": "x", "content": "res"},
        ]
        assert cch.loop_should_continue(agent, messages, 5) is True
        # Budget was RESET to a fresh window and the cap window extended.
        assert agent.iteration_budget.remaining == 5
        assert agent.max_iterations == 10
        assert agent._checkpoint_continuations == 1
        # The model is asked, inline, for a brief progress note.
        assert messages[-1]["role"] == "user"
        assert "checkpoint" in messages[-1]["content"].lower()

    def test_subagent_is_bounded_not_continued(self, env_only):
        env_only.setattr(cch, "_is_unattended_run", lambda: False)
        agent = _fake_agent(soft_cap=5, delegate_depth=1, exhausted=True)
        messages = [{"role": "user", "content": "go"}]
        assert cch.loop_should_continue(agent, messages, 5) is False
        assert agent._checkpoint_stop_reason == "subagent_bounded"
        assert len(messages) == 1          # no checkpoint injected

    def test_unattended_policy_denied_stops(self, env_only):
        env_only.setattr(cch, "_is_unattended_run", lambda: True)  # unattended
        env_only.setenv("FORECAST_POLICY_CYCLE_LLM_SPEND", "never")
        agent = _fake_agent(soft_cap=5, exhausted=True)
        messages = [{"role": "user", "content": "go"}]
        assert cch.loop_should_continue(agent, messages, 5) is False
        assert agent._checkpoint_stop_reason == "policy_denied"

    def test_unattended_policy_auto_continues(self, env_only):
        env_only.setattr(cch, "_is_unattended_run", lambda: True)  # unattended
        # default CYCLE row is auto ⇒ continues, bounded by spend caps.
        agent = _fake_agent(soft_cap=5, exhausted=True)
        messages = [{"role": "user", "content": "go"}]
        assert cch.loop_should_continue(agent, messages, 5) is True
        assert agent._checkpoint_continuations == 1


class TestLoopResumesUntilCeiling:
    """Drive the gate exactly as the conversation loop does."""

    def _run(self, agent, messages):
        api_call_count = 0
        guard = 0
        while True:
            guard += 1
            assert guard < 10_000, "runaway loop — gate never stopped"
            if not cch.loop_should_continue(agent, messages, api_call_count):
                break
            api_call_count += 1
            agent.iteration_budget.consume()
        return api_call_count

    def test_interactive_stops_only_at_hard_ceiling(self, env_only):
        env_only.setattr(cch, "_is_unattended_run", lambda: False)  # operator present
        soft = 5
        agent = _fake_agent(soft_cap=soft)
        messages = [{"role": "user", "content": "go"}]
        used = self._run(agent, messages)
        ceiling = resolve_hard_ceiling(soft)          # 50
        assert used == ceiling
        assert agent._checkpoint_stop_reason == "hard_ceiling"
        # Checkpointed at every window boundary below the ceiling.
        assert agent._checkpoint_continuations == ceiling // soft - 1  # 9

    def test_unattended_policy_denied_stops_at_first_checkpoint(self, env_only):
        env_only.setattr(cch, "_is_unattended_run", lambda: True)
        env_only.setenv("FORECAST_POLICY_CYCLE_LLM_SPEND", "never")
        soft = 5
        agent = _fake_agent(soft_cap=soft)
        messages = [{"role": "user", "content": "go"}]
        used = self._run(agent, messages)
        assert used == soft                          # ran one window, then stopped
        assert agent._checkpoint_continuations == 0
        assert agent._checkpoint_stop_reason == "policy_denied"


# ── The teaching summary message names the key ────────────────────────────────


class TestSummaryPromptNamesKey:
    def test_plain_cap_names_key(self):
        msg = cch.build_max_iterations_summary_prompt(200, None)
        assert "FORECAST_AGENT_MAX_TOOL_ITERATIONS" in msg
        assert "without calling any more tools" in msg

    def test_policy_denied_names_key_and_policy(self):
        msg = cch.build_max_iterations_summary_prompt(200, "policy_denied")
        assert "FORECAST_AGENT_MAX_TOOL_ITERATIONS" in msg
        assert "FORECAST_POLICY_" in msg

    def test_hard_ceiling_names_multiplier_and_value(self):
        msg = cch.build_max_iterations_summary_prompt(200, "hard_ceiling", 2000)
        assert "FORECAST_AGENT_MAX_TOOL_ITERATIONS_HARD_MULTIPLIER" in msg
        assert "2000" in msg
