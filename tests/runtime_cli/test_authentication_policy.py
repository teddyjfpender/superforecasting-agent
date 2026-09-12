"""Shared credential policy agrees with the settings and status surfaces."""

import pytest

from superforecasting_agent.runtime import auth, config


@pytest.mark.parametrize("placeholder", ["changeme", "your_api_key", "***", "   "])
def test_anthropic_inspection_skips_placeholder_before_fallback(
    monkeypatch, placeholder
):
    values = {
        "ANTHROPIC_API_KEY": placeholder,
        "ANTHROPIC_TOKEN": "valid-fallback-token",
    }
    for key in auth.PROVIDER_REGISTRY["anthropic"].api_key_env_vars:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(config, "get_env_value", values.get)
    assert auth.get_anthropic_key() == "valid-fallback-token"


def test_anthropic_inspection_does_not_report_placeholder_as_configured(monkeypatch):
    for key in auth.PROVIDER_REGISTRY["anthropic"].api_key_env_vars:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(config, "get_env_value", lambda key: "changeme")
    assert auth.get_anthropic_key() == ""


def test_compatibility_exports_use_shared_policy_objects():
    from superforecasting_agent.configuration import authentication as policy

    assert auth.PROVIDER_REGISTRY is policy.PROVIDER_REGISTRY
    assert auth.ProviderConfig is policy.ProviderConfig
    assert auth.has_usable_secret is policy.has_usable_secret
    assert auth._resolve_kimi_base_url is policy._resolve_kimi_base_url


def test_plugin_metadata_extends_catalog_without_loading_auth_runtime(tmp_path):
    import subprocess
    import sys

    probe = """
import sys
from types import ModuleType, SimpleNamespace
providers = ModuleType("providers")
providers.list_providers = lambda: [SimpleNamespace(
    name="fixture-vendor", auth_type="api_key", env_vars=("FIXTURE_URL", "FIXTURE_TOKEN"),
    display_name="Fixture", base_url="https://fixture.invalid", aliases=("fixture-alias",),
)]
sys.modules["providers"] = providers
from superforecasting_agent.configuration.authentication import PROVIDER_REGISTRY
row = PROVIDER_REGISTRY["fixture-vendor"]
assert row.api_key_env_vars == ("FIXTURE_TOKEN",)
assert row.base_url_env_var == "FIXTURE_URL"
assert PROVIDER_REGISTRY["fixture-alias"] is row
assert not any(name.startswith("superforecasting_agent.runtime") for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
