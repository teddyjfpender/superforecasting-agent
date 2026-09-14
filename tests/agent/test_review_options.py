"""Review budgets and routing preserve ownership without borrowing credentials."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent import review_options as options


def parent():
    return SimpleNamespace(
        model="main-model",
        provider="main-provider",
        max_tokens=8000,
        reasoning_config={"effort": "high"},
        _credential_pool=object(),
        _current_main_runtime=lambda: {
            "api_key": "parent-secret",
            "base_url": "https://parent.invalid",
            "api_mode": "chat_completions",
        },
    )


def test_default_review_inherits_runtime_without_resolution(monkeypatch):
    resolve = Mock(side_effect=AssertionError("unnecessary resolution"))
    monkeypatch.setattr(options, "resolve_runtime_provider", resolve)
    p = parent()
    result, routed = options.review_options(p, {})
    assert not routed and result["api_key"] == "parent-secret"
    assert result["credential_pool"] is p._credential_pool
    assert result["reasoning_config"] == {"effort": "high"}
    assert result["max_iterations"] == 16 and result["max_tokens"] == 8000


def test_routed_review_uses_own_credentials_and_explicit_budgets(monkeypatch):
    resolve = Mock(
        return_value={"api_key": "review-secret", "provider": "review-provider"}
    )
    monkeypatch.setattr(options, "resolve_runtime_provider", resolve)
    cfg = {
        "auxiliary": {
            "background_review": {
                "provider": "review-provider",
                "model": "review-model",
                "reasoning_effort": "low",
                "max_tokens": 1000,
                "max_iterations": 3,
            }
        }
    }
    result, routed = options.review_options(parent(), cfg)
    assert routed and result["api_key"] == "review-secret"
    assert result["credential_pool"] is None and result["reasoning_config"] == {
        "enabled": True,
        "effort": "low",
    }
    assert result["max_tokens"] == 1000 and result["max_iterations"] == 3
    assert resolve.call_args.kwargs["explicit_api_key"] == ""
    assert resolve.call_args.kwargs["explicit_base_url"] == ""


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_iterations", True),
        ("max_iterations", 0),
        ("max_tokens", -1),
        ("reasoning_effort", "invented"),
        ("model", 23),
    ],
)
def test_invalid_review_configuration_fails_before_construction(field, value):
    with pytest.raises(ValueError, match="background_review"):
        options.review_options(
            parent(), {"auxiliary": {"background_review": {field: value}}}
        )


def test_model_only_review_preserves_live_auth_pool(monkeypatch):
    monkeypatch.setattr(
        options,
        "resolve_runtime_provider",
        Mock(side_effect=AssertionError("must use live auth")),
    )
    p = parent()
    result, routed = options.review_options(
        p, {"auxiliary": {"background_review": {"model": "smaller"}}}
    )
    assert routed and result["model"] == "smaller"
    assert (
        result["api_key"] == "parent-secret"
        and result["credential_pool"] is p._credential_pool
    )


def test_different_provider_requires_an_explicit_compatible_model():
    with pytest.raises(ValueError, match="model is required"):
        options.review_options(
            parent(), {"auxiliary": {"background_review": {"provider": "other"}}}
        )
