"""Declarative plugin metadata, independent of registration and execution."""

from dataclasses import dataclass, field
from typing import Any

VALID_PLUGIN_KINDS: set[str] = {
    "standalone",
    "backend",
    "exclusive",
    "platform",
    "model-provider",
}


@dataclass
class PluginManifest:
    """Parsed representation of a plugin.yaml manifest."""

    name: str
    version: str = ""
    description: str = ""
    author: str = ""
    requires_env: list[str | dict[str, Any]] = field(default_factory=list)
    provides_tools: list[str] = field(default_factory=list)
    provides_hooks: list[str] = field(default_factory=list)
    source: str = ""  # "user", "project", or "entrypoint"
    path: str | None = None
    # Plugin kind — see plugins.py module docstring for semantics.
    # ``standalone`` (default): hooks/tools of its own; opt-in via
    #                           ``plugins.enabled``.
    # ``backend``: pluggable backend for an existing core tool (e.g.
    #              image_gen). Built-in (bundled) backends auto-load;
    #              user-installed still gated by ``plugins.enabled``.
    # ``exclusive``: category with exactly one active provider (memory).
    #              Selection via ``<category>.provider`` config key; the
    #              category's own discovery system handles loading and the
    #              general scanner skips these.
    # ``platform``: gateway messaging platform adapter (e.g. IRC). Bundled
    #              platform plugins auto-load so every shipped platform is
    #              available out of the box; user-installed platform plugins
    #              in the runtime-home plugins dir are still gated by
    #              ``plugins.enabled``
    #              (untrusted code).
    kind: str = "standalone"
    # Registry key — path-derived, used by ``plugins.enabled``/``disabled``
    # lookups and by ``superforecasting-agent plugins list``. For a flat plugin at
    # ``plugins/disk-cleanup/`` the key is ``disk-cleanup``; for a nested
    # category plugin at ``plugins/image_gen/openai/`` the key is
    # ``image_gen/openai``. When empty, falls back to ``name``.
    key: str = ""


def parse_manifest(
    data: Any, *, directory_name: str, path: str, source: str, prefix: str = ""
) -> PluginManifest:
    """Validate decoded declarations without filesystem access or plugin imports.

    Unknown fields remain available to specialized plugin systems. Unknown kinds
    retain the general manager's conservative standalone behavior.
    """
    if not isinstance(data, dict):
        raise ValueError("plugin manifest must be a mapping")
    name = data.get("name", directory_name)
    if not isinstance(name, str) or not name.strip():
        raise ValueError("plugin name must be a nonempty string")
    for field_name in ("description", "author"):
        if not isinstance(data.get(field_name, ""), str):
            raise ValueError(f"{field_name} must be a string")
    for field_name in ("requires_env", "provides_tools", "provides_hooks"):
        values = data.get(field_name, [])
        if not isinstance(values, list):
            raise ValueError(f"{field_name} must be a list")
        for value in values:
            declaration = (
                value.get("name")
                if field_name == "requires_env" and isinstance(value, dict)
                else value
            )
            if not isinstance(declaration, str) or not declaration.strip():
                raise ValueError(
                    f"{field_name} entries must have nonempty string names"
                )
    raw_kind = data.get("kind", "standalone")
    kind = raw_kind.strip().lower() if isinstance(raw_kind, str) else "standalone"
    return PluginManifest(
        name=name,
        version=str(data.get("version", "")),
        description=data.get("description", ""),
        author=data.get("author", ""),
        requires_env=data.get("requires_env", []),
        provides_tools=data.get("provides_tools", []),
        provides_hooks=data.get("provides_hooks", []),
        source=source,
        path=path,
        kind=kind if kind in VALID_PLUGIN_KINDS else "standalone",
        key=f"{prefix}/{directory_name}" if prefix else name,
    )
