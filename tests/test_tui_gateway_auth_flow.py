"""In-TUI device-code auth: auth.start / auth.poll RPCs.

The flow that previously forced users OUT of the TUI ("Run
`superforecasting-agent auth` to re-authenticate") is now drivable in-place:
auth.start returns the verification URL + user code immediately, a gateway
thread polls until the user finishes in the browser, and auth.poll reports
pending/success/failed. Network and persistence are faked at the
codex_device_flow seam.
"""

from __future__ import annotations

import threading
import time

from superforecasting_agent.runtime.codex_device_flow import DeviceCodeGrant
from tui_gateway import server


def _start(params=None):
    return server.handle_request(
        {"id": "1", "method": "auth.start", "params": params or {}}
    )


def _poll(params=None):
    return server.handle_request(
        {"id": "2", "method": "auth.poll", "params": params or {}}
    )


def _fake_grant():
    return DeviceCodeGrant(user_code="ABCD-1234", device_auth_id="dev_1", interval=3)


def _wait_status(target: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = _poll()["result"]
        if result["status"] == target:
            return result
        time.sleep(0.02)
    raise AssertionError(f"auth flow never reached status {target!r}: {_poll()['result']}")


def test_auth_start_returns_code_and_url(monkeypatch):
    import superforecasting_agent.runtime.codex_device_flow as flow

    monkeypatch.setattr(flow, "request_device_code", lambda **kw: _fake_grant())
    # Keep the poller pending so this test only checks the start surface.
    monkeypatch.setattr(flow, "poll_device_token_once", lambda grant, **kw: None)

    resp = _start()
    assert "result" in resp, resp
    result = resp["result"]
    assert result["user_code"] == "ABCD-1234"
    assert result["url"].startswith("https://auth.openai.com/")
    assert result["provider"] == "openai-codex"

    assert _poll()["result"]["status"] == "pending"
    _poll({"cancel": True})
    _wait_status("cancelled")


def test_auth_flow_success_persists_tokens(monkeypatch):
    import superforecasting_agent.runtime.auth as auth_mod
    import superforecasting_agent.runtime.codex_device_flow as flow

    saved = {}
    monkeypatch.setattr(flow, "request_device_code", lambda **kw: _fake_grant())
    monkeypatch.setattr(
        flow,
        "poll_device_token_once",
        lambda grant, **kw: {"authorization_code": "ac", "code_verifier": "cv"},
    )
    monkeypatch.setattr(
        flow,
        "exchange_device_code",
        lambda ac, cv, **kw: {"tokens": {"access_token": "at", "refresh_token": "rt"}},
    )
    monkeypatch.setattr(
        auth_mod,
        "_save_codex_tokens",
        lambda tokens, last_refresh=None, **kw: saved.update(tokens),
    )
    # The poller sleeps `interval` seconds before each poll — shrink it.
    monkeypatch.setattr(
        flow, "request_device_code",
        lambda **kw: DeviceCodeGrant(user_code="ABCD-1234", device_auth_id="dev_1", interval=0),
    )

    resp = _start({"provider": "codex"})  # alias normalizes to openai-codex
    assert "result" in resp, resp

    result = _wait_status("success")
    assert "signed in" in result["message"]
    assert saved == {"access_token": "at", "refresh_token": "rt"}


def test_auth_flow_failure_surfaces_message(monkeypatch):
    import superforecasting_agent.runtime.codex_device_flow as flow

    def boom(grant, **kw):
        raise flow.AuthError("device auth polling returned status 500", provider="openai-codex")

    monkeypatch.setattr(
        flow, "request_device_code",
        lambda **kw: DeviceCodeGrant(user_code="ABCD-1234", device_auth_id="dev_1", interval=0),
    )
    monkeypatch.setattr(flow, "poll_device_token_once", boom)

    assert "result" in _start()
    result = _wait_status("failed")
    assert "500" in result["message"]


def test_auth_success_refreshes_live_agent_credentials(monkeypatch):
    """The core fix: on success, the live agent's credentials are re-resolved
    and applied in place — no TUI restart needed."""
    import superforecasting_agent.runtime.codex_device_flow as flow

    monkeypatch.setattr(
        flow, "request_device_code",
        lambda **kw: DeviceCodeGrant(user_code="ABCD-1234", device_auth_id="dev_1", interval=0),
    )
    monkeypatch.setattr(
        flow, "poll_device_token_once",
        lambda grant, **kw: {"authorization_code": "ac", "code_verifier": "cv"},
    )
    monkeypatch.setattr(
        flow, "exchange_device_code",
        lambda ac, cv, **kw: {"tokens": {"access_token": "fresh_at", "refresh_token": "rt"}},
    )
    monkeypatch.setattr("superforecasting_agent.runtime.auth._save_codex_tokens", lambda *a, **k: None)
    fresh_pool = object()
    monkeypatch.setattr(
        "superforecasting_agent.runtime.runtime_provider.resolve_runtime_provider",
        lambda **kw: {
            "provider": "openai-codex",
            "api_key": "fresh_at",
            "base_url": "https://chatgpt.com/backend-api/codex",
            "api_mode": "codex_responses",
            "credential_pool": fresh_pool,
        },
    )

    switched = {}

    class _FakeAgent:
        provider = "openai-codex"
        model = "gpt-5.4"
        _credential_pool = object()

        def switch_model(self, *, new_model, new_provider, api_key, base_url, api_mode):
            switched.update(
                new_model=new_model, new_provider=new_provider,
                api_key=api_key, base_url=base_url, api_mode=api_mode,
            )

    monkeypatch.setattr(server, "_restart_slash_worker", lambda session: None)
    monkeypatch.setattr(server, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(server, "_session_info", lambda agent: {})
    server._sessions["sid_auth"] = {"agent": _FakeAgent(), "running": False}
    try:
        assert "result" in _start({"provider": "openai-codex", "session_id": "sid_auth"})
        result = _wait_status("success")
        assert result["credentials_applied"] is True
        assert switched["api_key"] == "fresh_at"
        assert switched["new_provider"] == "openai-codex"
        assert server._sessions["sid_auth"]["agent"]._credential_pool is fresh_pool
    finally:
        server._sessions.pop("sid_auth", None)


def test_auth_success_retries_agent_build_that_failed_before_sign_in(monkeypatch):
    """A cached pre-auth initialization failure is cleared and rebuilt."""
    old_ready = threading.Event()
    old_ready.set()
    started = {}
    session = {
        "agent": None,
        "agent_error": "No Codex credentials stored",
        "agent_ready": old_ready,
        "agent_build_started": True,
        "running": False,
    }

    def _fake_start(sid, current):
        started["sid"] = sid
        started["session"] = current

    monkeypatch.setattr(server, "_start_agent_build", _fake_start)
    server._sessions["sid_failed_auth"] = session
    try:
        assert server._refresh_agent_credentials_after_auth(
            "sid_failed_auth", "openai-codex"
        ) is True
        assert session["agent_error"] is None
        assert session["agent_ready"] is not old_ready
        assert session["agent_ready"].is_set() is False
        assert session["agent_build_started"] is False
        assert started == {"sid": "sid_failed_auth", "session": session}
    finally:
        server._sessions.pop("sid_failed_auth", None)


def test_auth_poll_reports_terminal_status_once(monkeypatch):
    """A consumed success is reported exactly once; a second poll sees 'none'
    (so a lingering watcher can't double-print 'signed in')."""
    import superforecasting_agent.runtime.codex_device_flow as flow

    monkeypatch.setattr(
        flow, "request_device_code",
        lambda **kw: DeviceCodeGrant(user_code="ABCD-1234", device_auth_id="dev_1", interval=0),
    )
    monkeypatch.setattr(
        flow, "poll_device_token_once",
        lambda grant, **kw: {"authorization_code": "ac", "code_verifier": "cv"},
    )
    monkeypatch.setattr(
        flow, "exchange_device_code",
        lambda ac, cv, **kw: {"tokens": {"access_token": "at", "refresh_token": "rt"}},
    )
    monkeypatch.setattr("superforecasting_agent.runtime.auth._save_codex_tokens", lambda *a, **k: None)

    assert "result" in _start()
    assert _wait_status("success")["status"] == "success"
    # Already consumed by _wait_status's successful poll → now reports none.
    assert _poll()["result"]["status"] == "none"


def test_auth_start_rejects_unsupported_provider():
    resp = _start({"provider": "anthropic"})
    assert "error" in resp, resp
    assert "/api-key" in resp["error"]["message"]


def test_auth_poll_with_no_flow():
    # Fresh-state behavior: clear any flow left by earlier tests.
    with server._auth_flow_lock:
        server._auth_flow.clear()
    assert _poll()["result"]["status"] == "none"
