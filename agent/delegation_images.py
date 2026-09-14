"""Bounded task attachments using the same vision routing as interactive turns."""

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from agent.image_routing import build_native_content_parts, decide_image_input_mode

logger = logging.getLogger(__name__)
MAX_DELEGATED_IMAGES = 8


def validate_images(value: object) -> list[str]:
    """Validate the complete list before any child is allocated."""
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_DELEGATED_IMAGES:
        raise ValueError("images must be an array of at most 8 nonempty strings")
    images: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("images must be an array of at most 8 nonempty strings")
        images.append(item.strip())
    return images


def goal_with_images(
    goal: str,
    images: list[str],
    *,
    provider: str,
    model: str,
    config: dict[str, Any] | None,
) -> str | list[dict[str, Any]]:
    """Attach pixels for vision models; preserve usable handles for text models."""
    if not images:
        return goal
    paths: list[str] = []
    urls: list[str] = []
    inline: list[str] = []
    for image in images:
        if image.startswith("data:image/"):
            inline.append(image)
        elif urlsplit(image).scheme.lower() in {"http", "https"}:
            urls.append(image)
        else:
            paths.append(image)
    if decide_image_input_mode(provider, model, config) == "native":
        parts, skipped = build_native_content_parts(goal, paths)
        if skipped:
            logger.warning("Skipped %d unreadable delegated image(s)", len(skipped))
        parts.extend(
            {"type": "image_url", "image_url": {"url": url}} for url in [*urls, *inline]
        )
        return parts if any(part.get("type") == "image_url" for part in parts) else goal
    readable = [path for path in paths if Path(path).is_file()]
    if len(readable) != len(paths):
        logger.warning(
            "Skipped %d unreadable delegated image(s)", len(paths) - len(readable)
        )
    handles = readable + urls
    notes = [
        f"[Image attached at: {handle}] Use vision_analyze to inspect this evidence."
        for handle in handles
    ]
    if inline:
        notes.append(
            f"[{len(inline)} inline image(s) unavailable to this non-vision model; delegate to a vision-capable model.]"
        )
    return "\n\n".join([goal, *notes])
