"""Regression tests for browser session cleanup and screenshot recovery."""

import logging
from unittest.mock import patch


class TestScreenshotPathRecovery:
    def test_extracts_standard_absolute_path(self):
        from tools.browser_tool import _extract_screenshot_path_from_text

        assert (
            _extract_screenshot_path_from_text("Screenshot saved to /tmp/foo.png")
            == "/tmp/foo.png"
        )

    def test_extracts_quoted_absolute_path(self):
        from tools.browser_tool import _extract_screenshot_path_from_text

        assert (
            _extract_screenshot_path_from_text(
                "Screenshot saved to '/Users/david/.hermes/browser_screenshots/shot.png'"
            )
            == "/Users/david/.hermes/browser_screenshots/shot.png"
        )


class TestBrowserCleanup:
    def setup_method(self):
        from tools import browser_tool

        self.browser_tool = browser_tool
        self.orig_active_sessions = browser_tool._active_sessions.copy()
        self.orig_session_last_activity = browser_tool._session_last_activity.copy()
        self.orig_recording_sessions = browser_tool._recording_sessions.copy()
        self.orig_cleanup_done = browser_tool._cleanup_done

    def teardown_method(self):
        self.browser_tool._active_sessions.clear()
        self.browser_tool._active_sessions.update(self.orig_active_sessions)
        self.browser_tool._session_last_activity.clear()
        self.browser_tool._session_last_activity.update(self.orig_session_last_activity)
        self.browser_tool._recording_sessions.clear()
        self.browser_tool._recording_sessions.update(self.orig_recording_sessions)
        self.browser_tool._cleanup_done = self.orig_cleanup_done

    def test_cleanup_browser_clears_tracking_state(self):
        browser_tool = self.browser_tool
        browser_tool._active_sessions["task-1"] = {
            "session_name": "sess-1",
            "bb_session_id": None,
        }
        browser_tool._session_last_activity["task-1"] = 123.0

        with (
            patch("tools.browser_tool._maybe_stop_recording") as mock_stop,
            patch(
                "tools.browser_tool._run_browser_command",
                return_value={"success": True},
            ) as mock_run,
            patch("tools.browser_tool.os.path.exists", return_value=False),
        ):
            browser_tool.cleanup_browser("task-1")

        assert "task-1" not in browser_tool._active_sessions
        assert "task-1" not in browser_tool._session_last_activity
        mock_stop.assert_called_once_with("task-1", session_info={"session_name": "sess-1", "bb_session_id": None})
        mock_run.assert_called_once_with(
            "task-1",
            "close",
            [],
            timeout=10,
            _session_info={"session_name": "sess-1", "bb_session_id": None},
        )

    def test_cleanup_camofox_managed_persistence_skips_close(self):
        """When camofox mode + managed persistence, soft_cleanup fires instead of close."""
        browser_tool = self.browser_tool
        browser_tool._active_sessions["task-1"] = {
            "session_name": "sess-1",
            "bb_session_id": None,
        }
        browser_tool._session_last_activity["task-1"] = 123.0

        with (
            patch("tools.browser_tool._is_camofox_mode", return_value=True),
            patch("tools.browser_tool._maybe_stop_recording") as mock_stop,
            patch(
                "tools.browser_tool._run_browser_command",
                return_value={"success": True},
            ),
            patch("tools.browser_tool.os.path.exists", return_value=False),
            patch(
                "tools.browser_camofox.camofox_soft_cleanup",
                return_value=True,
            ) as mock_soft,
            patch("tools.browser_camofox.camofox_close", return_value='{"success": true, "closed": true}') as mock_close,
        ):
            browser_tool.cleanup_browser("task-1")

        mock_soft.assert_called_once_with("task-1")
        mock_close.assert_not_called()

    def test_cleanup_camofox_no_persistence_calls_close(self):
        """When camofox mode but managed persistence is off, camofox_close fires."""
        browser_tool = self.browser_tool
        browser_tool._active_sessions["task-1"] = {
            "session_name": "sess-1",
            "bb_session_id": None,
        }
        browser_tool._session_last_activity["task-1"] = 123.0

        with (
            patch("tools.browser_tool._is_camofox_mode", return_value=True),
            patch("tools.browser_tool._maybe_stop_recording") as mock_stop,
            patch(
                "tools.browser_tool._run_browser_command",
                return_value={"success": True},
            ),
            patch("tools.browser_tool.os.path.exists", return_value=False),
            patch(
                "tools.browser_camofox.camofox_soft_cleanup",
                return_value=False,
            ) as mock_soft,
            patch("tools.browser_camofox.camofox_close", return_value='{"success": true, "closed": true}') as mock_close,
        ):
            browser_tool.cleanup_browser("task-1")

        mock_soft.assert_called_once_with("task-1")
        mock_close.assert_called_once_with("task-1")

    def test_emergency_cleanup_clears_all_tracking_state(self):
        browser_tool = self.browser_tool
        browser_tool._cleanup_done = False
        browser_tool._active_sessions["task-1"] = {"session_name": "sess-1"}
        browser_tool._active_sessions["task-2"] = {"session_name": "sess-2"}
        browser_tool._session_last_activity["task-1"] = 1.0
        browser_tool._session_last_activity["task-2"] = 2.0
        browser_tool._recording_sessions.update({"task-1", "task-2"})

        with (
            patch("tools.browser_tool._run_browser_command", return_value={"success": True}),
            patch("tools.browser_tool.os.path.exists", return_value=False),
            patch("tools.browser_tool._reap_orphaned_browser_sessions"),
        ):
            browser_tool._emergency_cleanup_all_sessions()

        assert browser_tool._active_sessions == {}
        assert browser_tool._session_last_activity == {}
        assert browser_tool._recording_sessions == set()
        assert browser_tool._cleanup_done is True

    def test_atexit_cleanup_restores_logging_state(self):
        browser_tool = self.browser_tool
        previous_disable = logging.root.manager.disable

        with patch("tools.browser_tool._emergency_cleanup_all_sessions") as cleanup:
            browser_tool._atexit_cleanup_browser_sessions()

        cleanup.assert_called_once_with()
        assert logging.root.manager.disable == previous_disable


def test_emergency_cleanup_retains_failed_owner_and_retries(monkeypatch):
    from tools import browser_tool as bt
    from unittest.mock import Mock

    handle = {"session_name": "", "bb_session_id": "remote-id"}
    disposer = Mock(side_effect=[RuntimeError("provider unavailable"), True])
    handle.update(_cloud_provider=object(), _close_cloud_session=disposer)
    monkeypatch.setattr(bt, "_active_sessions", {"task": handle})
    monkeypatch.setattr(bt, "_session_last_activity", {"task": 1.0})
    monkeypatch.setattr(bt, "_recording_sessions", set())
    monkeypatch.setattr(bt, "_cleanup_done", False)
    monkeypatch.setattr(bt, "_stop_cdp_supervisor", lambda _: None)
    monkeypatch.setattr(bt, "_is_camofox_mode", lambda: False)
    monkeypatch.setattr(bt, "_run_browser_command", lambda *a, **k: {"success": True})
    monkeypatch.setattr(bt, "_reap_orphaned_browser_sessions", lambda: None)

    bt._emergency_cleanup_all_sessions()
    assert bt._active_sessions["task"] is handle
    assert bt._cleanup_done is False
    bt._emergency_cleanup_all_sessions()
    assert bt._active_sessions == {}
    assert bt._cleanup_done is True
    bt._emergency_cleanup_all_sessions()
    assert disposer.call_count == 2
