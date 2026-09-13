"""Programmatic forecasting selects its model without importing a CLI adapter."""
import builtins
from types import SimpleNamespace

import pytest

from forecasting.market_nightly_forecaster import build_informed_market_forecaster
from forecasting.research_audit import _change_my_mind_coverage


@pytest.mark.parametrize("model", ["test-model", {"default": "test-model"}, {"model": "test-model"}])
def test_model_lookup_does_not_require_presentation(monkeypatch, model):
    monkeypatch.setattr(
        "superforecasting_agent.storage.configuration.read_configuration", lambda: {"model": model}
    )
    imported = builtins.__import__
    forbidden = []

    def guarded(name, *args, **kwargs):
        if name == "superforecasting_agent.runtime.config" or name == "forecasting.cli" or name.startswith("forecasting.cli."):
            forbidden.append(name)
            raise AssertionError("programmatic model lookup imported the CLI")
        return imported(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    calls = []

    def runner(selected, system, user):
        calls.append(selected)
        return '{"covered": [0], "uncovered": []}'

    result = _change_my_mind_coverage(
        runner, None, SimpleNamespace(title="Will X occur?"), ["Evidence of X"], []
    )
    assert result == {"covered": ["Evidence of X"], "uncovered": []}
    assert calls == ["test-model"]

    def factory(**kwargs):
        calls.append(kwargs["model"])
        return SimpleNamespace(
            run_conversation=lambda *args, **kwargs: {"final_response": '{"probability": 0.6}'}
        )

    forecaster = build_informed_market_forecaster(agent_factory=factory)
    assert forecaster({"id": "x", "question": "Will X occur?", "source": "manifold"}) == 0.6
    assert calls == ["test-model", "test-model"]
    assert forbidden == []
