"""Source timeouts must remain finite and preserve alias precedence."""
import pytest
from forecasting import source_adapters


@pytest.fixture(params=[("SOURCE_TIMEOUT", "_source_fetch_timeout", 30.0),
                        ("FRED_TIMEOUT", "_fred_fetch_timeout", 12.0)])
def timeout_config(request, monkeypatch):
    suffix, function, default = request.param
    names = [f"{prefix}_{suffix}" for prefix in ("SUPERFORECASTING_AGENT", "FORECAST", "HERMES")]
    for name in names:
        monkeypatch.delenv(name, raising=False)
    return getattr(source_adapters, function), names, default


@pytest.mark.parametrize("value", ["inf", "Infinity", "1e9999"])
@pytest.mark.parametrize("fallback", [False, True])
def test_nonfinite_source_timeout_uses_fallback(timeout_config, monkeypatch, value, fallback):
    function, names, default = timeout_config
    monkeypatch.setenv(names[0], value)
    if fallback:
        monkeypatch.setenv(names[1], "9")
    assert function() == (9.0 if fallback else default)


def test_native_timeout_keeps_precedence(timeout_config, monkeypatch):
    function, names, _ = timeout_config
    monkeypatch.setenv(names[0], " 2.5 ")
    monkeypatch.setenv(names[1], "9")
    assert function() == 2.5
