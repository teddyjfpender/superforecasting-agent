"""Tests for scripts/migration_guard.py — the upgrade red/green brain.

The guard is what keeps ``scripts/upgrade.sh`` from silently downgrading a box
or skipping a required schema step. These tests pin every decision branch and
the exit-code contract the shell relies on, so a broken guard can't green a
dangerous upgrade.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import migration_guard as mg

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "scripts" / "migration_guard.py"


# ── pure decision function ────────────────────────────────────────────────

def test_clean_upgrade_proceeds():
    d = mg.evaluate("0.18.0", "0.19.0", "0.17.0")
    assert d.ok and d.code == "ok" and not d.warn
    assert d.exit_code == mg.EXIT_PROCEED


def test_reinstall_same_version_proceeds():
    d = mg.evaluate("0.18.0", "0.18.0", "0.17.0")
    assert d.ok and d.code == "reinstall"


def test_downgrade_is_refused():
    d = mg.evaluate("0.19.0", "0.18.0", "0.17.0")
    assert not d.ok and d.code == "downgrade"
    assert d.exit_code == mg.EXIT_REFUSE


def test_below_min_migration_is_refused():
    # Box last touched by 0.16.0; the new build needs >= 0.18.0 to migrate it.
    d = mg.evaluate("0.16.0", "0.20.0", "0.18.0")
    assert not d.ok and d.code == "below_min_migration"
    assert d.exit_code == mg.EXIT_REFUSE


def test_at_exactly_min_migration_proceeds():
    d = mg.evaluate("0.18.0", "0.20.0", "0.18.0")
    assert d.ok and d.code == "ok"


@pytest.mark.parametrize("current", [None, "", "unknown", "unset", "null"])
def test_unknown_current_proceeds_with_warning(current):
    d = mg.evaluate(current, "0.19.0", "0.17.0")
    assert d.ok and d.warn and d.code == "unknown_current"
    assert d.exit_code == mg.EXIT_PROCEED


@pytest.mark.parametrize("bad", ["0.18", "1.2.3.4", "v0.18.0", "latest", "x.y.z"])
def test_bad_new_or_min_raises(bad):
    with pytest.raises(mg.GuardInputError):
        mg.evaluate("0.18.0", bad, "0.17.0")
    with pytest.raises(mg.GuardInputError):
        mg.evaluate("0.18.0", "0.19.0", bad)


def test_cmp_semver_orders_numerically_not_lexically():
    # 0.9.0 < 0.10.0 numerically (lexical string compare would get this wrong).
    assert mg.cmp_semver("0.9.0", "0.10.0") == -1
    assert mg.cmp_semver("0.10.0", "0.9.0") == 1
    assert mg.cmp_semver("1.0.0", "1.0.0") == 0


# ── CLI + exit-code contract (what upgrade.sh actually calls) ──────────────

def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GUARD), *args],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=REPO_ROOT,
    )


def test_cli_proceed_exit_zero():
    r = _run("--current", "0.18.0", "--new", "0.19.0", "--min-migration", "0.17.0")
    assert r.returncode == mg.EXIT_PROCEED
    assert "PROCEED" in r.stdout


def test_cli_refuse_exit_three():
    r = _run("--current", "0.19.0", "--new", "0.18.0", "--min-migration", "0.17.0")
    assert r.returncode == mg.EXIT_REFUSE
    assert "REFUSE" in r.stdout
    assert "downgrade" in r.stdout


def test_cli_bad_input_exit_two():
    r = _run("--current", "0.18.0", "--new", "notsemver", "--min-migration", "0.17.0")
    assert r.returncode == mg.EXIT_BAD_INPUT


def test_cli_reads_manifest(tmp_path: Path):
    manifest = tmp_path / "release-manifest.json"
    manifest.write_text(
        json.dumps({"version": "0.20.0", "min_migration_version": "0.18.0"}),
        encoding="utf-8",
    )
    # current below min -> refuse.
    r = _run("--current", "0.17.0", "--manifest", str(manifest))
    assert r.returncode == mg.EXIT_REFUSE
    assert "below_min_migration" in r.stdout or "min v0.18.0" in r.stdout
    # current fine -> proceed, and --json emits a parseable decision.
    r = _run("--current", "0.19.0", "--manifest", str(manifest), "--json")
    assert r.returncode == mg.EXIT_PROCEED
    payload = json.loads(r.stdout)
    assert payload["ok"] is True and payload["new"] == "0.20.0"
