"""Stdlib Telegram Bot API client — the outbound/probe transport for the
forecast-native Telegram surface.

The gateway's :mod:`gateway.platforms.telegram` adapter owns the long-poll
*inbound* session (and requires ``python-telegram-bot``). This module is the
complementary *outbound + provisioning* client: a token probe (``getMe``), the
chat-binding capture (``getUpdates``), and a message push (``sendMessage``),
each a single POST to ``https://api.telegram.org/bot<token>/<method>`` over
stdlib ``urllib``. That keeps ``forecast connect telegram`` and the notification
router dependency-free and — crucially — testable: :func:`_telegram_api_call`
is the one module-level HTTP seam, monkeypatched in tests so the full
connect→bind→deliver path is proven to the wire without a live bot.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any, Optional

API_ROOT = "https://api.telegram.org"

# python-telegram-bot caps a text message at 4096 chars; keep parity.
MAX_MESSAGE_LENGTH = 4096


def _telegram_api_call(token: str, method: str, timeout: float = 15.0, **params: Any) -> dict[str, Any]:
    """POST to the Telegram Bot API and return the parsed JSON envelope.

    Module-level so tests monkeypatch it without touching the network. Returns
    the raw Telegram envelope (``{"ok": bool, "result"|"description": ...}``).
    Nested values (a chat id, a thread id) are JSON-scalar friendly over the
    urlencoded transport.
    """
    if not token:
        return {"ok": False, "error_code": 401, "description": "no bot token"}
    url = f"{API_ROOT}/bot{token}/{method}"
    payload = {k: v for k, v in params.items() if v is not None}
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https host)
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # 400/401/403/409 carry a JSON body
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:  # pragma: no cover — non-JSON error body
            return {"ok": False, "error_code": exc.code, "description": str(exc)}


def resolve_bot_token(explicit: Optional[str] = None) -> Optional[str]:
    """Resolve the bot token: an explicit value, else ``TELEGRAM_BOT_TOKEN``."""
    tok = (explicit or "").strip()
    if tok:
        return tok
    env = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    return env or None


def get_me(token: str) -> dict[str, Any]:
    """Validate a token via ``getMe``. Returns ``{ok, username, id, name, error}``."""
    env = _telegram_api_call(token, "getMe")
    if env.get("ok"):
        result = env.get("result") or {}
        return {
            "ok": True,
            "id": result.get("id"),
            "username": result.get("username"),
            "name": result.get("first_name") or result.get("username"),
        }
    return {"ok": False, "error": env.get("description") or "getMe failed"}


def get_updates(token: str, *, offset: Optional[int] = None, timeout: int = 0) -> dict[str, Any]:
    """Fetch pending updates (long-poll ``getUpdates``)."""
    return _telegram_api_call(
        token,
        "getUpdates",
        offset=offset,
        timeout=timeout,
        # short network timeout even for a long_poll=0 call
        **({} if timeout else {}),
    )


def capture_chat(token: str, *, after_update_id: Optional[int] = None) -> Optional[dict[str, Any]]:
    """Capture the most recent chat that messaged the bot (the binding step).

    Returns ``{chat_id, chat_type, title, update_id}`` for the newest update
    whose ``update_id`` is greater than *after_update_id*, or ``None`` when the
    operator has not messaged the bot yet. This is how the connect flow learns
    the operator's ``chat_id`` without them reading it off any dashboard.
    """
    env = get_updates(token, offset=(after_update_id + 1) if after_update_id else None)
    if not env.get("ok"):
        return None
    newest: Optional[dict[str, Any]] = None
    for update in env.get("result") or []:
        uid = update.get("update_id")
        if after_update_id is not None and uid is not None and uid <= after_update_id:
            continue
        message = (
            update.get("message")
            or update.get("edited_message")
            or update.get("channel_post")
            or {}
        )
        chat = message.get("chat") or {}
        if chat.get("id") is None:
            continue
        candidate = {
            "chat_id": str(chat.get("id")),
            "chat_type": chat.get("type"),
            "title": chat.get("title") or chat.get("username") or chat.get("first_name"),
            "update_id": uid,
        }
        if newest is None or (uid is not None and uid >= (newest.get("update_id") or -1)):
            newest = candidate
    return newest


def send_message(
    token: str,
    chat_id: str,
    text: str,
    *,
    thread_id: Optional[str] = None,
    parse_mode: Optional[str] = "Markdown",
    disable_preview: bool = True,
) -> dict[str, Any]:
    """Send a text message. Returns ``{ok, message_id, error}``.

    A too-long body is truncated to :data:`MAX_MESSAGE_LENGTH` with an ellipsis
    marker rather than rejected by the API — a digest never silently vanishes.
    """
    body = text or ""
    if len(body) > MAX_MESSAGE_LENGTH:
        body = body[: MAX_MESSAGE_LENGTH - 1].rstrip() + "…"
    params: dict[str, Any] = {
        "chat_id": chat_id,
        "text": body,
        "disable_web_page_preview": "true" if disable_preview else None,
    }
    if parse_mode:
        params["parse_mode"] = parse_mode
    if thread_id and str(thread_id) not in {"", "1"}:
        # Forum topic thread; "1" is the General topic → omit (same rule the
        # gateway adapter applies).
        params["message_thread_id"] = str(thread_id)
    env = _telegram_api_call(token, "sendMessage", **params)
    if env.get("ok"):
        result = env.get("result") or {}
        return {"ok": True, "message_id": result.get("message_id")}
    # A MarkdownV2/Markdown parse failure should not lose the message: retry once
    # as plain text so an unescaped underscore never eats a digest.
    if parse_mode and "parse" in (env.get("description") or "").lower():
        retry = _telegram_api_call(
            token,
            "sendMessage",
            chat_id=chat_id,
            text=body,
            disable_web_page_preview="true" if disable_preview else None,
            **({"message_thread_id": str(thread_id)} if thread_id and str(thread_id) not in {"", "1"} else {}),
        )
        if retry.get("ok"):
            return {"ok": True, "message_id": (retry.get("result") or {}).get("message_id")}
    return {"ok": False, "error": env.get("description") or env.get("error") or "sendMessage failed"}


__all__ = [
    "API_ROOT",
    "MAX_MESSAGE_LENGTH",
    "resolve_bot_token",
    "get_me",
    "get_updates",
    "capture_chat",
    "send_message",
]
