"""Tests for the update check mechanism in superforecasting_agent.runtime.banner."""

from types import SimpleNamespace
import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_version_string_no_v_prefix():
    """__version__ should be bare semver without a 'v' prefix."""
    from superforecasting_agent.runtime import __version__
    assert not __version__.startswith("v"), f"__version__ should not start with 'v', got {__version__!r}"


def test_update_metadata_targets_forecast_package():
    import superforecasting_agent.runtime.banner as banner

    assert banner._UPSTREAM_REPO_URL == "https://github.com/teddyjfpender/superforecasting-agent.git"
    assert banner._UPSTREAM_BRANCH == "superforecasting-agent-snapshot"
    assert banner._RELEASE_URL_BASE == "https://github.com/teddyjfpender/superforecasting-agent/releases/tag"


def test_check_for_updates_uses_cache(tmp_path, monkeypatch):
    """When cache is fresh, check_for_updates should return cached value without calling git."""
    from superforecasting_agent.runtime.banner import check_for_updates

    # Create a fake git repo and fresh cache
    repo_dir = tmp_path / "hermes-agent"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()

    cache_file = tmp_path / ".update_check"
    cache_file.write_text(json.dumps({"ts": time.time(), "behind": 3}))

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    with patch("superforecasting_agent.runtime.banner.subprocess.run") as mock_run:
        result = check_for_updates()

    assert result == 3
    mock_run.assert_not_called()


def test_check_for_updates_expired_cache(tmp_path, monkeypatch):
    """When cache is expired, check_for_updates should call git fetch."""
    from superforecasting_agent.runtime.banner import check_for_updates

    repo_dir = tmp_path / "hermes-agent"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()

    # Write an expired cache (timestamp far in the past)
    cache_file = tmp_path / ".update_check"
    cache_file.write_text(json.dumps({"ts": 0, "behind": 1}))

    mock_result = MagicMock(returncode=0, stdout="5\n")

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    with patch("superforecasting_agent.runtime.banner.subprocess.run", return_value=mock_result) as mock_run:
        result = check_for_updates()

    assert result == 5
    assert mock_run.call_count == 2  # git fetch + git rev-list


def test_check_for_updates_prefers_forecast_revision_env_alias(tmp_path, monkeypatch):
    """Nix-style revision checks should prefer fork-native env aliases."""
    import superforecasting_agent.runtime.banner as banner

    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    monkeypatch.setenv("SUPERFORECASTING_AGENT_REVISION", "forecast-native-rev")
    monkeypatch.setenv("FORECAST_REVISION", "short-forecast-rev")
    monkeypatch.setenv("HERMES_REVISION", "legacy-rev")

    with patch.object(banner, "_check_via_rev", return_value=7) as check_rev:
        result = banner.check_for_updates()

    assert result == 7
    check_rev.assert_called_once_with("forecast-native-rev")


def test_check_for_updates_preserves_legacy_revision_env_alias(tmp_path, monkeypatch):
    """Existing HERMES_REVISION Nix wrappers remain compatible."""
    import superforecasting_agent.runtime.banner as banner

    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_REVISION", "legacy-rev")

    with patch.object(banner, "_check_via_rev", return_value=2) as check_rev:
        result = banner.check_for_updates()

    assert result == 2
    check_rev.assert_called_once_with("legacy-rev")


def test_check_for_updates_no_git_dir(tmp_path, monkeypatch):
    """Uses GitHub Releases when .git does not exist anywhere."""
    import superforecasting_agent.runtime.banner as banner

    monkeypatch.setattr(banner, "get_install_root", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    with patch("superforecasting_agent.runtime.banner.subprocess.run") as mock_run:
        with patch("superforecasting_agent.runtime.banner.check_via_release", return_value=0):
            result = banner.check_for_updates()
    assert result == 0
    mock_run.assert_not_called()


def test_check_for_updates_fallback_to_project_root(tmp_path, monkeypatch):
    """A source install falls back to its installation root for Git updates."""
    import superforecasting_agent.runtime.banner as banner

    project_root = tmp_path / "source"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.setattr(banner, "get_install_root", lambda: project_root)

    # Point HERMES_HOME at a temp dir with no hermes-agent/.git
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    with patch("superforecasting_agent.runtime.banner.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="0\n")
        result = banner.check_for_updates()
    # Should have fallen back to project root and run git commands
    assert mock_run.call_count >= 1


def test_prefetch_non_blocking():
    """prefetch_update_check() should return immediately without blocking."""
    import superforecasting_agent.runtime.banner as banner

    # Reset module state
    banner._update_result = None
    banner._update_check_done = threading.Event()

    with patch.object(banner, "_isolated_update_check", return_value=5):
        start = time.monotonic()
        banner.prefetch_update_check()
        elapsed = time.monotonic() - start

        # Should return almost immediately (well under 1 second)
        assert elapsed < 1.0

        # Wait for the background thread to finish
        banner._update_check_done.wait(timeout=5)
        assert banner._update_result == 5


def test_invalidate_update_cache_clears_all_profiles(tmp_path):
    """_invalidate_update_cache() should delete .update_check from ALL profiles."""
    from superforecasting_agent.runtime.main import _invalidate_update_cache

    # Build a fake ~/.hermes with default + two named profiles
    default_home = tmp_path / ".hermes"
    default_home.mkdir()
    (default_home / ".update_check").write_text('{"ts":1,"behind":50}')

    profiles_root = default_home / "profiles"
    for name in ("ops", "dev"):
        p = profiles_root / name
        p.mkdir(parents=True)
        (p / ".update_check").write_text('{"ts":1,"behind":50}')

    with patch.object(Path, "home", return_value=tmp_path), \
         patch.dict(os.environ, {"HERMES_HOME": str(default_home)}):
        _invalidate_update_cache()

    # All three caches should be gone
    assert not (default_home / ".update_check").exists(), "default profile cache not cleared"
    assert not (profiles_root / "ops" / ".update_check").exists(), "ops profile cache not cleared"
    assert not (profiles_root / "dev" / ".update_check").exists(), "dev profile cache not cleared"


def test_invalidate_update_cache_no_profiles_dir(tmp_path):
    """Works fine when no profiles directory exists (single-profile setup)."""
    from superforecasting_agent.runtime.main import _invalidate_update_cache

    default_home = tmp_path / ".hermes"
    default_home.mkdir()
    (default_home / ".update_check").write_text('{"ts":1,"behind":5}')

    with patch.object(Path, "home", return_value=tmp_path), \
         patch.dict(os.environ, {"HERMES_HOME": str(default_home)}):
        _invalidate_update_cache()

    assert not (default_home / ".update_check").exists()


def test_prefetch_shares_in_flight_check_and_completes_on_failure(monkeypatch):
    import superforecasting_agent.runtime.banner as banner

    entered, release = threading.Event(), threading.Event()
    calls = []

    def blocked_check():
        calls.append(1)
        entered.set()
        release.wait(5)
        raise RuntimeError("offline")

    monkeypatch.setattr(banner, "_isolated_update_check", blocked_check)
    try:
        banner.prefetch_update_check()
        assert entered.wait(2)
        worker = banner._update_check_thread
        for _ in range(100):
            banner.prefetch_update_check()
        assert banner._update_check_thread is worker
        assert calls == [1]
    finally:
        release.set()
        if banner._update_check_thread is not None:
            banner._update_check_thread.join(5)
    assert banner._update_check_done.is_set()
    assert banner.get_update_result(0) is None


def test_pending_refresh_does_not_report_previous_result(monkeypatch):
    import superforecasting_agent.runtime.banner as banner
    done = threading.Event()
    monkeypatch.setattr(banner, '_update_check_done', done)
    monkeypatch.setattr(banner, '_update_result', 5)
    assert banner.get_update_result(0) is None
    done.set()
    assert banner.get_update_result(0) == 5


@pytest.mark.parametrize('returncode,output', [(-11, ''), (1, ''), (0, 'not-json'), (0, '{"behind":true}')])
def test_update_probe_failure_is_nonfatal(monkeypatch, returncode, output):
    import superforecasting_agent.runtime.banner as banner
    monkeypatch.setattr(banner.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=returncode, stdout=output))
    assert banner._isolated_update_check() is None


def test_update_probe_transfers_only_valid_result(monkeypatch):
    import superforecasting_agent.runtime.banner as banner
    monkeypatch.setattr(banner.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=0, stdout='{"behind":2,"latest_version":"0.23.0"}'))
    assert banner._isolated_update_check() == 2
    assert banner._latest_version == '0.23.0'
