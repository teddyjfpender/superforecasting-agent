"""Vision-aware message preprocessing and safe multimodal tool results."""

import asyncio
import base64
import copy
import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, List, Optional

from agent.tool_dispatch_helpers import _is_multimodal_tool_result, _multimodal_text_summary

logger = logging.getLogger("run_agent")


def _content_has_image_parts(content: Any) -> bool:
    if not isinstance(content, list):
        return False
    for part in content:
        if isinstance(part, dict) and part.get("type") in {"image_url", "input_image"}:
            return True
    return False


def _materialize_data_url_for_vision(image_url: str) -> tuple[str, Optional[Path]]:
    header, _, data = str(image_url or "").partition(",")
    mime = "image/jpeg"
    if header.startswith("data:"):
        mime_part = header[len("data:"):].split(";", 1)[0].strip()
        if mime_part.startswith("image/"):
            mime = mime_part
    suffix = {
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
    }.get(mime, ".jpg")
    tmp = tempfile.NamedTemporaryFile(prefix="anthropic_image_", suffix=suffix, delete=False)
    try:
        with tmp:
            tmp.write(base64.b64decode(data))
    except Exception:
        # delete=False means a corrupt/unsupported data URL would otherwise
        # leak a zero-byte temp file on every failed materialization.
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise
    path = Path(tmp.name)
    return str(path), path


def _describe_image_for_anthropic_fallback(self, image_url: str, role: str) -> str:
    cache_key = hashlib.sha256(str(image_url or "").encode("utf-8")).hexdigest()
    cached = self._anthropic_image_fallback_cache.get(cache_key)
    if cached:
        return cached

    role_label = {
        "assistant": "assistant",
        "tool": "tool result",
    }.get(role, "user")
    analysis_prompt = (
        "Describe everything visible in this image in thorough detail. "
        "Include any text, code, UI, data, objects, people, layout, colors, "
        "and any other notable visual information."
    )

    vision_source = str(image_url or "")
    cleanup_path: Optional[Path] = None
    if vision_source.startswith("data:"):
        vision_source, cleanup_path = self._materialize_data_url_for_vision(vision_source)

    description = ""
    try:
        from tools.vision_tools import vision_analyze_tool

        result_json = asyncio.run(
            vision_analyze_tool(image_url=vision_source, user_prompt=analysis_prompt)
        )
        result = json.loads(result_json) if isinstance(result_json, str) else {}
        description = (result.get("analysis") or "").strip()
    except Exception as e:
        description = f"Image analysis failed: {e}"
    finally:
        if cleanup_path and cleanup_path.exists():
            try:
                cleanup_path.unlink()
            except OSError:
                pass

    if not description:
        description = "Image analysis failed."

    note = f"[The {role_label} attached an image. Here's what it contains:\n{description}]"
    if vision_source and not str(image_url or "").startswith("data:"):
        note += (
            f"\n[If you need a closer look, use vision_analyze with image_url: {vision_source}]"
        )

    self._anthropic_image_fallback_cache[cache_key] = note
    return note


def _model_supports_vision(self) -> bool:
    """Return True if the active provider+model reports native vision.

        Used to decide whether to strip image content parts from API-bound
        messages (for non-vision models) or let the provider adapter handle
        them natively (for vision-capable models).
        """
    try:
        from agent.models_dev import get_model_capabilities
        provider = (getattr(self, "provider", "") or "").strip()
        model = (getattr(self, "model", "") or "").strip()
        if not provider or not model:
            return False
        caps = get_model_capabilities(provider, model)
        if caps is None:
            return False
        return bool(caps.supports_vision)
    except Exception:
        return False


def _preprocess_anthropic_content(self, content: Any, role: str) -> Any:
    if not self._content_has_image_parts(content):
        return content

    text_parts: List[str] = []
    image_notes: List[str] = []
    for part in content:
        if isinstance(part, str):
            if part.strip():
                text_parts.append(part.strip())
            continue
        if not isinstance(part, dict):
            continue

        ptype = part.get("type")
        if ptype in {"text", "input_text"}:
            text = str(part.get("text", "") or "").strip()
            if text:
                text_parts.append(text)
            continue

        if ptype in {"image_url", "input_image"}:
            image_data = part.get("image_url", {})
            image_url = image_data.get("url", "") if isinstance(image_data, dict) else str(image_data or "")
            if image_url:
                image_notes.append(self._describe_image_for_anthropic_fallback(image_url, role))
            else:
                image_notes.append("[An image was attached but no image source was available.]")
            continue

        text = str(part.get("text", "") or "").strip()
        if text:
            text_parts.append(text)

    prefix = "\n\n".join(note for note in image_notes if note).strip()
    suffix = "\n".join(text for text in text_parts if text).strip()
    if prefix and suffix:
        return f"{prefix}\n\n{suffix}"
    if prefix:
        return prefix
    if suffix:
        return suffix
    return "[A multimodal message was converted to text for Anthropic compatibility.]"


def _prepare_anthropic_messages_for_api(self, api_messages: list) -> list:
    """Let the native adapter handle images when vision is supported."""
    return _prepare_messages_for_non_vision_model(self, api_messages)


def _prepare_messages_for_non_vision_model(self, api_messages: list) -> list:
    """Strip native image parts when the active model lacks vision.

        Runs on the chat.completions / codex_responses paths. Vision-capable
        models pass through unchanged (provider and any downstream translator
        handle the image parts natively). Non-vision models get each image
        replaced by a cached vision_analyze text description so the turn
        doesn't fail with "model does not support image input".
        """
    if not any(
        isinstance(msg, dict) and self._content_has_image_parts(msg.get("content"))
        for msg in api_messages
    ):
        return api_messages

    if self._model_supports_vision():
        return api_messages

    transformed = copy.deepcopy(api_messages)
    for msg in transformed:
        if not isinstance(msg, dict):
            continue
        # Reuse the Anthropic text-fallback preprocessor — the behaviour is
        # identical (walk content parts, replace images with cached
        # descriptions, merge back into a single text or structured
        # content). Naming is historical.
        msg["content"] = self._preprocess_anthropic_content(
            msg.get("content"),
            str(msg.get("role", "user") or "user"),
        )
    return transformed


def _tool_result_content_for_active_model(self, tool_name: str, result: Any) -> Any:
    """Return the tool message content that is safe for the active model.

        Multimodal tool results normally unwrap to OpenAI-style content parts so
        vision-capable models can inspect screenshots.  Text-only providers must
        not receive those image parts, because a rejected tool result becomes
        part of the canonical history and can make the next user turn fail before
        the agent has a chance to recover.
        """
    if not _is_multimodal_tool_result(result):
        return result

    content = result.get("content") or []
    if not self._content_has_image_parts(content):
        return content

    if self._model_supports_vision():
        # Vision-capable on paper — but if we've already learned in this
        # session that the active (provider, model) rejects list-type
        # tool content (e.g. Xiaomi MiMo's 400 "text is not set"),
        # short-circuit to a text summary so we don't burn another
        # round-trip relearning the same lesson.  Cache populated by
        # the 400 recovery path in agent.conversation_loop.  Transient
        # per-session; next session retries.
        key = (
            (getattr(self, "provider", "") or "").strip().lower(),
            (getattr(self, "model", "") or "").strip(),
        )
        no_list = getattr(self, "_no_list_tool_content_models", None)
        if no_list and key in no_list:
            logger.debug(
                "Tool %s: model %s/%s known to reject list-type tool "
                "content this session — sending text summary",
                tool_name, key[0], key[1],
            )
            return _multimodal_text_summary(result)
        return content

    summary = _multimodal_text_summary(result)
    if tool_name == "computer_use":
        return json.dumps({
            "error": (
                "computer_use returned screenshot/image content, but the active "
                "model/provider does not support image input. Switch to a "
                "vision-capable model for desktop computer use, or use browser "
                "tools for browser tasks."
            ),
            "text_summary": summary,
        })

    logger.warning(
        "Tool %s returned image content for non-vision model %s/%s; "
        "falling back to text summary",
        tool_name,
        self.provider,
        self.model,
    )
    return summary
