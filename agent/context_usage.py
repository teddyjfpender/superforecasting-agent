"""Provider-measured context baselines with full-prefix invalidation.

The baseline prices input only. Visible assistant output and subsequent tool
results are estimated as additions; billed hidden reasoning is never added.
Only digests and counts are persisted, never prompt content or credentials.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from typing import Any

from agent.model_metadata import (
    estimate_messages_tokens_rough,
    estimate_request_tokens_rough,
)
from agent.tool_discovery import wire_tools

logger = logging.getLogger(__name__)
_FIELDS = (
    "role",
    "content",
    "api_content",
    "tool_calls",
    "tool_call_id",
    "name",
    "tool_name",
    "reasoning",
    "reasoning_content",
    "reasoning_details",
    "codex_reasoning_items",
    "codex_message_items",
    "_anthropic_content_blocks",
)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _prefix(messages: list[dict]) -> str:
    return _digest([
        {key: msg[key] for key in _FIELDS if msg.get(key) is not None}
        for msg in messages
    ])


@dataclass(frozen=True)
class UsageAnchor:
    version: int
    prompt_tokens: int
    message_count: int
    prefix_digest: str
    identity_digest: str

    @classmethod
    def capture(
        cls, messages: list[dict], identity: Any, prompt_tokens: int
    ) -> UsageAnchor:
        if type(prompt_tokens) is not int or prompt_tokens <= 0:
            raise ValueError(
                "A context baseline requires positive measured input tokens"
            )
        return cls(
            1, prompt_tokens, len(messages), _prefix(messages), _digest(identity)
        )

    @classmethod
    def decode(cls, value: Any) -> UsageAnchor | None:
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            return None
        for name in ("version", "prompt_tokens", "message_count"):
            if type(value[name]) is not int:
                return None
        if (
            value["version"] != 1
            or value["prompt_tokens"] <= 0
            or value["message_count"] < 0
        ):
            return None
        for name in ("prefix_digest", "identity_digest"):
            digest = value[name]
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
            ):
                return None
        return cls(**value)

    def estimate(self, messages: list[dict], identity: Any) -> int | None:
        if (
            len(messages) < self.message_count
            or _digest(identity) != self.identity_digest
        ):
            return None
        if _prefix(messages[: self.message_count]) != self.prefix_digest:
            return None
        return self.prompt_tokens + estimate_messages_tokens_rough(
            messages[self.message_count :]
        )


def _system_prompt(agent: Any) -> str:
    cached = getattr(agent, "_cached_system_prompt", None)
    if isinstance(cached, str):
        return cached
    db = getattr(agent, "_session_db", None)
    session_id = getattr(agent, "session_id", None)
    if db is not None and isinstance(session_id, str):
        try:
            row = db.get_session(session_id)
            stored = row.get("system_prompt") if isinstance(row, dict) else None
            if isinstance(stored, str):
                return stored
        except Exception:
            logger.debug("Stored context prompt unavailable", exc_info=True)
    return ""


def request_identity(agent: Any, tools: list[dict] | None) -> dict:
    identity = {
        "runtime": {
            name: getattr(agent, name, None)
            for name in (
                "session_id",
                "model",
                "provider",
                "base_url",
                "api_mode",
                "reasoning_config",
                "reasoning_effort",
                "ephemeral_system_prompt",
                "prefill_messages",
                "_vision_supported",
                "_force_ascii_payload",
                "_cached_system_prompt",
                "_context_usage_overhead",
            )
        },
        "tools": tools,
    }
    identity["runtime"]["_cached_system_prompt"] = _system_prompt(agent)
    identity["runtime"]["_vision_supported"] = getattr(agent, "_vision_supported", True)
    return identity


def record_usage(agent: Any, snapshot: UsageAnchor | None, prompt_tokens: int) -> None:
    if snapshot is None or type(prompt_tokens) is not int or prompt_tokens <= 0:
        return
    anchor = UsageAnchor(
        1,
        prompt_tokens,
        snapshot.message_count,
        snapshot.prefix_digest,
        snapshot.identity_digest,
    )
    agent._context_usage_anchor = anchor
    db = getattr(agent, "_session_db", None)
    session_id = getattr(agent, "session_id", None)
    if db is not None and isinstance(session_id, str):
        try:
            agent._ensure_db_session()
            if not db.save_context_usage(session_id, asdict(anchor)):
                logger.warning("Context baseline was not saved: session row is missing")
        except Exception:
            logger.warning(
                "Could not persist context accounting; restart will use an estimate",
                exc_info=True,
            )


def snapshot_request(agent: Any, messages: list[dict]) -> UsageAnchor | None:
    try:
        return UsageAnchor.capture(
            messages, request_identity(agent, wire_tools(agent, register=False)), 1
        )
    except (TypeError, ValueError):
        return None


def context_tokens(agent: Any, messages: list[dict]) -> int:
    """Return measured input plus estimated additions, or a full rough estimate."""
    tools = wire_tools(agent, register=False)
    anchor = getattr(agent, "_context_usage_anchor", None)
    if not isinstance(anchor, UsageAnchor):
        db = getattr(agent, "_session_db", None)
        session_id = getattr(agent, "session_id", None)
        if db is not None and isinstance(session_id, str):
            try:
                anchor = UsageAnchor.decode(db.load_context_usage(session_id))
                agent._context_usage_anchor = anchor
            except Exception:
                logger.debug("Context baseline unavailable", exc_info=True)
    if isinstance(anchor, UsageAnchor):
        try:
            estimate = anchor.estimate(messages, request_identity(agent, tools))
            if estimate is not None:
                return estimate
        except (TypeError, ValueError):
            pass
    system = _system_prompt(agent)
    ephemeral = getattr(agent, "ephemeral_system_prompt", None)
    if isinstance(ephemeral, str) and ephemeral:
        system += "\n\n" + ephemeral
    prefill = getattr(agent, "prefill_messages", None)
    payload = (prefill if isinstance(prefill, list) else []) + messages
    estimate = estimate_request_tokens_rough(payload, system_prompt=system, tools=tools)
    overhead = getattr(agent, "_context_usage_overhead", None)
    if isinstance(overhead, tuple):
        estimate += sum(
            (len(part) + 3) // 4 for part in overhead if isinstance(part, str)
        )
    return estimate
