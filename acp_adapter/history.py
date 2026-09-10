"""Replay persisted conversations as ACP messages, thoughts, tools, and plans."""

from __future__ import annotations

import json
import logging
from typing import Any

import acp
from acp.schema import AgentMessageChunk, AgentThoughtChunk, TextContentBlock, UserMessageChunk

from acp_adapter.events import _build_plan_update_from_todo_result
from acp_adapter.session import SessionState
from acp_adapter.tools import build_tool_complete, build_tool_start

logger = logging.getLogger("acp_adapter.server")

@staticmethod
def _flatten_history_text(value: Any) -> str:
    """Normalize a persisted text-or-text-parts value into a single string.

        OpenAI-style assistant content (and provider reasoning fields) can arrive
        as either a scalar string or a list of ``{"text": ...}`` /
        ``{"type": "text", "content": ...}`` parts. Whitespace-only inputs
        collapse to an empty string so callers can treat ``""`` as "nothing to
        emit".
        """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                elif item.get("type") == "text" and isinstance(item.get("content"), str):
                    parts.append(item["content"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(part.strip() for part in parts if part and part.strip()).strip()
    return ""


@classmethod
def _history_message_text(cls, message: dict[str, Any]) -> str:
    """Extract displayable text from a persisted OpenAI-style message."""
    return cls._flatten_history_text(message.get("content"))


@classmethod
def _history_reasoning_text(cls, message: dict[str, Any]) -> str:
    """Extract displayable reasoning/thought text from a persisted assistant message.

        Returns the first non-empty value among ``reasoning_content`` (the
        canonical field used by DeepSeek / Moonshot and the post-#16892
        chat-completions normalizer) and ``reasoning`` (used by the codex
        event projector and several other transports). Both keys are
        actively written by live code paths, so neither branch is
        deprecated — they cover different transports rather than old vs.
        new sessions.
        """
    for key in ("reasoning_content", "reasoning"):
        text = cls._flatten_history_text(message.get(key))
        if text:
            return text
    return ""


@staticmethod
def _history_message_update(
    *,
    role: str,
    text: str,
) -> UserMessageChunk | AgentMessageChunk | None:
    """Build an ACP history replay update for a user/assistant message."""
    block = TextContentBlock(type="text", text=text)
    if role == "user":
        return UserMessageChunk(
            session_update="user_message_chunk",
            content=block,
        )
    if role == "assistant":
        return AgentMessageChunk(
            session_update="agent_message_chunk",
            content=block,
        )
    return None


@staticmethod
def _history_thought_update(text: str) -> AgentThoughtChunk:
    """Build an ACP history replay update for an assistant thought."""
    return acp.update_agent_thought_text(text)


@staticmethod
def _history_tool_call_name_args(tool_call: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Extract function name/arguments from an OpenAI-style tool_call."""
    function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
    name = str(function.get("name") or tool_call.get("name") or "unknown_tool")
    raw_args = function.get("arguments") or tool_call.get("arguments") or tool_call.get("args") or {}
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
        except Exception:
            parsed = {"raw": raw_args}
        raw_args = parsed
    if not isinstance(raw_args, dict):
        raw_args = {}
    return name, raw_args


@staticmethod
def _history_tool_call_id(tool_call: dict[str, Any]) -> str:
    """Return the stable provider tool call id for ACP history replay."""
    return str(
        tool_call.get("id")
        or tool_call.get("call_id")
        or tool_call.get("tool_call_id")
        or ""
    ).strip()


async def _replay_session_history(self, state: SessionState) -> None:
    """Replay persisted user/assistant history during session/load or session/resume.

        Invoked inline (``await``) from both ``load_session`` and
        ``resume_session`` so that spec-compliant ACP clients receive the
        full transcript within the request's lifetime — see the comment at
        the call sites for the rationale and prior-art citations.

        Replays the conversation as user/assistant chunks, thinking-mode
        thought chunks, plus reconstructed tool-call start/completion
        notifications. Restoring server-side context alone leaves the editor
        looking like a clean thread.
        """
    if not self._conn or not state.history:
        return

    active_tool_calls: dict[str, tuple[str, dict[str, Any]]] = {}

    async def _send(update: Any) -> bool:
        try:
            await self._conn.session_update(session_id=state.session_id, update=update)
            return True
        except Exception:
            logger.warning(
                "Failed to replay ACP history for session %s",
                state.session_id,
                exc_info=True,
            )
            return False

    for message in state.history:
        role = str(message.get("role") or "")

        if role == "user":
            text = self._history_message_text(message)
            if text:
                update = self._history_message_update(role=role, text=text)
                if update is not None and not await _send(update):
                    return
            continue

        if role == "assistant":
            thought = self._history_reasoning_text(message)
            if thought and not await _send(self._history_thought_update(thought)):
                return

            text = self._history_message_text(message)
            if text:
                update = self._history_message_update(role=role, text=text)
                if update is not None and not await _send(update):
                    return

            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list):
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    tool_call_id = self._history_tool_call_id(tool_call)
                    if not tool_call_id:
                        continue
                    tool_name, args = self._history_tool_call_name_args(tool_call)
                    active_tool_calls[tool_call_id] = (tool_name, args)
                    if not await _send(build_tool_start(tool_call_id, tool_name, args)):
                        return
            continue

        if role == "tool":
            tool_call_id = str(message.get("tool_call_id") or "").strip()
            tool_name = str(message.get("tool_name") or "").strip()
            function_args: dict[str, Any] | None = None
            if tool_call_id in active_tool_calls:
                tool_name, function_args = active_tool_calls.pop(tool_call_id)
            if not tool_call_id or not tool_name:
                continue
            result = message.get("content")
            result_text = result if isinstance(result, str) else None
            if not await _send(
                build_tool_complete(
                    tool_call_id,
                    tool_name,
                    result=result_text,
                    function_args=function_args,
                )
            ):
                return
            if tool_name == "todo":
                plan_update = _build_plan_update_from_todo_result(result_text)
                if plan_update is not None and not await _send(plan_update):
                    return
