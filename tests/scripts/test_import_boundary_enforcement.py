"""Prove the shipped strict contracts reject a forbidden transitive dependency."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest


@pytest.mark.parametrize("source", ["protocol", "superforecasting_agent.application", "forecasting.distribution_summary", "superforecasting_agent.constants", "superforecasting_agent.profile_paths", "forecasting.application", "superforecasting_agent.session_context", "superforecasting_agent.platform_registry", "superforecasting_agent.hosting.workers", "superforecasting_agent.hosting.sessions", "superforecasting_agent.hosting.storage", "superforecasting_agent.hosting.configuration", "superforecasting_agent.hosting.registry", "superforecasting_agent.hosting.credentials"])
def test_indirect_presentation_dependency_is_rejected(tmp_path, source):
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
    bridge.write_text("import cli\n", encoding="utf-8")
    broken = check()
    assert broken.returncode != 0, broken.stdout + broken.stderr
    assert "BROKEN" in broken.stdout
    assert "boundary_bridge -> cli" in broken.stdout
