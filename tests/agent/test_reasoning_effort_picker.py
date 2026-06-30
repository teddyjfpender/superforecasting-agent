"""Reasoning-effort selector: capability helper + config→codex-transport path.

Covers the server-side plumbing behind the TUI reasoning-effort picker step:
  * ``model_supports_reasoning_effort`` predicate (which providers/models get
    the effort step),
  * the chosen effort actually reaching the codex transport request as
    ``reasoning.effort`` via the ``parse_reasoning_effort`` config path.
"""

import pytest

from agent.model_metadata import (
    PICKER_REASONING_EFFORTS,
    model_supports_reasoning_effort,
)
from hermes_constants import parse_reasoning_effort


class TestModelSupportsReasoningEffort:
    def test_openai_codex_backend_always_supports(self):
        assert model_supports_reasoning_effort("openai-codex", "gpt-5.4") is True
        assert model_supports_reasoning_effort("openai-api", "gpt-5.4") is True

    def test_grok_allowlisted_model_supports(self):
        # xAI is per-MODEL: effort-capable grok models pass, the rest don't.
        assert model_supports_reasoning_effort("xai", "grok-3-mini") is True
        assert model_supports_reasoning_effort("xai", "grok-4") is False
        assert model_supports_reasoning_effort("xai", "grok-4-fast") is False

    def test_chat_completions_and_anthropic_excluded(self):
        # Non-codex transports do not take the reasoning.effort dial.
        assert model_supports_reasoning_effort("deepseek", "deepseek-chat") is False
        assert model_supports_reasoning_effort("anthropic", "claude-sonnet") is False
        assert model_supports_reasoning_effort("github-copilot", "gpt-5") is False

    def test_github_responses_excluded_by_url(self):
        # GitHub Models rides codex_responses but reasons via github_reasoning_extra.
        assert (
            model_supports_reasoning_effort(
                "openai-api", "gpt-5", base_url="https://models.github.ai/inference"
            )
            is False
        )

    def test_picker_levels(self):
        # The picker offers low/medium/high/xhigh — minimal is clamped, none is
        # handled separately by the /reasoning plumbing.
        assert PICKER_REASONING_EFFORTS == ("low", "medium", "high", "xhigh")
        assert "minimal" not in PICKER_REASONING_EFFORTS
        assert "none" not in PICKER_REASONING_EFFORTS


class TestChosenEffortReachesCodexTransport:
    @pytest.fixture
    def transport(self):
        import agent.transports.codex  # noqa: F401
        from agent.transports import get_transport

        return get_transport("codex_responses")

    @pytest.mark.parametrize("level", ["low", "medium", "high", "xhigh"])
    def test_effort_lands_on_request(self, transport, level):
        # The picker → config path: the chosen level becomes reasoning_config
        # via parse_reasoning_effort, then the transport emits reasoning.effort.
        reasoning_config = parse_reasoning_effort(level)
        assert reasoning_config == {"enabled": True, "effort": level}

        kw = transport.build_kwargs(
            model="gpt-5.4",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            reasoning_config=reasoning_config,
        )
        assert kw.get("reasoning", {}).get("effort") == level

    def test_minimal_is_clamped_to_low(self, transport):
        # The picker omits `minimal`, but if it ever flows in, codex clamps it.
        kw = transport.build_kwargs(
            model="gpt-5.4",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            reasoning_config=parse_reasoning_effort("minimal"),
        )
        assert kw.get("reasoning", {}).get("effort") == "low"

    def test_none_flows_through_to_disable_reasoning(self, transport):
        # Picking "none" on the effort step fires `/reasoning none`, which
        # disables reasoning entirely — the codex transport then sends NO
        # reasoning key at all (switching models must not silently re-enable it).
        reasoning_config = parse_reasoning_effort("none")
        assert reasoning_config == {"enabled": False}

        kw = transport.build_kwargs(
            model="gpt-5.4",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            reasoning_config=reasoning_config,
        )
        assert "reasoning" not in kw


class TestInventoryPayloadHints:
    def test_picker_payload_carries_effort_capability(self):
        from hermes_cli.inventory import _apply_reasoning_hints

        rows = [
            {"slug": "openai-codex", "models": ["gpt-5.4", "gpt-5.4-mini"]},
            {"slug": "deepseek", "models": ["deepseek-chat"]},
            {"slug": "xai", "models": ["grok-4", "grok-3-mini"]},
        ]
        _apply_reasoning_hints(rows)

        codex, deepseek, xai = rows
        assert codex["supports_reasoning_effort"] is True
        assert codex["reasoning_efforts"] == ["low", "medium", "high", "xhigh"]
        # Every codex model is effort-capable, so the per-model list is the full lineup.
        assert codex["reasoning_effort_models"] == ["gpt-5.4", "gpt-5.4-mini"]

        assert deepseek["supports_reasoning_effort"] is False
        assert deepseek["reasoning_efforts"] == []
        assert deepseek["reasoning_effort_models"] == []

        # xAI surfaces the step (provider hint) because at least one listed model
        # is effort-capable, but the PER-MODEL list pins it to grok-3-mini only —
        # grok-4 must skip the dead step in the picker.
        assert xai["supports_reasoning_effort"] is True
        assert xai["reasoning_effort_models"] == ["grok-3-mini"]
