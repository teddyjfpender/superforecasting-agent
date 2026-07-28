"""Verification posture of scripts/upgrade.sh + scripts/hetzner-install.sh.

Companion to test_install_release_verify.py: all three installers must share
one fatal-by-default trust rule — a DOWNLOADED wheel is always verified
(missing SHA256SUMS, an un-downloadable SHA256SUMS, a sums file with no entry
for the wheel, and a mismatch all abort with nothing installed; the only
opt-out is ALLOW_UNVERIFIED=1 for a release that genuinely ships no
SHA256SUMS) — while a LOCAL wheel the operator passed in (FORECAST_WHEEL=) is
the operator's own trust decision and installs unverified unless
FORECAST_CHECKSUMS= is supplied. scripts/test-fresh-box.sh depends on the
local-wheel rule, so these tests lock BOTH sides of it.

Same hermetic approach as the sibling file: the real scripts run under a
controlled PATH where curl/sudo/pipx/id/getent/chown/install are fakes; the
fake sudo records every invocation so the abort paths can prove pipx was
never reached. Root-only scripts run happily because `id -u` lies. No
network, no root, no system writes: every fatal path exits inside the
verification stage, and the hetzner opt-out/local-wheel paths deterministically
die at the "launcher not found" check — before the script's /usr/local/bin
symlink step — because the fake pipx installs nothing.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPGRADE = ROOT / "scripts" / "upgrade.sh"
HETZNER = ROOT / "scripts" / "hetzner-install.sh"

WHEEL_NAME = "superforecasting_agent-9.9.9-py3-none-any.whl"
WHEEL_BYTES = b"fake wheel payload for verify-consistency tests\n"
WHEEL_SHA = hashlib.sha256(WHEEL_BYTES).hexdigest()

_CURL_SHIM = """#!/usr/bin/env bash
# Serves the fixture release instead of the network. A FAIL_SUMS_DOWNLOAD
# marker file makes the SHA256SUMS fetch fail like a network error.
out=""; url=""; prev=""
for a in "$@"; do
  case "$prev" in -o) out="$a";; esac
  case "$a" in -o) prev="-o"; continue;; -*) prev="";; *) url="$a"; prev="";; esac
done
case "$url" in
  *api.github.com*)       src="$FIXDIR/api.json" ;;
  *SHA256SUMS)            [ -f "$FIXDIR/FAIL_SUMS_DOWNLOAD" ] && exit 22
                          src="$FIXDIR/SHA256SUMS" ;;
  *release-manifest.json) src="$FIXDIR/release-manifest.json" ;;
  *.whl)                  src="$FIXDIR/wheel.whl" ;;
  *) exit 22 ;;
esac
[ -f "$src" ] || exit 22
if [ -n "$out" ]; then cp "$src" "$out"; else cat "$src"; fi
"""

_SUDO_SHIM = """#!/usr/bin/env bash
# Records every invocation (incl. `sudo -u user env ... pipx install ...`);
# the abort paths must never log a pipx install.
echo "FAKE-SUDO: $*" >> "$FIXDIR/sudo-called.log"
exit 0
"""

_PIPX_SHIM = "#!/usr/bin/env bash\nexit 0\n"  # only `command -v pipx` probes it
_ID_SHIM = "#!/usr/bin/env bash\necho 0\n"  # root check + `id forecast` probe
_NOOP_SHIM = "#!/usr/bin/env bash\nexit 0\n"  # chown / install
_GETENT_SHIM = """#!/usr/bin/env bash
echo "forecast:x:501:501:F:$FIXDIR/user-home:/bin/bash"
"""


def _write_release_fixtures(
    fixdir: Path,
    *,
    sums_sha: str | None = WHEEL_SHA,
    with_sums_asset: bool = True,
    with_manifest: bool = True,
) -> None:
    fixdir.mkdir(parents=True, exist_ok=True)
    (fixdir / "wheel.whl").write_bytes(WHEEL_BYTES)
    if sums_sha is not None:
        (fixdir / "SHA256SUMS").write_text(
            f"{sums_sha}  {WHEEL_NAME}\n", encoding="utf-8"
        )
    if with_manifest:
        (fixdir / "release-manifest.json").write_text(
            json.dumps(
                {
                    "version": "9.9.9",
                    "tag": "v9.9.9",
                    "min_migration_version": "0.17.0",
                }
            ),
            encoding="utf-8",
        )
    assets = [f"https://dl.example/{WHEEL_NAME}"]
    if with_sums_asset:
        assets.append("https://dl.example/SHA256SUMS")
    if with_manifest:
        assets.append("https://dl.example/release-manifest.json")
    api = {"assets": [{"browser_download_url": url} for url in assets]}
    (fixdir / "api.json").write_text(json.dumps(api), encoding="utf-8")


def _shim_dir(tmp_path: Path) -> Path:
    shim = tmp_path / "shim"
    shim.mkdir(exist_ok=True)
    for name, body in (
        ("curl", _CURL_SHIM),
        ("sudo", _SUDO_SHIM),
        ("pipx", _PIPX_SHIM),
        ("id", _ID_SHIM),
        ("chown", _NOOP_SHIM),
        ("install", _NOOP_SHIM),
        ("getent", _GETENT_SHIM),
    ):
        p = shim / name
        p.write_text(body, encoding="utf-8")
        p.chmod(0o755)
    py_link = shim / "python3"
    if not py_link.exists():
        py_link.symlink_to(sys.executable)
    return shim


def _run(script: Path, tmp_path: Path, fixdir: Path, extra_env=None):
    shim = _shim_dir(tmp_path)
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir(exist_ok=True)
    fhome = tmp_path / "fhome"
    fhome.mkdir(exist_ok=True)
    if script == UPGRADE:
        (fhome / ".install_method").write_text("pipx\n", encoding="utf-8")
        (fhome / ".release_version").write_text("0.17.0\n", encoding="utf-8")
    env = {
        "PATH": f"{shim}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "TMPDIR": str(tmpdir),
        "FIXDIR": str(fixdir),
        "FORECAST_USER": "forecast",
        "FORECAST_HOME": str(fhome),
        "TAG": "v9.9.9",
    }
    if script == HETZNER:
        env.update({"LANE": "pipx", "SUPERVISOR": "none", "SKIP_HARDENING": "1"})
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        timeout=90,
        env=env,
    )


def _sudo_log(fixdir: Path) -> str:
    log = fixdir / "sudo-called.log"
    return log.read_text(encoding="utf-8") if log.exists() else ""


def test_scripts_parse():
    for script in (UPGRADE, HETZNER):
        subprocess.run(["bash", "-n", str(script)], check=True, timeout=15)


# ── upgrade.sh ──────────────────────────────────────────────────────────────


def test_upgrade_verified_download_upgrades(tmp_path):
    fixdir = tmp_path / "fix"
    _write_release_fixtures(fixdir)
    result = _run(UPGRADE, tmp_path, fixdir)
    assert result.returncode == 0, result.stderr
    assert "wheel sha256 verified (SHA256SUMS)" in result.stdout
    assert "pipx install --force" in _sudo_log(fixdir)


def test_upgrade_checksum_mismatch_refuses(tmp_path):
    fixdir = tmp_path / "fix"
    _write_release_fixtures(fixdir, sums_sha="f" + WHEEL_SHA[1:])
    result = _run(UPGRADE, tmp_path, fixdir)
    assert result.returncode != 0
    assert "MISMATCH" in result.stderr
    assert "pipx install" not in _sudo_log(fixdir)


def test_upgrade_sums_download_failure_refuses(tmp_path):
    # The old code swallowed nothing here but conflated download failure with
    # "mismatch"; now the message names the condition and still refuses.
    fixdir = tmp_path / "fix"
    _write_release_fixtures(fixdir)
    (fixdir / "FAIL_SUMS_DOWNLOAD").write_text("1", encoding="utf-8")
    result = _run(UPGRADE, tmp_path, fixdir)
    assert result.returncode != 0
    assert "SHA256SUMS download failed" in result.stderr
    assert "pipx install" not in _sudo_log(fixdir)


def test_upgrade_missing_sums_refuses_as_pre_p0(tmp_path):
    # Release carries a manifest (so the migration guard passes) but no
    # SHA256SUMS: previously this installed silently unverified; now fatal.
    fixdir = tmp_path / "fix"
    _write_release_fixtures(fixdir, sums_sha=None, with_sums_asset=False)
    result = _run(UPGRADE, tmp_path, fixdir)
    assert result.returncode != 0
    assert "pre-P0" in result.stderr
    assert "pipx install" not in _sudo_log(fixdir)


def test_upgrade_allow_unverified_opt_out(tmp_path):
    fixdir = tmp_path / "fix"
    _write_release_fixtures(fixdir, sums_sha=None, with_sums_asset=False)
    result = _run(UPGRADE, tmp_path, fixdir, {"ALLOW_UNVERIFIED": "1"})
    assert result.returncode == 0, result.stderr
    assert "WITHOUT integrity verification" in result.stdout
    assert "pipx install --force" in _sudo_log(fixdir)


def test_upgrade_local_wheel_stays_operator_trust(tmp_path):
    # FORECAST_WHEEL= (no checksums) must keep installing unverified — the
    # same trust rule test-fresh-box.sh relies on for the bootstrap.
    fixdir = tmp_path / "fix"
    _write_release_fixtures(fixdir)
    local = tmp_path / WHEEL_NAME
    local.write_bytes(WHEEL_BYTES)
    result = _run(UPGRADE, tmp_path, fixdir, {"FORECAST_WHEEL": str(local)})
    assert result.returncode == 0, result.stderr
    assert "pipx install --force" in _sudo_log(fixdir)


def test_upgrade_local_wheel_with_bad_checksums_refuses(tmp_path):
    fixdir = tmp_path / "fix"
    _write_release_fixtures(fixdir)
    local = tmp_path / WHEEL_NAME
    local.write_bytes(WHEEL_BYTES)
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(f"{'f' + WHEEL_SHA[1:]}  {WHEEL_NAME}\n", encoding="utf-8")
    result = _run(
        UPGRADE, tmp_path, fixdir,
        {"FORECAST_WHEEL": str(local), "FORECAST_CHECKSUMS": str(sums)},
    )
    assert result.returncode != 0
    assert "failed verification" in result.stderr
    assert "pipx install" not in _sudo_log(fixdir)


# ── hetzner-install.sh (pipx lane) ──────────────────────────────────────────
# The fatal paths all exit inside resolve_and_verify_wheel — before any pipx
# install and long before the /usr/local/bin symlink step. The proceed paths
# log the pipx install attempt, then deterministically die at "launcher not
# found" (the fake pipx installs nothing), which still proves verification
# was passed or skipped exactly as intended without touching the system.


def test_hetzner_checksum_mismatch_refuses(tmp_path):
    fixdir = tmp_path / "fix"
    _write_release_fixtures(fixdir, sums_sha="f" + WHEEL_SHA[1:], with_manifest=False)
    result = _run(HETZNER, tmp_path, fixdir)
    assert result.returncode != 0
    assert "MISMATCH" in result.stderr
    assert "pipx install" not in _sudo_log(fixdir)


def test_hetzner_sums_download_failure_refuses(tmp_path):
    # Previously `curl ... || true` swallowed this and installed unverified.
    fixdir = tmp_path / "fix"
    _write_release_fixtures(fixdir, with_manifest=False)
    (fixdir / "FAIL_SUMS_DOWNLOAD").write_text("1", encoding="utf-8")
    result = _run(HETZNER, tmp_path, fixdir)
    assert result.returncode != 0
    assert "SHA256SUMS download failed" in result.stderr
    assert "pipx install" not in _sudo_log(fixdir)


def test_hetzner_missing_sums_refuses_as_pre_p0(tmp_path):
    # Previously warn-and-proceed ("installing unverified wheel"); now fatal.
    fixdir = tmp_path / "fix"
    _write_release_fixtures(
        fixdir, sums_sha=None, with_sums_asset=False, with_manifest=False
    )
    result = _run(HETZNER, tmp_path, fixdir)
    assert result.returncode != 0
    assert "pre-P0" in result.stderr
    assert "pipx install" not in _sudo_log(fixdir)


def test_hetzner_allow_unverified_opt_out_reaches_install(tmp_path):
    fixdir = tmp_path / "fix"
    _write_release_fixtures(
        fixdir, sums_sha=None, with_sums_asset=False, with_manifest=False
    )
    result = _run(HETZNER, tmp_path, fixdir, {"ALLOW_UNVERIFIED": "1"})
    assert "WITHOUT integrity verification" in result.stdout
    assert "pipx install --force" in _sudo_log(fixdir)
    # Fake pipx installs nothing, so the script dies AFTER the install attempt.
    assert result.returncode != 0
    assert "launcher not found" in result.stderr


def test_hetzner_local_wheel_without_checksums_stays_operator_trust(tmp_path):
    # The exact shape test-fresh-box.sh STAGE 2 may use: a locally-built wheel
    # with no checksums. Must skip verification and go straight to install.
    fixdir = tmp_path / "fix"
    _write_release_fixtures(fixdir, with_manifest=False)
    local = tmp_path / WHEEL_NAME
    local.write_bytes(WHEEL_BYTES)
    result = _run(HETZNER, tmp_path, fixdir, {"FORECAST_WHEEL": str(local)})
    assert "pipx install --force" in _sudo_log(fixdir)
    assert "verified" not in result.stdout  # no false verification claim
    assert result.returncode != 0
    assert "launcher not found" in result.stderr


def test_hetzner_local_wheel_with_checksums_verifies(tmp_path):
    # The current test-fresh-box.sh STAGE 2 shape: FORECAST_WHEEL +
    # FORECAST_CHECKSUMS. Verification runs and passes, then install proceeds.
    fixdir = tmp_path / "fix"
    _write_release_fixtures(fixdir, with_manifest=False)
    local = tmp_path / WHEEL_NAME
    local.write_bytes(WHEEL_BYTES)
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(f"{WHEEL_SHA}  {WHEEL_NAME}\n", encoding="utf-8")
    result = _run(
        HETZNER, tmp_path, fixdir,
        {"FORECAST_WHEEL": str(local), "FORECAST_CHECKSUMS": str(sums)},
    )
    assert "wheel checksum verified against SHA256SUMS" in result.stdout
    assert "pipx install --force" in _sudo_log(fixdir)


def test_hetzner_local_wheel_with_bad_checksums_refuses(tmp_path):
    fixdir = tmp_path / "fix"
    _write_release_fixtures(fixdir, with_manifest=False)
    local = tmp_path / WHEEL_NAME
    local.write_bytes(WHEEL_BYTES)
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(f"{'f' + WHEEL_SHA[1:]}  {WHEEL_NAME}\n", encoding="utf-8")
    result = _run(
        HETZNER, tmp_path, fixdir,
        {"FORECAST_WHEEL": str(local), "FORECAST_CHECKSUMS": str(sums)},
    )
    assert result.returncode != 0
    assert "failed verification" in result.stderr
    assert "pipx install" not in _sudo_log(fixdir)
