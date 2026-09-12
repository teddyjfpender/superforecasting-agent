"""Installation policy is usable before any interface or runtime is initialized."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from superforecasting_agent.installation import (
    get_managed_system,
    require_configuration_writable,
)


@pytest.fixture(autouse=True)
def clean_managed_environment(monkeypatch):
    for name in (
        "SUPERFORECASTING_AGENT_MANAGED", "FORECAST_MANAGED", "HERMES_MANAGED"
    ):
        monkeypatch.delenv(name, raising=False)


def test_marker_is_scoped_to_requested_profile(tmp_path):
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / ".managed").touch()
    unmanaged = tmp_path / "unmanaged"
    assert get_managed_system(managed) == "NixOS"
    with pytest.raises(PermissionError, match="Cannot set quorum defaults"):
        require_configuration_writable("set quorum defaults", home=managed)
    require_configuration_writable(home=unmanaged)
    assert not unmanaged.exists()


def test_native_environment_alias_has_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_MANAGED", "nixos")
    monkeypatch.setenv("FORECAST_MANAGED", "custom manager")
    monkeypatch.setenv("SUPERFORECASTING_AGENT_MANAGED", "homebrew")
    with pytest.raises(PermissionError, match="SUPERFORECASTING_AGENT_MANAGED=homebrew"):
        require_configuration_writable(home=tmp_path)
    monkeypatch.setenv("SUPERFORECASTING_AGENT_MANAGED", " ")
    assert get_managed_system(tmp_path) == "custom manager"
    monkeypatch.delenv("FORECAST_MANAGED")
    assert get_managed_system(tmp_path) == "NixOS"


def test_policy_import_does_not_initialize_consumers(tmp_path):
    env = {**os.environ, "SUPERFORECASTING_AGENT_HOME": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, "-c", """
import sys
from superforecasting_agent.installation import get_managed_system
assert get_managed_system() is None
for prefix in ('superforecasting_agent.runtime', 'agent', 'tools', 'gateway', 'tui_gateway', 'cli', 'forecasting'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules), prefix
"""],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
