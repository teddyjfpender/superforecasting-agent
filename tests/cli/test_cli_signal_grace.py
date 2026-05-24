from cli import _SIGTERM_GRACE_ENV_NAMES, _sigterm_grace_seconds


def test_sigterm_grace_prefers_forecast_native_alias(monkeypatch):
    for name in _SIGTERM_GRACE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SUPERFORECASTING_AGENT_SIGTERM_GRACE", "0.25")
    monkeypatch.setenv("HERMES_SIGTERM_GRACE", "9")

    assert _sigterm_grace_seconds() == 0.25


def test_sigterm_grace_accepts_short_forecast_alias(monkeypatch):
    for name in _SIGTERM_GRACE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FORECAST_SIGTERM_GRACE", "2.75")

    assert _sigterm_grace_seconds() == 2.75


def test_sigterm_grace_invalid_alias_uses_default(monkeypatch):
    for name in _SIGTERM_GRACE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SUPERFORECASTING_AGENT_SIGTERM_GRACE", "not-a-float")

    assert _sigterm_grace_seconds(default=1.25) == 1.25
