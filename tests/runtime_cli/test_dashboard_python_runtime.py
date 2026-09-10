"""The embedded TUI must launch the same Python runtime as the CLI."""

import os
import sys

from superforecasting_agent.runtime import main, web_server


def test_dashboard_uses_current_python_and_source_root(monkeypatch, tmp_path):
    for prefix in ("SUPERFORECASTING_AGENT", "FORECAST", "HERMES"):
        for name in ("PYTHON", "PYTHON_SRC_ROOT", "CWD"):
            monkeypatch.delenv(f"{prefix}_{name}", raising=False)
    monkeypatch.delenv("PYTHON", raising=False)
    monkeypatch.setattr(main, "_make_tui_argv", lambda *a, **kw: (["node", "entry.js"], tmp_path / "packaged-tui"))
    _, _, env = web_server._resolve_chat_argv()
    for prefix in ("SUPERFORECASTING_AGENT", "FORECAST", "HERMES"):
        assert env[f"{prefix}_PYTHON"] == sys.executable
        assert env[f"{prefix}_PYTHON_SRC_ROOT"] == str(main.PROJECT_ROOT)
        assert env[f"{prefix}_CWD"] == os.getcwd()


def test_dashboard_preserves_explicit_runtime_overrides(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "_make_tui_argv", lambda *a, **kw: (["node", "entry.js"], tmp_path))
    for name, value in (("PYTHON", "/chosen/python"), ("PYTHON_SRC_ROOT", "/chosen/source"), ("CWD", "/chosen/work")):
        monkeypatch.setenv(f"SUPERFORECASTING_AGENT_{name}", value)
        monkeypatch.setenv(f"HERMES_{name}", "/stale/legacy")
    _, _, env = web_server._resolve_chat_argv()
    assert env["HERMES_PYTHON"] == "/chosen/python"
    assert env["HERMES_PYTHON_SRC_ROOT"] == "/chosen/source"
    assert env["HERMES_CWD"] == "/chosen/work"


def test_keyless_endpoint_does_not_report_failed_credentials():
    from types import SimpleNamespace
    from tui_gateway.server import _probe_credentials

    assert _probe_credentials(SimpleNamespace(api_key="no-key-required", provider="custom")) == ""
    assert _probe_credentials(SimpleNamespace(api_key=lambda: "token", provider="azure")) == ""
    assert "No API key" in _probe_credentials(SimpleNamespace(api_key="", provider="custom"))
