"""Convert ACP text, images, and attached resources into model content."""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from acp.schema import (
    AudioContentBlock, BlobResourceContents, EmbeddedResourceContentBlock,
    ImageContentBlock, ResourceContentBlock, TextContentBlock, TextResourceContents,
)

# Keep attachment diagnostics on the existing server log channel.
logger = logging.getLogger("acp_adapter.server")

_MAX_ACP_RESOURCE_BYTES = 512 * 1024


_TEXT_RESOURCE_MIME_PREFIXES = ("text/",)


_TEXT_RESOURCE_MIME_TYPES = {
    "application/json",
    "application/javascript",
    "application/typescript",
    "application/xml",
    "application/x-yaml",
    "application/yaml",
    "application/toml",
    "application/sql",
}


def _resource_display_name(uri: str, name: str | None = None, title: str | None = None) -> str:
    """Human-readable attachment name for prompt context."""
    raw_name = (name or "").strip()
    raw_title = (title or "").strip()
    if raw_title and raw_name and raw_title != raw_name:
        return f"{raw_title} ({raw_name})"
    if raw_title:
        return raw_title
    if raw_name:
        return raw_name
    parsed = urlparse(uri)
    candidate = parsed.path if parsed.scheme else uri
    return Path(unquote(candidate)).name or uri or "resource"


def _is_text_resource(mime_type: str | None) -> bool:
    mime = (mime_type or "").split(";", 1)[0].strip().lower()
    if not mime:
        return False
    return mime.startswith(_TEXT_RESOURCE_MIME_PREFIXES) or mime in _TEXT_RESOURCE_MIME_TYPES


def _is_image_resource(mime_type: str | None) -> bool:
    mime = (mime_type or "").split(";", 1)[0].strip().lower()
    return mime.startswith("image/")


def _guess_image_mime_from_path(path: Path) -> str | None:
    suffix = path.suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".svg": "image/svg+xml",
    }.get(suffix)


def _image_data_url(data: bytes, mime_type: str) -> str:
    return f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"


def _path_from_file_uri(uri: str) -> Path | None:
    """Convert local file URIs/paths from ACP clients into a readable Path.

    Zed may send POSIX file URIs from Linux/WSL workspaces or Windows-ish paths
    when launched through wsl.exe. Translate the common Windows drive form to
    /mnt/<drive>/... so the agent running in WSL can read it.
    """
    raw = (uri or "").strip()
    if not raw:
        return None

    parsed = urlparse(raw)
    if parsed.scheme and parsed.scheme != "file":
        return None

    if parsed.scheme == "file":
        if parsed.netloc and parsed.netloc not in {"", "localhost"}:
            return None
        path_text = unquote(parsed.path or "")
    else:
        path_text = unquote(raw)

    # file:///C:/Users/... or C:\Users\...
    if len(path_text) >= 3 and path_text[0] == "/" and path_text[2] == ":" and path_text[1].isalpha():
        drive = path_text[1].lower()
        rest = path_text[3:].lstrip("/\\").replace("\\", "/")
        return Path("/mnt") / drive / rest
    if len(path_text) >= 2 and path_text[1] == ":" and path_text[0].isalpha():
        drive = path_text[0].lower()
        rest = path_text[2:].lstrip("/\\").replace("\\", "/")
        return Path("/mnt") / drive / rest

    return Path(path_text)


def _decode_text_bytes(data: bytes, mime_type: str | None) -> str | None:
    """Decode resource bytes if they are probably text; return None for binary."""
    if b"\x00" in data and not _is_text_resource(mime_type):
        return None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _format_resource_text(
    *,
    uri: str,
    body: str,
    name: str | None = None,
    title: str | None = None,
    note: str | None = None,
) -> str:
    display = _resource_display_name(uri, name=name, title=title)
    header = f"[Attached file: {display}]"
    if note:
        header += f" ({note})"
    return f"{header}\nURI: {uri}\n\n{body}"


def _resource_link_to_parts(block: ResourceContentBlock) -> list[dict[str, Any]]:
    """Convert an ACP resource_link block to OpenAI content parts.

    Returns a list of {"type": "text", ...} and/or {"type": "image_url", ...}
    parts. Image resources produce an image_url part with a small text header
    so the model knows which attachment it is. Non-image resources return a
    single text part with the inlined file body (or a binary-omit note).
    """
    uri = str(getattr(block, "uri", "") or "").strip()
    if not uri:
        return []

    name = str(getattr(block, "name", "") or "").strip() or None
    title = str(getattr(block, "title", "") or "").strip() or None
    mime_type = str(getattr(block, "mime_type", "") or "").strip() or None
    path = _path_from_file_uri(uri)

    if path is None:
        return [{
            "type": "text",
            "text": _format_resource_text(
                uri=uri,
                name=name,
                title=title,
                body="[Resource link only; the agent cannot read non-file ACP resource URIs directly.]",
            ),
        }]

    # Image files: emit a short text header + image_url data URL so vision
    # models can see the attachment instead of a "binary omitted" note.
    image_mime = mime_type if _is_image_resource(mime_type) else _guess_image_mime_from_path(path)
    if image_mime and _is_image_resource(image_mime):
        try:
            size = path.stat().st_size
            if size > _MAX_ACP_RESOURCE_BYTES:
                return [{
                    "type": "text",
                    "text": _format_resource_text(
                        uri=uri,
                        name=name,
                        title=title,
                        body=f"[Image too large to inline: {size} bytes, cap={_MAX_ACP_RESOURCE_BYTES}]",
                    ),
                }]
            with path.open("rb") as fh:
                data = fh.read(_MAX_ACP_RESOURCE_BYTES + 1)
            if len(data) > _MAX_ACP_RESOURCE_BYTES:
                return [{
                    "type": "text",
                    "text": _format_resource_text(
                        uri=uri,
                        name=name,
                        title=title,
                        body=f"[Image too large to inline: exceeds cap={_MAX_ACP_RESOURCE_BYTES} bytes]",
                    ),
                }]
        except OSError as exc:
            logger.warning("ACP image resource read failed: %s", uri, exc_info=True)
            return [{
                "type": "text",
                "text": _format_resource_text(
                    uri=uri,
                    name=name,
                    title=title,
                    body=f"[Could not read attached image: {exc}]",
                ),
            }]
        display = _resource_display_name(uri, name=name, title=title)
        return [
            {"type": "text", "text": f"[Attached image: {display}]\nURI: {uri}"},
            {"type": "image_url", "image_url": {"url": _image_data_url(data, image_mime)}},
        ]

    try:
        size = path.stat().st_size
        read_size = min(size, _MAX_ACP_RESOURCE_BYTES)
        with path.open("rb") as fh:
            data = fh.read(read_size)
        text = _decode_text_bytes(data, mime_type)
        if text is None:
            return [{
                "type": "text",
                "text": _format_resource_text(
                    uri=uri,
                    name=name,
                    title=title,
                    body=f"[Binary file omitted: {size} bytes, mime={mime_type or 'unknown'}]",
                ),
            }]
        note = None
        if size > _MAX_ACP_RESOURCE_BYTES:
            note = f"truncated to {_MAX_ACP_RESOURCE_BYTES} of {size} bytes"
        return [{
            "type": "text",
            "text": _format_resource_text(uri=uri, name=name, title=title, body=text, note=note),
        }]
    except OSError as exc:
        logger.warning("ACP resource read failed: %s", uri, exc_info=True)
        return [{
            "type": "text",
            "text": _format_resource_text(
                uri=uri,
                name=name,
                title=title,
                body=f"[Could not read attached file: {exc}]",
            ),
        }]


def _embedded_resource_to_parts(block: EmbeddedResourceContentBlock) -> list[dict[str, Any]]:
    resource = getattr(block, "resource", None)
    if resource is None:
        return []

    uri = str(getattr(resource, "uri", "") or "").strip()
    mime_type = str(getattr(resource, "mime_type", "") or "").strip() or None

    if isinstance(resource, TextResourceContents):
        return [{"type": "text", "text": _format_resource_text(uri=uri, body=resource.text)}]

    if isinstance(resource, BlobResourceContents):
        blob = resource.blob or ""
        try:
            data = base64.b64decode(blob, validate=True)
        except Exception:
            data = blob.encode("utf-8", errors="replace")

        # Image blobs go through as image_url so vision models can see them.
        if _is_image_resource(mime_type):
            if len(data) > _MAX_ACP_RESOURCE_BYTES:
                return [{
                    "type": "text",
                    "text": _format_resource_text(
                        uri=uri,
                        body=f"[Embedded image too large to inline: {len(data)} bytes, cap={_MAX_ACP_RESOURCE_BYTES}]",
                    ),
                }]
            display = _resource_display_name(uri)
            return [
                {"type": "text", "text": f"[Attached image: {display}]" + (f"\nURI: {uri}" if uri else "")},
                {"type": "image_url", "image_url": {"url": _image_data_url(data, mime_type or "image/png")}},
            ]

        text = _decode_text_bytes(data[:_MAX_ACP_RESOURCE_BYTES], mime_type)
        if text is None:
            body = f"[Binary embedded file omitted: {len(data)} bytes, mime={mime_type or 'unknown'}]"
        else:
            body = text
            if len(data) > _MAX_ACP_RESOURCE_BYTES:
                body += f"\n\n[Truncated to {_MAX_ACP_RESOURCE_BYTES} of {len(data)} bytes]"
        return [{"type": "text", "text": _format_resource_text(uri=uri, body=body)}]

    text = getattr(resource, "text", None)
    if text:
        return [{"type": "text", "text": _format_resource_text(uri=uri, body=str(text))}]
    return []


def _extract_text(
    prompt: list[
        TextContentBlock
        | ImageContentBlock
        | AudioContentBlock
        | ResourceContentBlock
        | EmbeddedResourceContentBlock
    ],
) -> str:
    """Extract plain text from ACP content blocks for display/commands."""
    parts: list[str] = []
    for block in prompt:
        if isinstance(block, TextContentBlock):
            parts.append(block.text)
        elif hasattr(block, "text"):
            parts.append(str(block.text))
    return "\n".join(parts)


def _image_block_to_openai_part(block: ImageContentBlock) -> dict[str, Any] | None:
    """Convert an ACP image content block to OpenAI-style multimodal content."""
    data = str(getattr(block, "data", "") or "").strip()
    uri = str(getattr(block, "uri", "") or "").strip()
    mime_type = str(getattr(block, "mime_type", "") or "image/png").strip() or "image/png"

    if data:
        url = data if data.startswith("data:") else f"data:{mime_type};base64,{data}"
    elif uri:
        url = uri
    else:
        return None

    return {"type": "image_url", "image_url": {"url": url}}


def _content_blocks_to_openai_user_content(
    prompt: list[
        TextContentBlock
        | ImageContentBlock
        | AudioContentBlock
        | ResourceContentBlock
        | EmbeddedResourceContentBlock
    ],
) -> str | list[dict[str, Any]]:
    """Convert ACP prompt blocks into an OpenAI-compatible user content payload."""
    parts: list[dict[str, Any]] = []
    text_parts: list[str] = []

    for block in prompt:
        if isinstance(block, TextContentBlock):
            if block.text:
                parts.append({"type": "text", "text": block.text})
                text_parts.append(block.text)
            continue
        if isinstance(block, ImageContentBlock):
            image_part = _image_block_to_openai_part(block)
            if image_part is not None:
                parts.append(image_part)
            continue
        if isinstance(block, ResourceContentBlock):
            resource_parts = _resource_link_to_parts(block)
            for part in resource_parts:
                parts.append(part)
                if part.get("type") == "text":
                    text_parts.append(part["text"])
            continue
        if isinstance(block, EmbeddedResourceContentBlock):
            resource_parts = _embedded_resource_to_parts(block)
            for part in resource_parts:
                parts.append(part)
                if part.get("type") == "text":
                    text_parts.append(part["text"])
            continue

    if not parts:
        return _extract_text(prompt)

    # Keep pure text prompts as strings so slash-command handling and text-only
    # providers keep the exact legacy path. Switch to structured content only
    # when an actual non-text block is present.
    if all(part.get("type") == "text" for part in parts):
        return "\n".join(text_parts)

    return parts
