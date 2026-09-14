"""Compact repeated observations without caching or suppressing tool execution."""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from agent.tool_guardrails import ToolCallSignature

_MARKER = "[Repeated tool observation:"


@dataclass
class ResultReferences:
    """One consecutive observation chain; references require a retained original."""

    signature: ToolCallSignature | None = None
    digest: str = ""
    original_id: str = ""

    def compact(
        self,
        name: str,
        args: Mapping[str, Any],
        result: Any,
        call_id: str,
        messages: Sequence[Mapping[str, Any]],
        *,
        failed: bool,
    ) -> Any:
        if failed or not isinstance(result, str) or len(result) < 512 or not call_id:
            self.signature = None
            self.digest = self.original_id = ""
            return result
        try:
            signature = ToolCallSignature.from_call(name, args)
        except (TypeError, ValueError):
            self.signature = None
            self.digest = self.original_id = ""
            return result
        digest = hashlib.sha256(
            result.encode("utf-8", errors="surrogatepass")
        ).hexdigest()
        original = next(
            (
                message
                for message in reversed(messages)
                if message.get("role") == "tool"
                and message.get("tool_call_id") == self.original_id
            ),
            None,
        )
        content = original.get("content") if original else None
        if (
            signature == self.signature
            and digest == self.digest
            and isinstance(content, str)
            and _MARKER not in content
            and (
                result in content
                or (
                    "<persisted-output>" in content
                    and "Full output saved to:" in content
                )
            )
            and "Full output could not be saved" not in content
        ):
            return (
                f"{_MARKER} {name} executed again and returned identical bytes. "
                f"Use the retained result of tool call {self.original_id}. "
                f"SHA-256: {digest}. This is a fresh observation, not a cached execution.]"
            )
        self.signature, self.digest, self.original_id = signature, digest, call_id
        return result
