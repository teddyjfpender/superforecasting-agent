"""Session messages operations behind the SessionDB API."""

import json
import logging
import time
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _encode_content(cls, content: Any) -> Any:
    """Serialize structured (list/dict) message content for sqlite.

        sqlite3 can only bind ``str``, ``bytes``, ``int``, ``float``, and ``None``
        to query parameters. Multimodal messages have ``content`` as a list of
        parts (``[{"type": "text", ...}, {"type": "image_url", ...}]``), which
        raises ``ProgrammingError: Error binding parameter N: type 'list' is
        not supported`` when bound directly.

        Returns the value unchanged when it's already a safe scalar, or a
        sentinel-prefixed JSON string for lists/dicts. Paired with
        :meth:`_decode_content` on read.
        """
    if content is None or isinstance(content, (str, bytes, int, float)):
        return content
    try:
        return cls._CONTENT_JSON_PREFIX + json.dumps(content)
    except (TypeError, ValueError):
        # Last-resort fallback: stringify so persistence never fails.
        return str(content)


def _decode_content(cls, content: Any) -> Any:
    """Reverse :meth:`_encode_content`; returns scalars unchanged."""
    if isinstance(content, str) and content.startswith(cls._CONTENT_JSON_PREFIX):
        try:
            return json.loads(content[len(cls._CONTENT_JSON_PREFIX):])
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Failed to decode JSON-encoded message content; "
                "returning raw string"
            )
            return content
    return content


def append_message(
    self,
    session_id: str,
    role: str,
    content: str = None,
    tool_name: str = None,
    tool_calls: Any = None,
    tool_call_id: str = None,
    token_count: int = None,
    finish_reason: str = None,
    reasoning: str = None,
    reasoning_content: str = None,
    reasoning_details: Any = None,
    codex_reasoning_items: Any = None,
    codex_message_items: Any = None,
) -> int:
    """
        Append a message to a session. Returns the message row ID.

        Also increments the session's message_count (and tool_call_count
        if role is 'tool' or tool_calls is present).
        """
    # Serialize structured fields to JSON before entering the write txn
    reasoning_details_json = (
        json.dumps(reasoning_details)
        if reasoning_details else None
    )
    codex_items_json = (
        json.dumps(codex_reasoning_items)
        if codex_reasoning_items else None
    )
    codex_message_items_json = (
        json.dumps(codex_message_items)
        if codex_message_items else None
    )
    tool_calls_json = json.dumps(tool_calls) if tool_calls else None
    # Multimodal content (list of parts) must be JSON-encoded: sqlite3
    # cannot bind list/dict parameters directly.
    stored_content = self._encode_content(content)
    # Pre-compute tool call count
    num_tool_calls = 0
    if tool_calls is not None:
        num_tool_calls = len(tool_calls) if isinstance(tool_calls, list) else 1
    def _do(conn):
        cursor = conn.execute(
            """INSERT INTO messages (session_id, role, content, tool_call_id,
                   tool_calls, tool_name, timestamp, token_count, finish_reason,
                   reasoning, reasoning_content, reasoning_details, codex_reasoning_items,
                   codex_message_items)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                role,
                stored_content,
                tool_call_id,
                tool_calls_json,
                tool_name,
                time.time(),
                token_count,
                finish_reason,
                reasoning,
                reasoning_content,
                reasoning_details_json,
                codex_items_json,
                codex_message_items_json,
            ),
        )
        msg_id = cursor.lastrowid
        # Update counters
        if num_tool_calls > 0:
            conn.execute(
                """UPDATE sessions SET message_count = message_count + 1,
                       tool_call_count = tool_call_count + ? WHERE id = ?""",
                (num_tool_calls, session_id),
            )
        else:
            conn.execute(
                "UPDATE sessions SET message_count = message_count + 1 WHERE id = ?",
                (session_id,),
            )
        return msg_id
    return self._execute_write(_do)


def replace_messages(self, session_id: str, messages: List[Dict[str, Any]]) -> None:
    """Atomically replace every message for a session.

        Used by transcript-rewrite flows such as /retry, /undo, and /compress.
        The delete + reinsert sequence must commit as one transaction so a
        mid-rewrite failure does not leave SQLite with a partial transcript.
        """
    self._execute_write(lambda conn: _replace_messages(self, conn, session_id, messages))


def _replace_messages(self, conn, session_id: str, messages: List[Dict[str, Any]]) -> None:
    """Write a transcript inside an already-owned transaction."""
    conn.execute(
        "DELETE FROM messages WHERE session_id = ?", (session_id,)
    )
    conn.execute(
        "UPDATE sessions SET message_count = 0, tool_call_count = 0 WHERE id = ?",
        (session_id,),
    )
    now_ts = time.time()
    total_messages = 0
    total_tool_calls = 0
    for msg in messages:
        role = msg.get("role", "unknown")
        tool_calls = msg.get("tool_calls")
        reasoning_details = msg.get("reasoning_details") if role == "assistant" else None
        codex_reasoning_items = (
            msg.get("codex_reasoning_items") if role == "assistant" else None
        )
        codex_message_items = (
            msg.get("codex_message_items") if role == "assistant" else None
        )
        reasoning_details_json = (
            json.dumps(reasoning_details) if reasoning_details else None
        )
        codex_items_json = (
            json.dumps(codex_reasoning_items) if codex_reasoning_items else None
        )
        codex_message_items_json = (
            json.dumps(codex_message_items) if codex_message_items else None
        )
        tool_calls_json = json.dumps(tool_calls) if tool_calls else None
        conn.execute(
            """INSERT INTO messages (session_id, role, content, tool_call_id,
                   tool_calls, tool_name, timestamp, token_count, finish_reason,
                   reasoning, reasoning_content, reasoning_details, codex_reasoning_items,
                   codex_message_items)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                role,
                self._encode_content(msg.get("content")),
                msg.get("tool_call_id"),
                tool_calls_json,
                msg.get("tool_name"),
                now_ts,
                msg.get("token_count"),
                msg.get("finish_reason"),
                msg.get("reasoning") if role == "assistant" else None,
                msg.get("reasoning_content") if role == "assistant" else None,
                reasoning_details_json,
                codex_items_json,
                codex_message_items_json,
            ),
        )
        total_messages += 1
        if tool_calls is not None:
            total_tool_calls += (
                len(tool_calls) if isinstance(tool_calls, list) else 1
            )
        now_ts += 1e-6
    conn.execute(
        "UPDATE sessions SET message_count = ?, tool_call_count = ? WHERE id = ?",
        (total_messages, total_tool_calls, session_id),
    )
