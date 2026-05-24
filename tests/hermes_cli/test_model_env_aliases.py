from __future__ import annotations

from hermes_cli import model_env


def test_model_env_prefers_forecast_native_runtime_alias(monkeypatch) -> None:
    for name in model_env.MODEL_ENV_NAMES + model_env.INFERENCE_MODEL_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("SUPERFORECASTING_AGENT_MODEL", "anthropic/native-model")
    monkeypatch.setenv("FORECAST_MODEL", "anthropic/short-model")
    monkeypatch.setenv("HERMES_MODEL", "anthropic/legacy-model")

    assert model_env.model_env() == "anthropic/native-model"


def test_inference_model_env_prefers_forecast_native_alias(monkeypatch) -> None:
    for name in model_env.INFERENCE_MODEL_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("SUPERFORECASTING_AGENT_INFERENCE_MODEL", "anthropic/native-model")
    monkeypatch.setenv("FORECAST_INFERENCE_MODEL", "anthropic/short-model")
    monkeypatch.setenv("HERMES_INFERENCE_MODEL", "anthropic/legacy-model")

    assert model_env.inference_model_env() == "anthropic/native-model"


def test_inference_provider_env_prefers_forecast_native_alias(monkeypatch) -> None:
    for name in model_env.INFERENCE_PROVIDER_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("SUPERFORECASTING_AGENT_INFERENCE_PROVIDER", "anthropic")
    monkeypatch.setenv("FORECAST_INFERENCE_PROVIDER", "openrouter")
    monkeypatch.setenv("HERMES_INFERENCE_PROVIDER", "nous")

    assert model_env.inference_provider_env() == "anthropic"


def test_set_env_aliases_sets_all_names() -> None:
    env: dict[str, str] = {}

    model_env.set_env_aliases(env, model_env.INFERENCE_PROVIDER_ENV_NAMES, "openrouter")

    assert env == {
        "SUPERFORECASTING_AGENT_INFERENCE_PROVIDER": "openrouter",
        "FORECAST_INFERENCE_PROVIDER": "openrouter",
        "HERMES_INFERENCE_PROVIDER": "openrouter",
    }
