"""Slack app server-side primitives — the security-critical signature verification
(fails closed), the OAuth install (code -> token -> persisted), and event parsing."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time

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
