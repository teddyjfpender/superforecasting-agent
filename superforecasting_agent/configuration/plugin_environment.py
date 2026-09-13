"""Interpret platform manifest environment declarations without loading plugins."""

from __future__ import annotations

from typing import Any


def environment_metadata(
    manifest: Any, *, fallback_label: str
) -> dict[str, dict[str, Any]]:
    if not isinstance(manifest, dict):
        return {}
    label = manifest.get("label") or manifest.get("name") or fallback_label
    result = {}
    for field in ("requires_env", "optional_env"):
        entries = manifest.get(field) or []
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, str):
                name, meta = entry, {}
            elif isinstance(entry, dict):
                name, meta = entry.get("name"), entry
            else:
                continue
            if not isinstance(name, str) or not name.strip() or name in result:
                continue
            is_secret = bool(meta.get("password") or meta.get("secret"))
            if not is_secret and meta.get("password") is not False:
                is_secret = name.upper().endswith((
                    "_TOKEN",
                    "_SECRET",
                    "_KEY",
                    "_PASSWORD",
                    "_JSON",
                ))
            result[name] = {
                "description": meta.get("description") or f"{label} configuration",
                "prompt": meta.get("prompt") or name,
                "url": meta.get("url") or None,
                "password": is_secret,
                "category": meta.get("category") or "messaging",
            }
    return result
