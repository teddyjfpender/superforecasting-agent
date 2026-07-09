"""Tests for scripts/check-release-ready.sh and scripts/release.sh (dry-run).

The gate is the shared red/green decision for "cut a release or not", used by
production-release.yml and a pre-tag hook. release.sh is its offline dry-run
twin. These tests pin the red/green cases so a broken gate can't silently green.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "scripts" / "check-release-ready.sh"
RELEASE = REPO_ROOT / "scripts" / "release.sh"


def _run(cmd, **env):
    e = dict(os.environ)
    e.update(env)
    return subprocess.run(
        cmd, cwd=REPO_ROOT, env=e, capture_output=True, text=True, timeout=600
    )


def _pyproject_version() -> str:
    for line in (REPO_ROOT / "pyproject.toml").read_text().splitlines():
        if line.startswith("version = "):
            return line.split('"')[1]
    raise AssertionError("no version in pyproject.toml")


def test_gate_green_for_current_version():
    ver = _pyproject_version()
    r = _run(["bash", str(GATE), "--version", ver])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "READY" in r.stdout
    assert "version consistent" in r.stdout


def test_gate_red_on_version_mismatch():
    r = _run(["bash", str(GATE), "--version", "0.0.99"])
    assert r.returncode == 1
    assert "NOT READY" in r.stdout
    assert "!= pyproject" in r.stdout


def test_gate_red_when_changelog_entry_missing():
    # 3.2.1 is valid semver with no changelog section -> red on the changelog
    # check (and consequently on the version-mismatch check too).
    r = _run(["bash", str(GATE), "--version", "3.2.1"])
    assert r.returncode == 1
    assert "changelog has no non-empty" in r.stdout


def test_gate_red_when_tag_already_exists():
    ver = _pyproject_version()
    tag = f"v{ver}"
    existing = subprocess.run(
        ["git", "tag", "-l", tag], cwd=REPO_ROOT, capture_output=True, text=True
    ).stdout.strip()
    if not existing:
        pytest.skip(f"{tag} is not an existing tag in this checkout")
    r = _run(["bash", str(GATE), "--version", ver])
    assert r.returncode == 1
    assert "already exists" in r.stdout


@pytest.mark.skipif(
    shutil.which("uv") is None or not (REPO_ROOT / "ui-tui" / "dist" / "entry.js").exists(),
    reason="dry-run needs uv + a prebuilt TUI bundle (ui-tui/dist/entry.js)",
)
def test_release_dry_run_produces_full_artifact_set(tmp_path):
    out = tmp_path / "rel"
    py = str(REPO_ROOT / ".venv" / "bin" / "python")
    if not Path(py).exists():
        py = shutil.which("python3") or "python3"
    r = _run(["bash", str(RELEASE), "--out", str(out)], PYTHON=py)
    assert r.returncode == 0, r.stdout + r.stderr
    ver = _pyproject_version()
    expected = [
        f"superforecasting_agent-{ver}-py3-none-any.whl",
        f"superforecasting_agent-{ver}.tar.gz",
        "install.sh",
        "SHA256SUMS",
        "release-manifest.json",
        "RELEASE_NOTES.md",
    ]
    for name in expected:
        assert (out / name).exists(), f"missing {name}\n{r.stdout}"

    # The emitted manifest must validate against the schema and be dry-run
    # (digest null, image aimed at ghcr.io).
    import json

    from scripts import release_manifest as rm

    manifest = json.loads((out / "release-manifest.json").read_text())
    rm.validate_manifest(manifest)
    assert manifest["version"] == ver
    assert manifest["tag"] == f"v{ver}"
    assert manifest["image"]["registry"] == "ghcr.io"
    assert manifest["image"]["digest"] is None
    assert set(manifest["artifacts"]) >= set(rm.REQUIRED_ARTIFACT_ROLES)

    # SHA256SUMS entries must match the manifest hashes.
    sums = {}
    for line in (out / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split()
        sums[name] = digest
    assert sums[manifest["artifacts"]["wheel"]["name"]] == (
        manifest["artifacts"]["wheel"]["sha256"]
    )
