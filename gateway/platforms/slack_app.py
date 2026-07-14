"""Slack app server-side primitives: HTTP Events API signature verification, the OAuth
install flow (code -> bot token -> persisted), and event parsing.

Built on stdlib ``hmac``/``hashlib`` + ``aiohttp`` — NO slack_sdk/bolt dependency — so
multi-workspace install and the HTTP Events transport work even where bolt isn't
installed. Tokens are written in the ``{team_id: {token, team_name}}`` shape that
``gateway/platforms/slack.py:connect()`` already reads, so an OAuth-installed workspace
is picked up automatically (closing the read-only-token gap: the file was read but
never written).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qs
from pathlib import Path
from typing import Any

# Reject requests whose timestamp is older/newer than this (Slack's replay guard).
_REPLAY_WINDOW_SECONDS = 60 * 5

_OAUTH_ACCESS_URL = "https://slack.com/api/oauth.v2.access"


def verify_slack_signature(
    signing_secret: str,
    timestamp: str | int | None,
    body: bytes | str,
    signature: str | None,
    *,
    now: float | None = None,
) -> bool:
    """Verify an inbound Slack request's ``X-Slack-Signature`` (v0 = HMAC-SHA256 of
    ``v0:{timestamp}:{body}``) and reject stale timestamps (replay protection). Uses a
    constant-time compare. Returns False on any missing/malformed input — the security
    boundary FAILS CLOSED."""
    if not signing_secret or not signature or timestamp is None:
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    current = int(time.time()) if now is None else int(now)
    if abs(current - ts) > _REPLAY_WINDOW_SECONDS:
        return False
    body_str = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body)
    basestring = f"v0:{int(timestamp)}:{body_str}"
    expected = "v0=" + hmac.new(
        signing_secret.encode("utf-8"), basestring.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_event_request(body: bytes | str) -> dict[str, Any]:
    """Parse an Events API JSON body; returns ``{}`` on bad JSON (never raises)."""
    try:
        text = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body)
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def url_verification_challenge(payload: dict[str, Any]) -> str | None:
    """The challenge string for Slack's url_verification handshake, else None."""
    if isinstance(payload, dict) and payload.get("type") == "url_verification":
        challenge = payload.get("challenge")
        return str(challenge) if challenge is not None else None
    return None


def _tokens_path() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home() / "slack_tokens.json"


def write_slack_token(
    team_id: str, token: str, *, team_name: str | None = None, path: str | Path | None = None
) -> dict[str, Any]:
    """Merge a workspace's bot token into slack_tokens.json (atomic write), in the
    ``{team_id: {token, team_name}}`` shape slack.py reads. The missing writer half of
    the multi-workspace install."""
    p = Path(path) if path else _tokens_path()
    data: dict[str, Any] = {}
    if p.exists():
        try:
            loaded = json.loads(p.read_text(encoding="utf-8"))
            data = loaded if isinstance(loaded, dict) else {}
        except Exception:
            data = {}
    data[str(team_id)] = {"token": token, "team_name": team_name or str(team_id)}
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(p)
    p.chmod(0o600)
    return data[str(team_id)]


async def exchange_oauth_code(
    client_id: str, client_secret: str, code: str, redirect_uri: str | None = None
) -> dict[str, Any]:
    """Exchange an OAuth ``code`` for a bot token via oauth.v2.access. Returns the
    parsed Slack response ({ok, access_token, team:{id,name}, ...})."""
    import aiohttp

    form = {"client_id": client_id, "client_secret": client_secret, "code": code}
    if redirect_uri:
        form["redirect_uri"] = redirect_uri
    async with aiohttp.ClientSession() as session:
        async with session.post(_OAUTH_ACCESS_URL, data=form) as resp:
            return await resp.json()


async def install_from_oauth_code(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str | None = None,
    *,
    path: str | Path | None = None,
    exchange=exchange_oauth_code,
) -> dict[str, Any]:
    """Full install: exchange the code, then persist the workspace bot token. Returns
    ``{ok, team_id, team_name}`` on success or ``{ok: False, error}``. ``exchange`` is
    injectable for tests."""
    result = await exchange(client_id, client_secret, code, redirect_uri)
    if not isinstance(result, dict) or not result.get("ok"):
        return {"ok": False, "error": (result or {}).get("error", "oauth_failed")}
    token = result.get("access_token") or (result.get("bot") or {}).get("bot_access_token")
    team = result.get("team") or {}
    team_id = team.get("id")
    team_name = team.get("name")
    if not (token and team_id):
        return {"ok": False, "error": "missing_token_or_team"}
    write_slack_token(team_id, token, team_name=team_name, path=path)
    return {"ok": True, "team_id": team_id, "team_name": team_name}


# ── HTTP Events API transport (aiohttp) ───────────────────────────────────────

async def handle_events_request(request, *, signing_secret, on_event=None):
    """aiohttp handler for ``POST /slack/events``: verify the signature, answer the
    url_verification challenge, hand an ``event_callback`` to ``on_event(payload)``,
    and ack within Slack's 3s budget. A bad/absent signature -> 401 (fail closed)."""
    from aiohttp import web

    body = await request.read()
    ts = request.headers.get("X-Slack-Request-Timestamp")
    sig = request.headers.get("X-Slack-Signature")
    if not verify_slack_signature(signing_secret, ts, body, sig):
        return web.Response(status=401, text="invalid signature")
    content_type = request.headers.get("Content-Type", "")
    if "application/x-www-form-urlencoded" in content_type:
        form = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
        if form.get("payload"):
            payload = parse_event_request(form["payload"][0])
        else:
            payload = {key: values[0] if values else "" for key, values in form.items()}
            payload["type"] = "slash_command"
    else:
        payload = parse_event_request(body)
    challenge = url_verification_challenge(payload)
    if challenge is not None:
        return web.json_response({"challenge": challenge})
    if payload and on_event is not None:
        try:
            maybe = on_event(payload)
            if hasattr(maybe, "__await__"):
                await maybe
        except Exception:
            # Signature verification succeeded, but the control plane did not
            # durably accept the delivery. Ask Slack to retry instead of
            # acknowledging work that may be lost.
            return web.Response(status=503, text="delivery not accepted")
    return web.Response(status=200, text="")


async def handle_oauth_request(request, *, client_id, client_secret, redirect_uri=None):
    """aiohttp handler for ``GET /slack/oauth/redirect``: exchange the code + persist the
    workspace token (the install writer)."""
    from aiohttp import web

    code = request.query.get("code")
    if not code:
        return web.Response(status=400, text="missing 'code'")
    result = await install_from_oauth_code(client_id, client_secret, code, redirect_uri)
    if result.get("ok"):
        return web.Response(status=200, text=f"Installed to {result.get('team_name')}. You can close this tab.")
    return web.Response(status=400, text=f"install failed: {result.get('error')}")


def register_slack_routes(app, *, signing_secret, client_id=None, client_secret=None, redirect_uri=None, on_event=None, events_enabled=True):
    """Register the Slack HTTP routes on an existing aiohttp ``web.Application``:
    signed Events routes when ``events_enabled``; the OAuth redirect when credentials
    are provided. Socket Mode disables Events while retaining optional OAuth install."""
    async def _events(request):
        return await handle_events_request(request, signing_secret=signing_secret, on_event=on_event)

    if events_enabled:
        if not signing_secret:
            raise ValueError("Slack Events routes require a signing secret")
        app.router.add_post("/slack/events", _events)
        app.router.add_post("/api/webhooks/slack", _events)
    if client_id and client_secret:
        async def _oauth(request):
            return await handle_oauth_request(request, client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri)

        app.router.add_get("/slack/oauth/redirect", _oauth)
