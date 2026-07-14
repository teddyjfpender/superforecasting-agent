"""Slack app server-side primitives — the security-critical signature verification
(fails closed), the OAuth install (code -> token -> persisted), and event parsing."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import stat
import time
from urllib.parse import quote

from gateway.platforms import slack_app as sa


def _sign(secret: str, ts: str, body: str) -> str:
    base = f"v0:{ts}:{body}"
    return "v0=" + hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()


def test_signature_valid_and_rejects_tamper():
    secret, ts, body = "shh", str(int(time.time())), '{"event":"x"}'
    sig = _sign(secret, ts, body)
    assert sa.verify_slack_signature(secret, ts, body, sig) is True
    assert sa.verify_slack_signature(secret, ts, body + " ", sig) is False  # tampered body
    assert sa.verify_slack_signature("wrong-secret", ts, body, sig) is False  # wrong secret
    assert sa.verify_slack_signature(secret, ts, body, "v0=deadbeef") is False  # forged sig


def test_signature_replay_and_fails_closed_on_bad_input():
    secret, body = "shh", "{}"
    stale = str(int(time.time()) - 9999)
    assert sa.verify_slack_signature(secret, stale, body, _sign(secret, stale, body)) is False  # replay window
    assert sa.verify_slack_signature("", "1", "{}", "v0=x") is False  # no secret -> fail closed
    assert sa.verify_slack_signature(secret, None, "{}", "v0=x") is False
    assert sa.verify_slack_signature(secret, "not-an-int", "{}", "v0=x") is False
    assert sa.verify_slack_signature(secret, "1", "{}", None) is False


def test_signature_accepts_bytes_body():
    secret, ts = "shh", str(int(time.time()))
    body = b'{"event":"y"}'
    sig = _sign(secret, ts, body.decode())
    assert sa.verify_slack_signature(secret, ts, body, sig) is True


def test_url_verification_challenge():
    assert sa.url_verification_challenge({"type": "url_verification", "challenge": "c123"}) == "c123"
    assert sa.url_verification_challenge({"type": "event_callback"}) is None
    assert sa.url_verification_challenge({}) is None


def test_parse_event_request_tolerant():
    assert sa.parse_event_request(b'{"a": 1}') == {"a": 1}
    assert sa.parse_event_request("not json") == {}
    assert sa.parse_event_request(b"[1,2,3]") == {}  # non-dict -> {}


def test_write_slack_token_merges(tmp_path):
    p = tmp_path / "slack_tokens.json"
    sa.write_slack_token("T1", "xoxb-1", team_name="Acme", path=p)
    sa.write_slack_token("T2", "xoxb-2", team_name="Beta", path=p)
    data = json.loads(p.read_text())
    assert data["T1"] == {"token": "xoxb-1", "team_name": "Acme"}
    assert data["T2"]["token"] == "xoxb-2"  # second workspace merged, first preserved
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_socket_mode_can_register_oauth_without_event_routes():
    from aiohttp import web

    app = web.Application()
    sa.register_slack_routes(
        app, signing_secret=None, client_id="id", client_secret="secret",
        events_enabled=False,
    )
    paths = {route.resource.canonical for route in app.router.routes()}
    assert "/slack/oauth/redirect" in paths
    assert "/slack/events" not in paths
    assert "/api/webhooks/slack" not in paths


def test_install_from_oauth_code_persists_token(tmp_path):
    p = tmp_path / "slack_tokens.json"

    async def _exchange(cid, cs, code, redirect):
        assert (cid, cs, code) == ("cid", "cs", "code123")
        return {"ok": True, "access_token": "xoxb-z", "team": {"id": "T9", "name": "Zeta"}}

    out = asyncio.run(sa.install_from_oauth_code("cid", "cs", "code123", path=p, exchange=_exchange))
    assert out == {"ok": True, "team_id": "T9", "team_name": "Zeta"}
    assert json.loads(p.read_text())["T9"]["token"] == "xoxb-z"


def test_install_handles_oauth_error(tmp_path):
    async def _bad(*_a, **_k):
        return {"ok": False, "error": "invalid_code"}

    out = asyncio.run(sa.install_from_oauth_code("c", "s", "x", path=tmp_path / "t.json", exchange=_bad))
    assert out["ok"] is False and out["error"] == "invalid_code"


def test_install_rejects_missing_token(tmp_path):
    async def _no_token(*_a, **_k):
        return {"ok": True, "team": {"id": "T1"}}  # ok but no access_token

    out = asyncio.run(sa.install_from_oauth_code("c", "s", "x", path=tmp_path / "t.json", exchange=_no_token))
    assert out["ok"] is False and out["error"] == "missing_token_or_team"


class _FakeReq:
    def __init__(self, body: bytes, headers: dict, query: dict | None = None):
        self._body = body
        self.headers = headers
        self.query = query or {}

    async def read(self) -> bytes:
        return self._body


def _signed_req(secret: str, payload: dict) -> _FakeReq:
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))
    return _FakeReq(body, {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": _sign(secret, ts, body.decode())})


def test_events_handler_rejects_bad_signature():
    req = _FakeReq(b'{"type":"event_callback"}', {"X-Slack-Request-Timestamp": str(int(time.time())), "X-Slack-Signature": "v0=forged"})
    resp = asyncio.run(sa.handle_events_request(req, signing_secret="shh"))
    assert resp.status == 401


def test_events_handler_answers_url_verification():
    resp = asyncio.run(sa.handle_events_request(_signed_req("shh", {"type": "url_verification", "challenge": "cZ"}), signing_secret="shh"))
    assert resp.status == 200 and "cZ" in resp.text


def test_events_handler_dispatches_event_callback():
    seen: list = []
    resp = asyncio.run(
        sa.handle_events_request(
            _signed_req("shh", {"type": "event_callback", "event": {"type": "message", "text": "hi"}}),
            signing_secret="shh", on_event=lambda p: seen.append(p),
        )
    )
    assert resp.status == 200
    assert seen and seen[0]["type"] == "event_callback"


def test_events_handler_requests_retry_on_acceptance_error():
    def _boom(_payload):
        raise RuntimeError("dispatch blew up")

    resp = asyncio.run(
        sa.handle_events_request(_signed_req("shh", {"type": "event_callback", "event": {}}), signing_secret="shh", on_event=_boom)
    )
    assert resp.status == 503


def test_events_handler_dispatches_signed_form_payload():
    payload = {"type": "block_actions", "actions": [{"action_id": "hermes_deny"}]}
    body = ("payload=" + quote(json.dumps(payload))).encode()
    ts = str(int(time.time()))
    req = _FakeReq(body, {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": _sign("shh", ts, body.decode()),
    })
    seen = []
    resp = asyncio.run(sa.handle_events_request(req, signing_secret="shh", on_event=seen.append))
    assert resp.status == 200
    assert seen == [payload]
