from superforecasting_agent.runtime.nous_env import (
    nous_inference_base_url,
    nous_min_key_ttl_seconds,
    nous_portal_base_url,
    nous_timeout_seconds,
)


def test_nous_portal_base_url_prefers_forecast_native_alias(monkeypatch):
    monkeypatch.setenv("NOUS_BASE_URL", "https://base.example/")
    monkeypatch.setenv("HERMES_PORTAL_BASE_URL", "https://legacy.example/")
    monkeypatch.setenv("FORECAST_NOUS_PORTAL_BASE_URL", "https://short.example/")
    monkeypatch.setenv("SUPERFORECASTING_AGENT_NOUS_PORTAL_BASE_URL", "https://native.example/")

    assert nous_portal_base_url("https://default.example") == "https://native.example"


def test_nous_portal_base_url_preserves_provider_alias(monkeypatch):
    monkeypatch.setenv("NOUS_BASE_URL", "https://base.example/")
    monkeypatch.delenv("HERMES_PORTAL_BASE_URL", raising=False)
    monkeypatch.delenv("FORECAST_NOUS_PORTAL_BASE_URL", raising=False)
    monkeypatch.delenv("SUPERFORECASTING_AGENT_NOUS_PORTAL_BASE_URL", raising=False)

    assert nous_portal_base_url("https://default.example") == "https://base.example"


def test_nous_inference_base_url_prefers_forecast_native_alias(monkeypatch):
    monkeypatch.setenv("NOUS_INFERENCE_BASE_URL", "https://legacy-inference.example/")
    monkeypatch.setenv("FORECAST_NOUS_INFERENCE_BASE_URL", "https://short-inference.example/")
    monkeypatch.setenv("SUPERFORECASTING_AGENT_NOUS_INFERENCE_BASE_URL", "https://native-inference.example/")

    assert nous_inference_base_url("https://default.example") == "https://native-inference.example"


def test_nous_runtime_numeric_aliases(monkeypatch):
    monkeypatch.setenv("HERMES_NOUS_MIN_KEY_TTL_SECONDS", "90")
    monkeypatch.setenv("FORECAST_NOUS_MIN_KEY_TTL_SECONDS", "120")
    monkeypatch.setenv("SUPERFORECASTING_AGENT_NOUS_MIN_KEY_TTL_SECONDS", "180")
    monkeypatch.setenv("HERMES_NOUS_TIMEOUT_SECONDS", "3")
    monkeypatch.setenv("FORECAST_NOUS_TIMEOUT_SECONDS", "4")
    monkeypatch.setenv("SUPERFORECASTING_AGENT_NOUS_TIMEOUT_SECONDS", "5.5")

    assert nous_min_key_ttl_seconds() == 180
    assert nous_timeout_seconds() == 5.5


def test_nous_min_key_ttl_seconds_keeps_floor(monkeypatch):
    monkeypatch.setenv("SUPERFORECASTING_AGENT_NOUS_MIN_KEY_TTL_SECONDS", "5")

    assert nous_min_key_ttl_seconds() == 60
