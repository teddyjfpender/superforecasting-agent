"""Agent-facing Slack Web API tool, so the desk can act as a team collaborator in
Slack: search history, post, reply in-thread, react, pin, list channels.

Stdlib-only transport (urllib) so it works without slack_sdk. The bot token is resolved
per workspace from the OAuth-written slack_tokens.json (or SLACK_BOT_TOKEN), so a
multi-workspace install Just Works.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

SLACK_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["post_message", "search_messages", "add_reaction", "pin_message", "list_channels"],
        },
        "team_id": {"type": "string", "description": "Workspace to act in (defaults to the only/first installed)."},
        "channel": {"type": "string", "description": "Channel id (post_message / add_reaction / pin_message)."},
        "text": {"type": "string", "description": "Message text (post_message)."},
        "thread_ts": {"type": "string", "description": "Reply in this thread (post_message)."},
        "query": {"type": "string", "description": "Search query (search_messages)."},
        "timestamp": {"type": "string", "description": "Message ts (add_reaction / pin_message)."},
        "name": {"type": "string", "description": "Emoji name without colons (add_reaction)."},
        "count": {"type": "integer"},
        "limit": {"type": "integer"},
    },
    "required": ["action"],
}


def _slack_api_call(method: str, token: str, **params: Any) -> dict[str, Any]:
    """POST to the Slack Web API (application/x-www-form-urlencoded, Bearer token).
    Module-level so tests can monkeypatch it without hitting the network."""
    url = f"https://slack.com/api/{method}"
    payload = {k: v for k, v in params.items() if v is not None}
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 (fixed https host)
        return json.loads(resp.read().decode("utf-8"))


def _resolve_bot_token(team_id: str | None = None) -> str | None:
    """Resolve a workspace bot token: SLACK_BOT_TOKEN env, else the OAuth-written
    slack_tokens.json (by team_id, else the first entry)."""
    env = os.getenv("SLACK_BOT_TOKEN")
    if env:
        return env
    try:
        from hermes_constants import get_hermes_home

        path = get_hermes_home() / "slack_tokens.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        if team_id and isinstance(data.get(team_id), dict):
            return data[team_id].get("token")
        for entry in data.values():
            if isinstance(entry, dict) and entry.get("token"):
                return entry["token"]
    except Exception:
        return None
    return None


def _require(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not value:
        raise ValueError(f"missing required arg: {key}")
    return str(value)


def slack_tool(args: dict[str, Any]) -> str:
    """Dispatch a Slack Web API action and return a JSON string."""
    action = args.get("action")
    token = _resolve_bot_token(args.get("team_id"))
    if not token:
        return json.dumps({"success": False, "error": "no Slack bot token (install via OAuth or set SLACK_BOT_TOKEN)"})
    try:
        if action == "post_message":
            result = _slack_api_call("chat.postMessage", token, channel=_require(args, "channel"), text=_require(args, "text"), thread_ts=args.get("thread_ts"))
        elif action == "search_messages":
            result = _slack_api_call("search.messages", token, query=_require(args, "query"), count=args.get("count", 20))
        elif action == "add_reaction":
            result = _slack_api_call("reactions.add", token, channel=_require(args, "channel"), timestamp=_require(args, "timestamp"), name=_require(args, "name"))
        elif action == "pin_message":
            result = _slack_api_call("pins.add", token, channel=_require(args, "channel"), timestamp=_require(args, "timestamp"))
        elif action == "list_channels":
            result = _slack_api_call("conversations.list", token, limit=args.get("limit", 100), types="public_channel,private_channel")
        else:
            return json.dumps({"success": False, "error": f"unknown action: {action}"})
    except ValueError as exc:
        return json.dumps({"success": False, "error": str(exc)})
    except Exception as exc:  # network / API transport failure
        return json.dumps({"success": False, "error": f"slack api call failed: {exc}"})
    return json.dumps({"success": bool(result.get("ok")), **result})
