"""Integrity-verification contract of scripts/install-release.sh.

The one-line installer is the first thing a brand-new user pipes into bash, so
it must never install a wheel it cannot verify: it fetches the release's
SHA256SUMS (and release-manifest.json pin) and ABORTS — installing nothing —
on any mismatch. These tests run the real script hermetically: a fake ``curl``
on a controlled PATH serves synthetic release fixtures, and a fake ``pipx``
records whether the install step was ever reached. No network, no real pipx.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "install-release.sh"

WHEEL_NAME = "superforecasting_agent-9.9.9-py3-none-any.whl"
WHEEL_BYTES = b"fake wheel payload for install-release verification tests\n"
WHEEL_SHA = hashlib.sha256(WHEEL_BYTES).hexdigest()

_CURL_SHIM = """#!/usr/bin/env bash
# Serves the fixture release instead of the network. Understands the two call
# shapes install-release.sh uses: `curl -fsSL URL` and `curl -fsSL -o DEST URL`.
out=""; url=""; prev=""
for a in "$@"; do
  case "$prev" in -o) out="$a";; esac
  case "$a" in -o) prev="-o"; continue;; -*) prev="";; *) url="$a"; prev="";; esac
done
case "$url" in
  *api.github.com*)       src="$FIXDIR/api.json" ;;
  *SHA256SUMS)            src="$FIXDIR/SHA256SUMS" ;;
  *release-manifest.json) src="$FIXDIR/release-manifest.json" ;;
  *superforecasting_agent_tui-*.whl) src="$FIXDIR/terminal.whl" ;;
  *.whl)                  src="$FIXDIR/wheel.whl" ;;
  *) exit 22 ;;
esac
[ -f "$src" ] || exit 22
if [ -n "$out" ]; then cp "$src" "$out"; else cat "$src"; fi
"""

_PIPX_SHIM = """#!/usr/bin/env bash
# Records every invocation; the abort paths must never create this log.
echo "FAKE-PIPX CALLED: $*" >> "$FIXDIR/pipx-called.log"
exit 0
"""


def _write_fixtures(
    fixdir: Path,
    *,
    wheel_bytes: bytes = WHEEL_BYTES,
    sums_sha: str | None = WHEEL_SHA,
    manifest_sha: str | None = WHEEL_SHA,
    with_sums_asset: bool = True,
    with_manifest_asset: bool = True,
) -> None:
    fixdir.mkdir(parents=True, exist_ok=True)
    (fixdir / "wheel.whl").write_bytes(wheel_bytes)
    if sums_sha is not None:
        (fixdir / "SHA256SUMS").write_text(
            f"{sums_sha}  {WHEEL_NAME}\n"
            f"{'0' * 64}  superforecasting_agent-9.9.9.tar.gz\n",
            encoding="utf-8",
        )
    if manifest_sha is not None:
        manifest = {
            "version": "9.9.9",
            "tag": "v9.9.9",
            "artifacts": {
                "wheel": {
                    "name": WHEEL_NAME,
                    "sha256": manifest_sha,
                    "size_bytes": len(wheel_bytes),
                }
            },
        }
        (fixdir / "release-manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
    assets = [f"https://dl.example/{WHEEL_NAME}"]
    if with_sums_asset:
        assets.append("https://dl.example/SHA256SUMS")
    if with_manifest_asset:
        assets.append("https://dl.example/release-manifest.json")
    api = {"assets": [{"browser_download_url": url} for url in assets]}
    (fixdir / "api.json").write_text(json.dumps(api), encoding="utf-8")


def _run(tmp_path: Path, fixdir: Path, extra_env: dict[str, str] | None = None):
    shim = tmp_path / "shim"
    shim.mkdir(exist_ok=True)
    (shim / "curl").write_text(_CURL_SHIM, encoding="utf-8")
    (shim / "pipx").write_text(_PIPX_SHIM, encoding="utf-8")
    (shim / "curl").chmod(0o755)
    (shim / "pipx").chmod(0o755)
    py_link = shim / "python3"
    if not py_link.exists():
        py_link.symlink_to(sys.executable)
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir(exist_ok=True)
    # Built from scratch (not os.environ) so an operator's TAG /
    # SUPERFORECASTING_AGENT_RELEASE_TAG / MANIFEST can never leak in.
    env = {
        "PATH": f"{shim}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "TMPDIR": str(tmpdir),
        "FIXDIR": str(fixdir),
        "TAG": "v9.9.9",
    }
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


def _pipx_log(fixdir: Path) -> str | None:
    log = fixdir / "pipx-called.log"
    return log.read_text(encoding="utf-8") if log.exists() else None


def test_installer_parses():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True, timeout=15)


def test_unsupported_python_fails_before_network(tmp_path):
    shim = tmp_path / "shim"
    shim.mkdir()
    fake_python = "#!/usr/bin/env bash\nexit 1\n"
    for name in ("python3", "python"):
        path = shim / name
        path.write_text(fake_python, encoding="utf-8")
        path.chmod(0o755)

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=15,
        env={"PATH": f"{shim}:/usr/bin:/bin", "HOME": str(tmp_path)},
    )

    assert result.returncode != 0
    assert "Python 3.11-3.13 is required" in result.stderr


def test_verified_wheel_installs(tmp_path):
    fixdir = tmp_path / "fix"
    _write_fixtures(fixdir)
    result = _run(tmp_path, fixdir)
    assert result.returncode == 0, result.stderr
    assert "Wheel sha256 verified (SHA256SUMS)" in result.stdout
    assert "matches the release-manifest.json pin" in result.stdout
    log = _pipx_log(fixdir)
    assert log is not None and "install --force" in log and WHEEL_NAME in log
    assert (tmp_path / "home" / ".superforecasting-agent" / ".install_method").read_text() == "release\n"


def test_corrupted_wheel_aborts_and_installs_nothing(tmp_path):
    fixdir = tmp_path / "fix"
    _write_fixtures(fixdir, wheel_bytes=WHEEL_BYTES + b"tampered")
    result = _run(tmp_path, fixdir)
    assert result.returncode != 0
    assert "MISMATCH" in result.stderr
    assert _pipx_log(fixdir) is None, "pipx must never run on a checksum mismatch"


def test_corrupted_checksum_line_aborts_and_installs_nothing(tmp_path):
    fixdir = tmp_path / "fix"
    _write_fixtures(fixdir, sums_sha="f" + WHEEL_SHA[1:], manifest_sha=WHEEL_SHA)
    result = _run(tmp_path, fixdir)
    assert result.returncode != 0
    assert "MISMATCH" in result.stderr
    assert _pipx_log(fixdir) is None


def test_sums_without_wheel_entry_aborts(tmp_path):
    fixdir = tmp_path / "fix"
    _write_fixtures(fixdir)
    (fixdir / "SHA256SUMS").write_text(
        f"{'0' * 64}  some-other-file.tar.gz\n", encoding="utf-8"
    )
    result = _run(tmp_path, fixdir)
    assert result.returncode != 0
    assert "no entry for" in result.stdout
    assert _pipx_log(fixdir) is None


def test_manifest_pin_mismatch_aborts(tmp_path):
    # SHA256SUMS agrees with the wheel but the manifest pins a different
    # sha256 — an inconsistent artifact set must not install.
    fixdir = tmp_path / "fix"
    _write_fixtures(fixdir, manifest_sha="f" + WHEEL_SHA[1:])
    result = _run(tmp_path, fixdir)
    assert result.returncode != 0
    assert "release-manifest.json pin" in result.stderr
    assert _pipx_log(fixdir) is None


def test_missing_sha256sums_aborts_as_pre_p0(tmp_path):
    fixdir = tmp_path / "fix"
    _write_fixtures(
        fixdir, sums_sha=None, manifest_sha=None,
        with_sums_asset=False, with_manifest_asset=False,
    )
    result = _run(tmp_path, fixdir)
    assert result.returncode != 0
    assert "pre-P0" in result.stderr
    assert _pipx_log(fixdir) is None


def test_allow_unverified_opt_out_installs_with_loud_warning(tmp_path):
    fixdir = tmp_path / "fix"
    _write_fixtures(
        fixdir, sums_sha=None, manifest_sha=None,
        with_sums_asset=False, with_manifest_asset=False,
    )
    result = _run(tmp_path, fixdir, {"ALLOW_UNVERIFIED": "1"})
    assert result.returncode == 0, result.stderr
    assert "WITHOUT integrity verification" in result.stdout
    assert _pipx_log(fixdir) is not None


def test_local_manifest_pins_the_tag(tmp_path):
    fixdir = tmp_path / "fix"
    _write_fixtures(fixdir)
    local = tmp_path / "release-manifest.json"
    local.write_text(
        (fixdir / "release-manifest.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    result = _run(tmp_path, fixdir, {"TAG": "", "MANIFEST": str(local)})
    assert result.returncode == 0, result.stderr
    assert "Pinned by manifest: v9.9.9" in result.stdout
    assert _pipx_log(fixdir) is not None


def test_local_manifest_conflicting_tag_aborts(tmp_path):
    fixdir = tmp_path / "fix"
    _write_fixtures(fixdir)
    local = tmp_path / "release-manifest.json"
    local.write_text(
        (fixdir / "release-manifest.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    result = _run(tmp_path, fixdir, {"TAG": "v8.8.8", "MANIFEST": str(local)})
    assert result.returncode != 0
    assert "conflicts" in result.stderr
    assert _pipx_log(fixdir) is None


TUI_NAME = "superforecasting_agent_tui-0.1.0-py3-none-any.whl"
TUI_BYTES = b"separate terminal payload\n"


def _split_release(fixdir: Path) -> None:
    _write_fixtures(fixdir)
    (fixdir / "terminal.whl").write_bytes(TUI_BYTES)
    manifest_path = fixdir / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"]["terminal_wheel"] = {
        "name": TUI_NAME,
        "sha256": hashlib.sha256(TUI_BYTES).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest))
    sums = fixdir / "SHA256SUMS"
    sums.write_text(sums.read_text() + f"{hashlib.sha256(TUI_BYTES).hexdigest()}  {TUI_NAME}\n")
    api_path = fixdir / "api.json"
    api = json.loads(api_path.read_text())
    api["assets"].insert(0, {"browser_download_url": f"https://dl.example/{TUI_NAME}"})
    api_path.write_text(json.dumps(api))


def test_split_release_installs_manifest_backend_then_companion(tmp_path):
    fixdir = tmp_path / "fix"
    _split_release(fixdir)
    result = _run(tmp_path, fixdir)
    assert result.returncode == 0, result.stderr
    log = _pipx_log(fixdir)
    assert f"/{WHEEL_NAME}" in log
    assert f"inject --force superforecasting-agent " in log
    assert f"/{TUI_NAME}" in log
    assert log.index("install --force") < log.index("inject --force")


def test_corrupt_companion_prevents_backend_install(tmp_path):
    fixdir = tmp_path / "fix"
    _split_release(fixdir)
    (fixdir / "terminal.whl").write_bytes(b"corrupt")
    result = _run(tmp_path, fixdir)
    assert result.returncode != 0
    assert "MISMATCH" in result.stderr
    assert _pipx_log(fixdir) is None


def test_backend_only_does_not_download_or_install_companion(tmp_path):
    fixdir = tmp_path / "fix"
    _split_release(fixdir)
    (fixdir / "terminal.whl").unlink()
    result = _run(tmp_path, fixdir, {"INSTALL_TUI": "0"})
    assert result.returncode == 0, result.stderr
    assert "inject" not in _pipx_log(fixdir)
    assert TUI_NAME not in _pipx_log(fixdir)
    assert "--tui" not in result.stdout


def test_duplicate_companion_asset_prevents_install(tmp_path):
    fixdir = tmp_path / "fix"
    _split_release(fixdir)
    api_path = fixdir / "api.json"
    api = json.loads(api_path.read_text())
    api["assets"].append(api["assets"][0])
    api_path.write_text(json.dumps(api))
    result = _run(tmp_path, fixdir)
    assert result.returncode != 0
    assert "duplicate terminal wheel" in result.stderr
    assert _pipx_log(fixdir) is None


def test_companion_manifest_mismatch_prevents_backend_install(tmp_path):
    fixdir = tmp_path / "fix"
    _split_release(fixdir)
    path = fixdir / "release-manifest.json"
    manifest = json.loads(path.read_text())
    manifest["artifacts"]["terminal_wheel"]["sha256"] = "0" * 64
    path.write_text(json.dumps(manifest))
    result = _run(tmp_path, fixdir)
    assert result.returncode != 0
    assert "manifest sha256 MISMATCH" in result.stderr
    assert _pipx_log(fixdir) is None


def test_missing_companion_prevents_backend_install(tmp_path):
    fixdir = tmp_path / "fix"
    _split_release(fixdir)
    path = fixdir / "api.json"
    api = json.loads(path.read_text())
    api["assets"].pop(0)
    path.write_text(json.dumps(api))
    result = _run(tmp_path, fixdir)
    assert result.returncode != 0
    assert "Missing or duplicate terminal wheel" in result.stderr
    assert _pipx_log(fixdir) is None


def test_duplicate_checksum_entry_prevents_install(tmp_path):
    fixdir = tmp_path / "fix"
    _write_fixtures(fixdir)
    path = fixdir / "SHA256SUMS"
    path.write_text(path.read_text() + f"{WHEEL_SHA}  {WHEEL_NAME}\n")
    result = _run(tmp_path, fixdir)
    assert result.returncode != 0
    assert _pipx_log(fixdir) is None
