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
            "enum": [
                "post_message", "search_messages", "add_reaction", "pin_message",
                "list_channels", "post_blocks", "post_with_metadata", "upload_file",
                "read_thread",
            ],
        },
        "team_id": {"type": "string", "description": "Workspace to act in (defaults to the only/first installed)."},
        "channel": {"type": "string", "description": "Channel id (post_* / add_reaction / pin_message / upload_file / read_thread)."},
        "text": {"type": "string", "description": "Message text; also the fallback/notification text for post_blocks / post_with_metadata."},
        "thread_ts": {"type": "string", "description": "Reply in / read this thread (post_* / upload_file / read_thread)."},
        "query": {"type": "string", "description": "Search query (search_messages)."},
        "timestamp": {"type": "string", "description": "Message ts (add_reaction / pin_message)."},
        "name": {"type": "string", "description": "Emoji name without colons (add_reaction)."},
        "blocks": {"type": "array", "items": {"type": "object"}, "description": "Block Kit blocks (post_blocks / post_with_metadata)."},
        "event_type": {"type": "string", "description": "Message-metadata event_type, e.g. 'sfp_forecast_card' (post_with_metadata)."},
        "event_payload": {"type": "object", "description": "Machine-readable message-metadata payload — agents parse this, not the prose (post_with_metadata)."},
        "content": {"type": "string", "description": "Inline text file content to upload (upload_file)."},
        "filename": {"type": "string", "description": "Uploaded file name (upload_file)."},
        "title": {"type": "string", "description": "Uploaded file title (upload_file)."},
        "initial_comment": {"type": "string", "description": "Message posted alongside the upload (upload_file)."},
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
        from superforecasting_agent.constants import get_agent_home

        path = get_agent_home() / "slack_tokens.json"
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
        elif action == "post_blocks":
            # Human-readable Block Kit surface. `text` is kept as the notification
            # / accessibility fallback (Slack recommends it alongside blocks).
            result = _slack_api_call(
                "chat.postMessage", token,
                channel=_require(args, "channel"),
                blocks=_encode_blocks(args.get("blocks")) or _require(args, "blocks"),
                text=args.get("text"),
                thread_ts=args.get("thread_ts"),
            )
        elif action == "post_with_metadata":
            # The machine-truth verb: Block Kit on the surface, a versioned JSON
            # payload underneath via Slack message metadata (event_type +
            # event_payload). Agents parse the metadata, never the prose.
            event_type = _require(args, "event_type")
            if args.get("event_payload") is None:
                raise ValueError("missing required arg: event_payload")
            metadata = json.dumps({"event_type": event_type, "event_payload": args["event_payload"]})
            result = _slack_api_call(
                "chat.postMessage", token,
                channel=_require(args, "channel"),
                text=args.get("text"),
                blocks=_encode_blocks(args.get("blocks")),
                thread_ts=args.get("thread_ts"),
                metadata=metadata,
            )
        elif action == "upload_file":
            # Inline-text upload via files.upload `content` (urlencoded-safe — the
            # bodies that ride uploads are text: evidence excerpts, exported
            # cards). Binary/multipart uploads (charts) are a documented
            # fast-follow. `channel` maps to files.upload's `channels`.
            result = _slack_api_call(
                "files.upload", token,
                channels=args.get("channel") or args.get("channels"),
                content=_require(args, "content"),
                filename=args.get("filename"),
                title=args.get("title"),
                initial_comment=args.get("initial_comment"),
                thread_ts=args.get("thread_ts"),
            )
        elif action == "read_thread":
            # conversations.replies on the thread's parent ts. include_all_metadata
            # surfaces peer sfp/1 message metadata so the agent can parse it.
            result = _slack_api_call(
                "conversations.replies", token,
                channel=_require(args, "channel"),
                ts=_require_any(args, ("thread_ts", "ts", "timestamp")),
                limit=args.get("limit", 100),
                include_all_metadata=True,
            )
        else:
            return json.dumps({"success": False, "error": f"unknown action: {action}"})
    except ValueError as exc:
        return json.dumps({"success": False, "error": str(exc)})
    except Exception as exc:  # network / API transport failure
        return json.dumps({"success": False, "error": f"slack api call failed: {exc}"})
    return json.dumps({"success": bool(result.get("ok")), **result})


def check_slack_tool_requirements() -> bool:
    """Available when a bot token is resolvable — from SLACK_BOT_TOKEN or the
    OAuth-written slack_tokens.json."""
    return _resolve_bot_token() is not None


# Self-register into the 'slack' toolset (best-effort: a minimal import context without
# the registry just skips registration).
try:
    from tools.registry import registry

    registry.register(
        name="slack",
        toolset="slack",
        schema=SLACK_TOOL_SCHEMA,
        handler=lambda args, **_kw: slack_tool(args),
        check_fn=check_slack_tool_requirements,
        requires_env=[],
        description=(
            "Act as a Slack collaborator: post / reply in-thread, post Block Kit, post with "
            "machine-readable message metadata, upload files, read a thread, search history, "
            "react, pin, list channels."
        ),
    )
except Exception:  # pragma: no cover
    pass
