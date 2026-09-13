"""Slack transport shared by forecast collaboration, notifications and tools."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any


def api_call(method: str, token: str, **params: Any) -> dict[str, Any]:
    """POST to the Slack Web API (application/x-www-form-urlencoded, Bearer token).
    Module-level so tests can monkeypatch it without hitting the network."""
    url = f"https://slack.com/api/{method}"
    payload = {k: v for k, v in params.items() if v is not None}
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 (fixed https host)
        result = json.loads(resp.read().decode("utf-8"))
    if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
        raise ValueError("Slack API response must be an object with boolean ok")
    return result


def resolve_bot_token(team_id: str | None = None) -> str | None:
    """Resolve a workspace bot token: SLACK_BOT_TOKEN env, else the OAuth-written
    slack_tokens.json (by team_id, else the first entry)."""
    env = _usable_token(os.getenv("SLACK_BOT_TOKEN"))
    if env:
        return env
    try:
        from superforecasting_agent.constants import get_agent_home

        path = get_agent_home() / "slack_tokens.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        if team_id:
            entry = data.get(team_id)
            return (
                _usable_token(entry.get("token")) if isinstance(entry, dict) else None
            )
        for entry in data.values():
            token = (
                _usable_token(entry.get("token")) if isinstance(entry, dict) else None
            )
            if token:
                return token
    except Exception:
        return None
    return None


def _usable_token(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _require(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not value:
        raise ValueError(f"missing required arg: {key}")
    return str(value)


def _require_any(args: dict[str, Any], keys: tuple[str, ...]) -> str:
    """Return the first present value among *keys*, or raise naming all of them."""
    for key in keys:
        value = args.get(key)
        if value:
            return str(value)
    raise ValueError(f"missing required arg: one of {', '.join(keys)}")


def _encode_blocks(blocks: Any) -> Any:
    """Slack expects `blocks` as a JSON string over urlencoded transport; pass a
    string through untouched, serialize a list/dict."""
    if blocks is None or isinstance(blocks, str):
        return blocks
    return json.dumps(blocks)


def execute_slack_action(args: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a Slack Web API action and return a structured result."""
    action = args.get("action")
    token = resolve_bot_token(args.get("team_id"))
    if not token:
        return {
            "success": False,
            "error": "no Slack bot token (install via OAuth or set SLACK_BOT_TOKEN)",
        }
    try:
        if action == "post_message":
            result = api_call(
                "chat.postMessage",
                token,
                channel=_require(args, "channel"),
                text=_require(args, "text"),
                thread_ts=args.get("thread_ts"),
            )
        elif action == "search_messages":
            result = api_call(
                "search.messages",
                token,
                query=_require(args, "query"),
                count=args.get("count", 20),
            )
        elif action == "add_reaction":
            result = api_call(
                "reactions.add",
                token,
                channel=_require(args, "channel"),
                timestamp=_require(args, "timestamp"),
                name=_require(args, "name"),
            )
        elif action == "pin_message":
            result = api_call(
                "pins.add",
                token,
                channel=_require(args, "channel"),
                timestamp=_require(args, "timestamp"),
            )
        elif action == "list_channels":
            result = api_call(
                "conversations.list",
                token,
                limit=args.get("limit", 100),
                types="public_channel,private_channel",
            )
        elif action == "post_blocks":
            result = api_call(
                "chat.postMessage",
                token,
                channel=_require(args, "channel"),
                blocks=_encode_blocks(args.get("blocks")) or _require(args, "blocks"),
                text=args.get("text"),
                thread_ts=args.get("thread_ts"),
            )
        elif action == "post_with_metadata":
            event_type = _require(args, "event_type")
            if args.get("event_payload") is None:
                raise ValueError("missing required arg: event_payload")
            metadata = json.dumps({
                "event_type": event_type,
                "event_payload": args["event_payload"],
            })
            result = api_call(
                "chat.postMessage",
                token,
                channel=_require(args, "channel"),
                text=args.get("text"),
                blocks=_encode_blocks(args.get("blocks")),
                thread_ts=args.get("thread_ts"),
                metadata=metadata,
            )
        elif action == "upload_file":
            result = api_call(
                "files.upload",
                token,
                channels=args.get("channel") or args.get("channels"),
                content=_require(args, "content"),
                filename=args.get("filename"),
                title=args.get("title"),
                initial_comment=args.get("initial_comment"),
                thread_ts=args.get("thread_ts"),
            )
        elif action == "read_thread":
            result = api_call(
                "conversations.replies",
                token,
                channel=_require(args, "channel"),
                ts=_require_any(args, ("thread_ts", "ts", "timestamp")),
                limit=args.get("limit", 100),
                include_all_metadata=True,
            )
        else:
            return {"success": False, "error": f"unknown action: {action}"}
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": f"slack api call failed: {exc}"}
    return {**result, "success": result.get("ok") is True}
