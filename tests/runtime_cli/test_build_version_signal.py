"""The build-version + staleness signal the TUI shows.

Guards a real, expensive regression: an operator ran a pipx-installed v0.17.0
binary for three weeks against a v0.19.0 repo. The wheel lane has no git checkout
and this fork is not on PyPI, so ``check_for_updates()`` could only ever answer
"don't know" — and the TUI showed nothing at all, so nobody found out.

Everything here must hold WITHOUT network access, so every remote call is
stubbed. The one thing these tests must never do is let a real request escape.
"""

import json
import threading
import time
from unittest.mock import patch

import pytest


@pytest.fixture
def banner(tmp_path, monkeypatch):
    """``superforecasting_agent.runtime.banner`` with a scratch agent-home and clean module state."""
    import superforecasting_agent.runtime.banner as mod

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(mod, "_latest_version", None, raising=False)
    monkeypatch.setattr(mod, "_update_result", None, raising=False)
    monkeypatch.setattr(mod, "_update_check_done", threading.Event(), raising=False)
    return mod


# ── the release lane (the pipx / one-line-installer trap) ────────────────────


def test_release_check_resolves_a_bare_semver_from_the_tag(banner):
    """``v0.19.0`` on the wire has to compare against a bare ``__version__``."""
    with patch.object(banner, "_fetch_release_latest", return_value="0.19.0"):
        with patch.object(banner, "VERSION", "0.17.0"):
            assert banner.check_via_release() == banner.UPDATE_AVAILABLE_NO_COUNT
    assert banner._latest_version == "0.19.0"


def test_release_check_is_zero_when_current(banner):
    with patch.object(banner, "_fetch_release_latest", return_value="0.19.0"):
        with patch.object(banner, "VERSION", "0.19.0"):
            assert banner.check_via_release() == 0


def test_release_check_is_none_when_the_feed_is_unreachable(banner):
    """Offline must be "unknown", never "behind" — no false alarm on a plane."""
    with patch.object(banner, "_fetch_release_latest", return_value=None):
        assert banner.check_via_release() is None


def test_latest_prefers_the_shipped_release_manifest(banner):
    """The manifest is a plain asset download, so it survives the API's 60/hour
    unauthenticated rate limit — which a shared/NAT'd network exhausts easily."""
    manifest = {"product": "superforecasting-agent", "version": "0.19.0", "tag": "v0.19.0"}

    def _fake(url, accept):
        assert "release-manifest.json" in url, "the manifest must be tried FIRST"
        return manifest

    with patch.object(banner, "_get_json", _fake):
        assert banner._fetch_release_latest() == "0.19.0"


def test_latest_falls_back_to_the_releases_api(banner):
    """A release older than the manifest still resolves — via the tag, v stripped."""
    seen = []

    def _fake(url, accept):
        seen.append(url)
        return None if "release-manifest.json" in url else {"tag_name": "v0.18.0"}

    with patch.object(banner, "_get_json", _fake):
        assert banner._fetch_release_latest() == "0.18.0"
    assert len(seen) == 2 and "api.github.com" in seen[1]


def test_latest_is_none_when_both_paths_fail(banner):
    """Offline, rate-limited, or a repo with no releases — silence, not an error."""
    with patch.object(banner, "_get_json", lambda url, accept: None):
        assert banner._fetch_release_latest() is None


def test_latest_ignores_a_manifest_for_a_different_product(banner):
    """A wrong-product manifest must not be mistaken for our version."""
    def _fake(url, accept):
        if "release-manifest.json" in url:
            return {"product": "something-else", "version": "9.9.9"}
        return {"tag_name": "v0.19.0"}

    with patch.object(banner, "_get_json", _fake):
        assert banner._fetch_release_latest() == "0.19.0"


def test_get_json_never_raises(banner):
    """Every transport failure has to come back as None, not an exception."""
    import urllib.request

    with patch.object(urllib.request, "urlopen", side_effect=OSError("Network is unreachable")):
        assert banner._get_json("https://example.invalid/x.json", "application/json") is None

    class _Resp:
        def read(self):
            return b"<html>rate limited</html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch.object(urllib.request, "urlopen", lambda *a, **k: _Resp()):
        assert banner._get_json("https://example.invalid/x.json", "application/json") is None


def test_wheel_lane_uses_the_release_feed(banner, tmp_path, monkeypatch):
    """THE regression: no .git — the release feed must answer."""
    fake = tmp_path / "site-packages" / 'superforecasting_agent/runtime' / "banner.py"
    fake.parent.mkdir(parents=True)
    fake.touch()
    monkeypatch.setattr(banner, "get_install_root", lambda: fake.parent.parent)

    with patch.object(banner, "check_via_release", return_value=banner.UPDATE_AVAILABLE_NO_COUNT) as rel:
        assert banner.check_for_updates() == banner.UPDATE_AVAILABLE_NO_COUNT
    rel.assert_called_once()


def test_resolved_latest_survives_in_the_shared_cache(banner, tmp_path):
    """The 6-hour cache carries the version string, so a warm start needs no I/O."""
    with patch.object(banner, "_fetch_release_latest", return_value="0.19.0"):
        with patch.object(banner, "VERSION", "0.17.0"):
            with patch.object(banner, "_check_via_local_git", return_value=None):
                banner.check_for_updates()

    cached = json.loads((tmp_path / ".update_check").read_text())
    assert cached["latest"] == "0.19.0"
    assert cached["behind"] == banner.UPDATE_AVAILABLE_NO_COUNT

    # A fresh process reads it back without touching the network at all.
    banner._latest_version = None
    with patch.object(banner, "_fetch_release_latest", side_effect=AssertionError("no network!")):
        assert banner.check_for_updates() == banner.UPDATE_AVAILABLE_NO_COUNT
    assert banner._latest_version == "0.19.0"


# ── the lane-aware remedy ────────────────────────────────────────────────────


def test_remedy_for_a_checkout_rebuilds_and_reinstalls(banner):
    """A `git pull` alone leaves an installed binary — and its frozen TUI — stale."""
    with patch.object(banner, "_resolve_repo_dir", return_value=banner.Path("/repo")):
        remedy = banner.stale_build_remedy("git")
    assert remedy == "scripts/build-release.sh && pipx install --force dist/*.whl"


def test_remedy_for_a_wheel_is_the_one_line_installer(banner):
    for method in ("pip", "pipx", "unknown"):
        remedy = banner.stale_build_remedy(method)
        assert remedy.startswith("curl -fsSL https://github.com/teddyjfpender/superforecasting-agent")
        assert remedy.endswith("install.sh | bash")


def test_remedy_detects_the_lane_when_not_told_one(banner):
    """``None`` means "work it out" — it must not silently fall through to a wheel."""
    with patch("superforecasting_agent.runtime.config.detect_install_method", return_value="pip"):
        assert banner.stale_build_remedy().startswith("curl -fsSL")
    with patch("superforecasting_agent.runtime.config.detect_install_method", return_value="git"):
        with patch.object(banner, "_resolve_repo_dir", return_value=banner.Path("/repo")):
            assert banner.stale_build_remedy() == "scripts/build-release.sh && pipx install --force dist/*.whl"


def test_remedy_defers_to_the_package_manager_when_managed(banner):
    with patch("superforecasting_agent.runtime.config.get_managed_update_command", return_value="brew upgrade x"):
        assert banner.stale_build_remedy("homebrew") == "brew upgrade x"


# ── get_update_state: the shape on the wire ──────────────────────────────────


def test_update_state_never_blocks_and_never_opens_a_network_path(banner):
    """The startup contract: pure memory + one tiny file read, no sockets."""
    with patch.object(banner, "_fetch_release_latest", side_effect=AssertionError("no network!")):
        start = time.monotonic()
        state = banner.get_update_state()
        elapsed = time.monotonic() - start

    assert elapsed < 0.2, f"get_update_state() blocked for {elapsed:.3f}s"
    assert state["version"]
    assert state["remedy"]


def test_update_state_degrades_silently_when_nothing_resolved(banner):
    """Offline / cold cache: a version, no verdict, and crucially no error."""
    state = banner.get_update_state()

    assert state["stale"] is False
    assert state["latest_version"] is None
    assert state["behind"] is None
    assert state["version"] == banner.VERSION


def test_update_state_reports_the_operator_trap(banner, tmp_path):
    """v0.17.0 installed, v0.19.0 published: stale, named, with a remedy."""
    (tmp_path / ".update_check").write_text(
        json.dumps({"ts": time.time(), "behind": banner.UPDATE_AVAILABLE_NO_COUNT, "latest": "0.19.0"})
    )

    with patch.object(banner, "VERSION", "0.17.0"):
        state = banner.get_update_state()

    assert state["stale"] is True
    assert state["version"] == "0.17.0"
    assert state["latest_version"] == "0.19.0"
    assert state["behind"] == banner.UPDATE_AVAILABLE_NO_COUNT
    assert state["remedy"]


def test_update_state_reads_a_positive_commit_count_from_the_cache(banner, tmp_path):
    (tmp_path / ".update_check").write_text(json.dumps({"ts": time.time(), "behind": 7}))

    state = banner.get_update_state()

    assert state["behind"] == 7
    assert state["stale"] is True


def test_update_state_is_not_stale_when_up_to_date(banner, tmp_path):
    (tmp_path / ".update_check").write_text(
        json.dumps({"ts": time.time(), "behind": 0, "latest": banner.VERSION})
    )

    state = banner.get_update_state()

    assert state["behind"] == 0
    assert state["stale"] is False


def test_update_state_survives_a_corrupt_cache(banner, tmp_path):
    (tmp_path / ".update_check").write_text("{ this is not json")

    state = banner.get_update_state()

    assert state["version"] and state["stale"] is False


# ── the gateway wire ─────────────────────────────────────────────────────────


def test_gateway_build_info_validates_against_the_wire_model():
    from protocol.events.gateway import GatewayReady
    from tui_gateway import server

    payload = server.build_info()
    assert payload["version"]

    frame = GatewayReady.model_validate(
        {"skin": {"name": "aurora"}, "protocol_version": 1, "build": payload}
    )
    assert frame.build is not None
    assert frame.build.version == payload["version"]


def test_gateway_ready_tolerates_a_build_less_frame():
    """An older gateway omits `build` entirely — the TUI must still connect."""
    from protocol.events.gateway import GatewayReady

    assert GatewayReady.model_validate({}).build is None
    assert GatewayReady.model_validate({"build": {"version": "0.1.0"}}).build.stale is None


def test_gateway_build_info_defaults_to_the_non_blocking_read():
    """The startup call must not spend the 0.5s budget session.info is allowed."""
    from tui_gateway import server

    with patch("superforecasting_agent.runtime.banner.get_update_state") as spy:
        spy.return_value = {"version": "0.19.0"}
        server.build_info()

    spy.assert_called_once_with(timeout=0.0)


def test_gateway_build_info_still_names_the_version_if_the_check_explodes():
    from tui_gateway import server

    with patch("superforecasting_agent.runtime.banner.get_update_state", side_effect=RuntimeError("boom")):
        payload = server.build_info()

    assert payload["version"]


def test_session_info_carries_the_build(monkeypatch):
    """session.info lands after the check finishes, so it refreshes the verdict."""
    from tui_gateway import server

    class _Agent:
        model = "gpt-5.5"
        tools: list = []

    monkeypatch.setattr(server, "build_info", lambda timeout=0.0: {"version": "9.9.9", "stale": True})
    info = server._session_info(_Agent())

    assert info["build"] == {"version": "9.9.9", "stale": True}


# ── `forecast doctor` — the thing an operator runs when something looks wrong ─


def _doctor_output(capsys, state):
    from superforecasting_agent.runtime import doctor as doctor_mod

    issues: list[str] = []
    with patch("superforecasting_agent.runtime.banner.prefetch_update_check"):
        with patch("superforecasting_agent.runtime.banner.get_update_state", return_value=state):
            doctor_mod._check_build_version(issues)
    return capsys.readouterr().out, issues


def test_doctor_names_the_running_build_and_its_lane(capsys):
    out, issues = _doctor_output(
        capsys,
        {
            "version": "0.19.0",
            "release_date": "2026.7.24",
            "install_method": "pip",
            "latest_version": "0.19.0",
            "behind": 0,
            "stale": False,
            "remedy": "x",
        },
    )

    assert "Build Version" in out
    assert "Running v0.19.0 (2026.7.24)" in out
    assert "installed via pip" in out
    assert "Up to date" in out
    assert issues == []


def test_doctor_fails_loud_on_a_stale_build_and_prints_the_remedy(capsys):
    out, issues = _doctor_output(
        capsys,
        {
            "version": "0.17.0",
            "release_date": "2026.6.30",
            "install_method": "pip",
            "latest_version": "0.19.0",
            "behind": -1,
            "stale": True,
            "remedy": "curl -fsSL https://example.invalid/install.sh | bash",
        },
    )

    assert "BEHIND the latest release" in out
    assert "latest v0.19.0" in out
    assert "curl -fsSL https://example.invalid/install.sh | bash" in out
    # The trap itself, spelled out — a rebuild alone does not update the binary.
    assert "frozen inside its own venv" in out
    assert issues and "0.17.0" in issues[0]


def test_doctor_says_unknown_rather_than_ok_when_offline(capsys):
    """Never imply the build was VERIFIED current when the feed was unreachable."""
    out, issues = _doctor_output(
        capsys,
        {
            "version": "0.19.0",
            "release_date": None,
            "install_method": "git",
            "latest_version": None,
            "behind": None,
            "stale": False,
            "remedy": "x",
        },
    )

    assert "Could not reach the release feed" in out
    assert "Up to date" not in out
    assert issues == []


def test_doctor_never_raises_when_the_check_explodes(capsys):
    from superforecasting_agent.runtime import doctor as doctor_mod

    issues: list[str] = []
    with patch("superforecasting_agent.runtime.banner.prefetch_update_check", side_effect=RuntimeError("boom")):
        doctor_mod._check_build_version(issues)

    assert "Could not resolve the running build" in capsys.readouterr().out
    assert issues == []


# ── the shipped module marker (the MODULE_TYPELESS_PACKAGE_JSON fix) ─────────


def test_bundled_tui_declares_itself_an_es_module():
    """Without this, Node walks up to the repo-root package.json and warns on stderr
    before first paint. It also has to be BUNDLED, not just present in the tree."""
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    marker = root / 'superforecasting_agent/runtime' / "tui_dist" / "package.json"

    assert marker.exists(), "superforecasting_agent/runtime/tui_dist/package.json is missing"
    assert json.loads(marker.read_text()) == {"type": "module"}

    gitignore = (root / ".gitignore").read_text()
    assert "!superforecasting_agent/runtime/tui_dist/package.json" in gitignore, "the marker would be gitignored"

    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    globs = pyproject["tool"]["setuptools"]["package-data"]["superforecasting_agent.runtime"]
    assert not any(g.startswith("tui_dist/") for g in globs), "the backend must not bundle terminal assets"
    terminal = tomllib.loads((root / "products/tui/pyproject.toml").read_text(encoding="utf-8"))
    assets = terminal["tool"]["setuptools"]["package-data"]["superforecasting_agent_tui"]
    assert "dist/package.json" in assets, "the terminal wheel must ship its ES module marker"
