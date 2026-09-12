"""Inject forbidden imports to prove the shipped ownership gates reject them."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest


@pytest.mark.parametrize("source", ["superforecasting_agent.storage.environment", "superforecasting_agent.configuration.authentication", "superforecasting_agent.storage.auth", "agent.model_catalog", "superforecasting_agent.configuration.codex_catalog", "superforecasting_agent.configuration.provider_catalog", "superforecasting_agent.tooling.interrupts", "superforecasting_agent.tooling.web_search", "forecasting.transports.slack", "superforecasting_agent.tooling.prompt_callbacks", "forecasting.application.market_output", "forecasting.sources.watched", "forecasting.sources.evidence", "forecasting.panel_selection", "forecasting.sources.dispatch", "tui_gateway", "protocol", "superforecasting_agent.application", "forecasting.distribution_summary", "superforecasting_agent.constants", "superforecasting_agent.profile_paths", "forecasting.application", "superforecasting_agent.session_context", "superforecasting_agent.platform_registry", "superforecasting_agent.hosting.workers", "superforecasting_agent.hosting.sessions", "superforecasting_agent.hosting.storage", "superforecasting_agent.hosting.configuration", "superforecasting_agent.hosting.registry", "superforecasting_agent.hosting.credentials", "superforecasting_agent.hosting.runtime", "superforecasting_agent.hosting.device_auth", "superforecasting_agent.hosting.commands", "superforecasting_agent.hosting.builds", "superforecasting_agent.hosting.notifications", "superforecasting_agent.application.command_catalog", "superforecasting_agent.tooling.inventory", "superforecasting_agent.storage.configuration", "forecasting.configuration", "forecasting.bayes_toolkit", "forecasting.market_compute", "agent.background_options", "tools.environments.configuration", "superforecasting_agent.tooling.startup_selection"])
def test_presentation_dependency_is_rejected(tmp_path, source):
    root = Path(__file__).resolve().parents[2]
    settings = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    contract = next(c for c in settings["tool"]["importlinter"]["contracts"] if c["source_modules"] == [source])
    modules = {source, "boundary_bridge", *contract["forbidden_modules"]}
    for module in modules:
        folder = tmp_path
        for part in module.split("."):
            folder /= part
            folder.mkdir(exist_ok=True)
            (folder / "__init__.py").touch()
    roots = sorted({m.split(".")[0] for m in modules})
    config = '[tool.importlinter]\nroot_packages = ' + json.dumps(roots) + '\n[[tool.importlinter.contracts]]\n'
    config += '\n'.join(f'{key} = {json.dumps(value)}' for key, value in contract.items())
    (tmp_path / "pyproject.toml").write_text(config, encoding="utf-8")
    entry = tmp_path.joinpath(*source.split("."), "__init__.py")
    if source == "tui_gateway":
        entry = entry.parent / "new_transport.py"
    entry.write_text("import boundary_bridge\n", encoding="utf-8")
    bridge = tmp_path / "boundary_bridge/__init__.py"

    def check():
        return subprocess.run(
            [sys.executable, "-c", "import sys; from importlinter.cli import lint_imports_command; sys.exit(lint_imports_command())", "--no-cache"],
            cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(tmp_path)},
            capture_output=True, text=True, timeout=20,
        )

    clean = check()
    assert clean.returncode == 0, clean.stdout + clean.stderr
    if contract.get("allow_indirect_imports"):
        entry.write_text("import cli\n", encoding="utf-8")
        forbidden_edge = "tui_gateway.new_transport -> cli"
    else:
        bridge.write_text("import cli\n", encoding="utf-8")
        forbidden_edge = "boundary_bridge -> cli"
    broken = check()
    assert broken.returncode != 0, broken.stdout + broken.stderr
    assert "BROKEN" in broken.stdout
    assert forbidden_edge in broken.stdout
