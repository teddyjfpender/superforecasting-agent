"""Numerical operations may import optional libraries, never install them."""

import builtins

import pytest

from forecasting import bayes_toolkit, market_compute


@pytest.mark.parametrize("module", [bayes_toolkit, market_compute])
def test_missing_optional_backends_do_not_load_installer(monkeypatch, module):
    original = builtins.__import__
    attempted_install = []

    def without_optional(name, *args, **kwargs):
        if name.startswith("tools"):
            attempted_install.append(name)
            raise AssertionError("domain attempted to load tool installer")
        if name.split(".")[0] in {"numpy", "scipy", "statsmodels"}:
            raise ImportError("optional backend unavailable")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_optional)
    monkeypatch.setattr(module, "_np", None)
    monkeypatch.setattr(module, "_scipy_stats", None)
    monkeypatch.setattr(module, "_scipy_stats_probed", False)
    result = module.ensure_industry_backends()
    assert result["numpy"] is False
    assert result["scipy"] is False
    if module is market_compute:
        monkeypatch.setattr(module, "_sm", None)
        assert module.ensure_econometrics()["statsmodels"] is False
    assert attempted_install == []
