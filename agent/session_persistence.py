"""Agent session persistence, transcript cleanup, and redaction."""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List

from agent.redact import redact_sensitive_text
from agent.trajectory import convert_scratchpad_to_think
from agent.tool_dispatch_helpers import _is_multimodal_tool_result, _multimodal_text_summary
from superforecasting_agent.storage.files import atomic_json_write

logger = logging.getLogger("run_agent")


def _apply_persist_user_message_override(self, messages: List[Dict]) -> None:
    """Rewrite the current-turn user message before persistence/return.

        Some call paths need an API-only user-message variant without letting
        that synthetic text leak into persisted transcripts or resumed session
        history. When an override is configured for the active turn, mutate the
        in-memory messages list in place so both persistence and returned
        history stay clean.
        """
    idx = getattr(self, "_persist_user_message_idx", None)
    override = getattr(self, "_persist_user_message_override", None)
    if override is None or idx is None:
        return
    if 0 <= idx < len(messages):
        msg = messages[idx]
        if isinstance(msg, dict) and msg.get("role") == "user":
            msg["content"] = override


def _persist_session(self, messages: List[Dict], conversation_history: List[Dict] = None):
    """Save session state to both JSON log and SQLite on any exit path.

        Ensures conversations are never lost, even on errors or early returns.
        """
    self._drop_trailing_empty_response_scaffolding(messages)
    self._apply_persist_user_message_override(messages)
    self._session_messages = messages
    self._save_session_log(messages)
    self._flush_messages_to_session_db(messages, conversation_history)


def _drop_trailing_empty_response_scaffolding(self, messages: List[Dict]) -> None:
    """Remove private empty-response retry/failure scaffolding from transcript tails.

        Also rewinds past any trailing tool-result / assistant(tool_calls) pair
        that the failed iteration left hanging. Without this, the tail ends at
        a raw ``tool`` message and the next user turn lands as
        ``...tool, user, user`` — a protocol-invalid sequence that most
        providers silently reject (returns empty content), causing the
        empty-retry loop to fire forever. See #<TBD>.
        """
    # Pass 1: strip the flagged scaffolding messages themselves.
    dropped_scaffolding = False
    while (
        messages
        and isinstance(messages[-1], dict)
        and (
            messages[-1].get("_empty_recovery_synthetic")
            or messages[-1].get("_empty_terminal_sentinel")
        )
    ):
        messages.pop()
        dropped_scaffolding = True

    # Pass 2: if we stripped scaffolding, rewind through any trailing
    # tool-result messages plus the assistant(tool_calls) message that
    # produced them. This preserves role alternation so the next user
    # message follows a user or assistant message, not an orphan tool
    # result. Only runs when scaffolding was actually present — normal
    # conversation tails (real tool loops mid-progress) are untouched.
    if not dropped_scaffolding:
        return

    # Drop any trailing tool-result messages
    while (
        messages
        and isinstance(messages[-1], dict)
        and messages[-1].get("role") == "tool"
    ):
        messages.pop()

    # Drop the assistant message that issued the tool calls, if the tail
    # now ends in an assistant-with-tool_calls (the pair that owned the
    # just-popped tool results). Without this, the tail is
    # ``assistant(tool_calls=...)`` with no tool answers, which some
    # providers also reject.
    if (
        messages
        and isinstance(messages[-1], dict)
        and messages[-1].get("role") == "assistant"
        and messages[-1].get("tool_calls")
    ):
        messages.pop()


def _flush_messages_to_session_db(self, messages: List[Dict], conversation_history: List[Dict] = None):
    """Persist any un-flushed messages to the SQLite session store.

        Uses _last_flushed_db_idx to track which messages have already been
        written, so repeated calls (from multiple exit paths) only write
        truly new messages — preventing the duplicate-write bug (#860).
        """
    if not self._session_db:
        return
    self._apply_persist_user_message_override(messages)
    try:
        # Retry row creation if the earlier attempt failed transiently.
        if not self._session_db_created:
            self._ensure_db_session()
        start_idx = len(conversation_history) if conversation_history else 0
        flush_from = max(start_idx, self._last_flushed_db_idx)
        for msg in messages[flush_from:]:
            role = msg.get("role", "unknown")
            content = msg.get("content")
            # Persist multimodal tool results as their text summary only —
            # base64 images would bloat the session DB and aren't useful
            # for cross-session replay.
            if _is_multimodal_tool_result(content):
                content = _multimodal_text_summary(content)
            elif isinstance(content, list):
                # List of OpenAI-style content parts: strip images, keep text.
                _txt = []
                for p in content:
                    if isinstance(p, dict) and p.get("type") == "text":
                        _txt.append(str(p.get("text", "")))
                    elif isinstance(p, dict) and p.get("type") in {"image", "image_url", "input_image"}:
                        _txt.append("[screenshot]")
                content = "\n".join(_txt) if _txt else None
            tool_calls_data = None
            if hasattr(msg, "tool_calls") and isinstance(msg.tool_calls, list) and msg.tool_calls:
                tool_calls_data = [
                    {"name": tc.function.name, "arguments": tc.function.arguments}
                    for tc in msg.tool_calls
                ]
            elif isinstance(msg.get("tool_calls"), list):
                tool_calls_data = msg["tool_calls"]
            self._session_db.append_message(
                session_id=self.session_id,
                role=role,
                content=content,
                tool_name=msg.get("tool_name"),
                tool_calls=tool_calls_data,
                tool_call_id=msg.get("tool_call_id"),
                finish_reason=msg.get("finish_reason"),
                reasoning=msg.get("reasoning") if role == "assistant" else None,
                reasoning_content=msg.get("reasoning_content") if role == "assistant" else None,
                reasoning_details=msg.get("reasoning_details") if role == "assistant" else None,
                codex_reasoning_items=msg.get("codex_reasoning_items") if role == "assistant" else None,
                codex_message_items=msg.get("codex_message_items") if role == "assistant" else None,
            )
        self._last_flushed_db_idx = len(messages)
    except Exception as e:
        logger.warning("Session DB append_message failed: %s", e)


def _get_messages_up_to_last_assistant(self, messages: List[Dict]) -> List[Dict]:
    """
        Get messages up to (but not including) the last assistant turn.
        
        This is used when we need to "roll back" to the last successful point
        in the conversation, typically when the final assistant message is
        incomplete or malformed.
        
        Args:
            messages: Full message list
            
        Returns:
            Messages up to the last complete assistant turn (ending with user/tool message)
        """
    if not messages:
        return []

    # Find the index of the last assistant message
    last_assistant_idx = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "assistant":
            last_assistant_idx = i
            break

    if last_assistant_idx is None:
        # No assistant message found, return all messages
        return messages.copy()

    # Return everything up to (not including) the last assistant message
    return messages[:last_assistant_idx]


def _clean_session_content(content: str) -> str:
    """Convert REASONING_SCRATCHPAD to think tags and clean up whitespace."""
    if not content:
        return content
    content = convert_scratchpad_to_think(content)
    content = re.sub(r'\n+(<think>)', r'\n\1', content)
    content = re.sub(r'(</think>)\n+', r'\1\n', content)
    return content.strip()


def _redact_message_content(content):
    """Apply secret redaction to message content (str or list-of-parts).

        Handles both plain-string content and the OpenAI/Anthropic multimodal
        shape where ``content`` is a list of ``{"type": "text", "text": ...}``
        / ``{"type": "image_url", ...}`` / ``{"type": "input_text", "content": ...}``
        parts. Image / binary parts are left untouched; only text fields are
        passed through ``redact_sensitive_text``.

        Respects ``SUPERFORECASTING_AGENT_REDACT_SECRETS`` (and the
        ``FORECAST_`` / ``HERMES_`` aliases) via ``redact_sensitive_text`` —
        when disabled the helper is effectively a no-op.
        """
    if content is None:
        return content
    if isinstance(content, str):
        return redact_sensitive_text(content)
    if isinstance(content, list):
        redacted = []
        for part in content:
            if isinstance(part, dict):
                part = dict(part)
                if isinstance(part.get("text"), str):
                    part["text"] = redact_sensitive_text(part["text"])
                if isinstance(part.get("content"), str):
                    part["content"] = redact_sensitive_text(part["content"])
            redacted.append(part)
        return redacted
    return content


def _save_session_log(self, messages: List[Dict[str, Any]] = None):
    """
        Save the full raw session to a JSON file.

        Stores every message exactly as the agent sees it: user messages,
        assistant messages (with reasoning, finish_reason, tool_calls),
        tool responses (with tool_call_id, tool_name), and injected system
        messages (compression summaries, todo snapshots, etc.).

        REASONING_SCRATCHPAD tags are converted to <think> blocks for consistency.
        Overwritten after each turn so it always reflects the latest state.
        """
    messages = messages or self._session_messages
    if not messages:
        return

    try:
        # Clean assistant content for session logs
        cleaned = []
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("content"):
                msg = dict(msg)
                msg["content"] = self._clean_session_content(msg["content"])
            # Defence-in-depth: redact credentials from every message
            # content before persistence. Catches PATs / API keys / Bearer
            # tokens that may have leaked into assistant responses, tool
            # output, or user paste. Respects
            # SUPERFORECASTING_AGENT_REDACT_SECRETS (and FORECAST_/HERMES_
            # aliases) via redact_sensitive_text — no-op when disabled.
            if "content" in msg:
                msg = dict(msg)
                msg["content"] = self._redact_message_content(msg.get("content"))
            cleaned.append(msg)

        # Guard: never overwrite a larger session log with fewer messages.
        # This protects against data loss when --resume loads a session whose
        # messages weren't fully written to SQLite — the resumed agent starts
        # with partial history and would otherwise clobber the full JSON log.
        if self.session_log_file.exists():
            try:
                existing = json.loads(self.session_log_file.read_text(encoding="utf-8"))
                existing_count = existing.get("message_count", len(existing.get("messages", [])))
                if existing_count > len(cleaned):
                    logging.debug(
                        "Skipping session log overwrite: existing has %d messages, current has %d",
                        existing_count, len(cleaned),
                    )
                    return
            except Exception:
                pass  # corrupted existing file — allow the overwrite

        entry = {
            "session_id": self.session_id,
            "model": self.model,
            "base_url": self.base_url,
            "platform": self.platform,
            "session_start": self.session_start.isoformat(),
            "last_updated": datetime.now().isoformat(),
            "system_prompt": redact_sensitive_text(self._cached_system_prompt or ""),
            "tools": self.tools or [],
            "message_count": len(cleaned),
            "messages": cleaned,
        }

        atomic_json_write(
            self.session_log_file,
            entry,
            indent=2,
            default=str,
        )

    except Exception as e:
        if self.verbose_logging:
            logging.warning(f"Failed to save session log: {e}")
