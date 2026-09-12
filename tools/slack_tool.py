"""Agent-facing Slack Web API tool, so the desk can act as a team collaborator in
Slack: search history, post, reply in-thread, react, pin, list channels.

Stdlib-only transport (urllib) so it works without slack_sdk. The bot token is resolved
per workspace from the OAuth-written slack_tokens.json (or SLACK_BOT_TOKEN), so a
multi-workspace install Just Works.
"""

from __future__ import annotations

import json
from typing import Any

from forecasting.transports import slack as _transport

# Compatibility exports; behavior lives in the shared transport.
_slack_api_call = _transport.api_call
_resolve_bot_token = _transport.resolve_bot_token


def slack_tool(args: dict[str, Any]) -> str:
    return json.dumps(_transport.execute_slack_action(args))


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


def check_slack_tool_requirements() -> bool:
    """Available when a bot token is resolvable — from SLACK_BOT_TOKEN or the
    OAuth-written slack_tokens.json."""
    return _transport.resolve_bot_token() is not None


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
