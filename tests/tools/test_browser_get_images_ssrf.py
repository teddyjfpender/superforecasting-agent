"""Tests that browser_get_images blocks image data from eval-navigated private pages.

The pre-navigation SSRF guard in ``browser_open`` blocks the agent from *opening*
a private/internal URL, but a JavaScript navigation (e.g. ``location.href = ...``
via ``browser_console``/eval) bypasses it.  ``browser_get_images`` reads page
content by calling the eval command directly, so without its own re-check the
image ``src`` URLs and alt text from a private page would leak.

Ported from upstream security fix 61210097a ("extend private-network guard to
browser_get_images"), adapted to this fork's ``_eval_ssrf_guard_active`` /
``_current_page_private_url`` helpers (the fork lacks the upstream sibling
snapshot/vision/eval rechecks, so this guard is built on the fork's existing
``_url_is_private`` / ``_allow_private_urls`` / ``_is_local_backend`` primitives).
"""

import json

import pytest

from tools import browser_tool

PRIVATE_URL = "http://127.0.0.1:8080/internal"
IMAGES_JS_RESULT = json.dumps([
    {"src": "http://127.0.0.1:8080/logo.png", "alt": "Internal Logo", "width": 200, "height": 100},
])


@pytest.fixture(autouse=True)
def _patches(monkeypatch):
    monkeypatch.setattr(browser_tool, "_is_camofox_mode", lambda: False)
    monkeypatch.setattr(browser_tool, "_last_session_key", lambda key: key)


def _mock_run_success(monkeypatch):
    def _run(task_id, command, args=None, **kwargs):
        return {"success": True, "data": {"result": IMAGES_JS_RESULT}}
    monkeypatch.setattr(browser_tool, "_run_browser_command", _run)


def test_blocks_images_on_private_page(monkeypatch):
    _mock_run_success(monkeypatch)
    monkeypatch.setattr(browser_tool, "_eval_ssrf_guard_active", lambda tid: True)
    monkeypatch.setattr(browser_tool, "_current_page_private_url", lambda tid: PRIVATE_URL)

    result = json.loads(browser_tool.browser_get_images(task_id="test"))
    assert result["success"] is False
    assert "private or internal address" in result["error"]
    assert PRIVATE_URL in result["error"]


def test_allows_images_on_public_page(monkeypatch):
    _mock_run_success(monkeypatch)
    monkeypatch.setattr(browser_tool, "_eval_ssrf_guard_active", lambda tid: True)
    monkeypatch.setattr(browser_tool, "_current_page_private_url", lambda tid: None)

    result = json.loads(browser_tool.browser_get_images(task_id="test"))
    assert result["success"] is True
    assert result["count"] == 1
    assert result["images"][0]["src"] == "http://127.0.0.1:8080/logo.png"


def test_skips_guard_for_local_backend(monkeypatch):
    _mock_run_success(monkeypatch)
    monkeypatch.setattr(browser_tool, "_eval_ssrf_guard_active", lambda tid: False)

    result = json.loads(browser_tool.browser_get_images(task_id="test"))
    assert result["success"] is True
    assert result["count"] == 1


def test_skips_guard_when_private_urls_allowed(monkeypatch):
    _mock_run_success(monkeypatch)
    monkeypatch.setattr(browser_tool, "_eval_ssrf_guard_active", lambda tid: False)

    result = json.loads(browser_tool.browser_get_images(task_id="test"))
    assert result["success"] is True
    assert result["count"] == 1


def test_guard_does_not_block_on_failed_eval(monkeypatch):
    """If the eval itself fails, browser_get_images returns its own error — no guard needed."""
    def _run(task_id, command, args=None, **kwargs):
        return {"success": False, "error": "eval failed"}
    monkeypatch.setattr(browser_tool, "_run_browser_command", _run)

    result = json.loads(browser_tool.browser_get_images(task_id="test"))
    assert result["success"] is False
    assert "eval failed" in result["error"]


# ---------------------------------------------------------------------------
# Helper-level tests: exercise the real guard wiring (not the patched stubs),
# proving the fork's _eval_ssrf_guard_active / _current_page_private_url
# actually gate on backend mode, allow_private_urls, and URL privacy.
# ---------------------------------------------------------------------------


def test_guard_active_only_for_cloud_backend_without_optout(monkeypatch):
    monkeypatch.setattr(browser_tool, "_is_local_backend", lambda: False)
    monkeypatch.setattr(browser_tool, "_allow_private_urls", lambda: False)
    assert browser_tool._eval_ssrf_guard_active("test") is True

    monkeypatch.setattr(browser_tool, "_is_local_backend", lambda: True)
    assert browser_tool._eval_ssrf_guard_active("test") is False

    monkeypatch.setattr(browser_tool, "_is_local_backend", lambda: False)
    monkeypatch.setattr(browser_tool, "_allow_private_urls", lambda: True)
    assert browser_tool._eval_ssrf_guard_active("test") is False


def test_current_page_private_url_detects_private(monkeypatch):
    def _run(task_id, command, args=None, **kwargs):
        return {"success": True, "data": {"result": '"http://127.0.0.1:8080/internal"'}}
    monkeypatch.setattr(browser_tool, "_run_browser_command", _run)
    assert browser_tool._current_page_private_url("test") == "http://127.0.0.1:8080/internal"


def test_current_page_private_url_none_for_public(monkeypatch):
    def _run(task_id, command, args=None, **kwargs):
        return {"success": True, "data": {"result": '"https://example.com/"'}}
    monkeypatch.setattr(browser_tool, "_run_browser_command", _run)
    monkeypatch.setattr(browser_tool, "_url_is_private", lambda url: False)
    assert browser_tool._current_page_private_url("test") is None


def test_end_to_end_blocks_private_image_leak(monkeypatch):
    """Full path with real guard helpers: cloud backend + JS-navigated private page."""
    monkeypatch.setattr(browser_tool, "_is_local_backend", lambda: False)
    monkeypatch.setattr(browser_tool, "_allow_private_urls", lambda: False)

    def _run(task_id, command, args=None, **kwargs):
        # The first eval is the image-extraction JS; the URL recheck eval asks
        # for window.location.href.
        if args and args[0] == "window.location.href":
            return {"success": True, "data": {"result": '"http://127.0.0.1:8080/internal"'}}
        return {"success": True, "data": {"result": IMAGES_JS_RESULT}}

    monkeypatch.setattr(browser_tool, "_run_browser_command", _run)

    result = json.loads(browser_tool.browser_get_images(task_id="test"))
    assert result["success"] is False
    assert "private or internal address" in result["error"]
    assert "127.0.0.1" in result["error"]
