"""Background configuration preserves explicit choices and independent ownership."""

from types import SimpleNamespace

import pytest

from agent.background_options import background_agent_options


@pytest.mark.parametrize("selection", [[], ["forecasting"], None])
def test_selection_inherits_only_when_unset(selection):
    defaults = {"enabled_toolsets": ["web"], "reasoning_config": {"effort": "high"}}
    parent = SimpleNamespace(enabled_toolsets=selection, reasoning_config={})
    result = background_agent_options(parent, "background", defaults)
    assert result["enabled_toolsets"] == (["web"] if selection is None else selection)
    assert result["reasoning_config"] == {}
    result["enabled_toolsets"].append("changed")
    assert defaults["enabled_toolsets"] == ["web"]
    assert parent.enabled_toolsets == selection
    if selection is not None:
        assert "changed" not in selection


def test_background_options_do_not_share_nested_mutable_settings():
    parent = SimpleNamespace(
        providers_allowed=["one"], request_overrides={"nested": {"value": 1}},
        reasoning_config={"budget": {"tokens": 10}},
    )
    store = object()
    result = background_agent_options(parent, "background", {"session_db": store})
    result["providers_allowed"].append("two")
    result["request_overrides"]["nested"]["value"] = 2
    result["reasoning_config"]["budget"]["tokens"] = 20
    assert parent.providers_allowed == ["one"]
    assert parent.request_overrides == {"nested": {"value": 1}}
    assert parent.reasoning_config == {"budget": {"tokens": 10}}
    assert result["session_db"] is store
    assert result["session_id"] == "background"
