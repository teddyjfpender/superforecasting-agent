"""Session replay operations behind the SessionDB API."""

import json
import logging
from typing import Any, Dict, List

from agent.memory_manager import sanitize_context

logger = logging.getLogger(__name__)


def resolve_resume_session_id(self, session_id: str) -> str:
    """Redirect a resume target to the descendant session that holds the messages.

        Context compression ends the current session and forks a new child session
        (linked via ``parent_session_id``). The flush cursor is reset, so the
        child is where new messages actually land — the parent ends up with
        ``message_count = 0`` rows unless messages had already been flushed to
        it before compression. See #15000.

        This helper walks ``parent_session_id`` forward from ``session_id`` and
        returns the first descendant in the chain that has at least one message
        row. If the original session already has messages, or no descendant
        has any, the original ``session_id`` is returned unchanged.

        The chain is always walked via the child whose ``started_at`` is
        latest; that matches the single-chain shape that compression creates.
        A depth cap (32) guards against accidental loops in malformed data.
        """
    if not session_id:
        return session_id
    with self._lock:
        # If this session already has messages, nothing to redirect.
        try:
            row = self._conn.execute(
                "SELECT 1 FROM messages WHERE session_id = ? LIMIT 1",
                (session_id,),
            ).fetchone()
        except Exception:
            return session_id
        if row is not None:
            return session_id
        # Walk descendants: at each step, pick the most-recently-started
            # child session; stop once we find one with messages.
        current = session_id
        seen = {current}
        for _ in range(32):
            try:
                child_row = self._conn.execute(
                    "SELECT id FROM sessions "
                    "WHERE parent_session_id = ? "
                    "ORDER BY started_at DESC, id DESC LIMIT 1",
                    (current,),
                ).fetchone()
            except Exception:
                return session_id
            if child_row is None:
                return session_id
            child_id = child_row["id"] if hasattr(child_row, "keys") else child_row[0]
            if not child_id or child_id in seen:
                return session_id
            seen.add(child_id)
            try:
                msg_row = self._conn.execute(
                    "SELECT 1 FROM messages WHERE session_id = ? LIMIT 1",
                    (child_id,),
                ).fetchone()
            except Exception:
                return session_id
            if msg_row is not None:
                return child_id
            current = child_id
    return session_id


def get_messages_as_conversation(
    self, session_id: str, include_ancestors: bool = False
) -> List[Dict[str, Any]]:
    """
        Load messages in the OpenAI conversation format (role + content dicts).
        Used by the gateway to restore conversation history.
        """
    session_ids = [session_id]
    if include_ancestors:
        session_ids = self._session_lineage_root_to_tip(session_id)
    with self._lock:
        placeholders = ",".join("?" for _ in session_ids)
        rows = self._conn.execute(
            "SELECT role, content, tool_call_id, tool_calls, tool_name, "
            "finish_reason, reasoning, reasoning_content, reasoning_details, "
            "codex_reasoning_items, codex_message_items "
            f"FROM messages WHERE session_id IN ({placeholders}) ORDER BY id",
            tuple(session_ids),
        ).fetchall()
    messages = []
    for row in rows:
        content = self._decode_content(row["content"])
        if row["role"] in {"user", "assistant"} and isinstance(content, str):
            content = sanitize_context(content).strip()
        msg = {"role": row["role"], "content": content}
        if row["tool_call_id"]:
            msg["tool_call_id"] = row["tool_call_id"]
        if row["tool_name"]:
            msg["tool_name"] = row["tool_name"]
        if row["tool_calls"]:
            try:
                msg["tool_calls"] = json.loads(row["tool_calls"])
            except (json.JSONDecodeError, TypeError):
                logger.warning("Failed to deserialize tool_calls in conversation replay, falling back to []")
                msg["tool_calls"] = []
        # Restore reasoning fields on assistant messages so providers
        # that replay reasoning (OpenRouter, OpenAI, Nous) receive
        # coherent multi-turn reasoning context.
        if row["role"] == "assistant":
            if row["finish_reason"]:
                msg["finish_reason"] = row["finish_reason"]
            if row["reasoning"]:
                msg["reasoning"] = row["reasoning"]
            if row["reasoning_content"] is not None:
                msg["reasoning_content"] = row["reasoning_content"]
            if row["reasoning_details"]:
                try:
                    msg["reasoning_details"] = json.loads(row["reasoning_details"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Failed to deserialize reasoning_details, falling back to None")
                    msg["reasoning_details"] = None
            if row["codex_reasoning_items"]:
                try:
                    msg["codex_reasoning_items"] = json.loads(row["codex_reasoning_items"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Failed to deserialize codex_reasoning_items, falling back to None")
                    msg["codex_reasoning_items"] = None
            if row["codex_message_items"]:
                try:
                    msg["codex_message_items"] = json.loads(row["codex_message_items"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Failed to deserialize codex_message_items, falling back to None")
                    msg["codex_message_items"] = None
        if include_ancestors and self._is_duplicate_replayed_user_message(messages, msg):
            continue
        messages.append(msg)
    return messages


def _session_lineage_root_to_tip(self, session_id: str) -> List[str]:
    if not session_id:
        return [session_id]
    chain = []
    current = session_id
    seen = set()
    with self._lock:
        for _ in range(100):
            if not current or current in seen:
                break
            seen.add(current)
            chain.append(current)
            row = self._conn.execute(
                "SELECT parent_session_id FROM sessions WHERE id = ?",
                (current,),
            ).fetchone()
            if row is None:
                break
            current = row["parent_session_id"] if hasattr(row, "keys") else row[0]
    return list(reversed(chain)) or [session_id]


def _is_duplicate_replayed_user_message(messages: List[Dict[str, Any]], msg: Dict[str, Any]) -> bool:
    if msg.get("role") != "user":
        return False
    content = msg.get("content")
    if not isinstance(content, str) or not content:
        return False
    for prev in reversed(messages):
        if prev.get("role") == "user" and prev.get("content") == content:
            return True
        if prev.get("role") == "assistant" and (prev.get("content") or prev.get("tool_calls")):
            return False
    return False
