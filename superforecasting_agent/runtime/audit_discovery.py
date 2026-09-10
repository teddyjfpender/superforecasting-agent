"""Discover pinned audit components from the environment, plugins, and MCP."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .audit_types import Component


def _discover_venv() -> list[Component]:
    """Every dist installed in the running Python's import path."""
    from importlib.metadata import distributions

    out: list[Component] = []
    seen: set[tuple[str, str]] = set()
    for dist in distributions():
        try:
            name = (dist.metadata["Name"] or "").strip()
        except Exception:
            continue
        version = (dist.version or "").strip()
        if not name or not version:
            continue
        key = (name.lower(), version)
        if key in seen:
            continue
        seen.add(key)
        out.append(Component(name=name, version=version, ecosystem="PyPI", source="venv"))
    return out


# requirements.txt line: drop comments, environment markers, options, extras
_REQ_LINE = re.compile(
    r"""^\s*
        (?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)
        (?:\[[^\]]+\])?              # extras
        \s*==\s*
        (?P<version>[A-Za-z0-9._+!-]+)
        \s*(?:;.*)?$
    """,
    re.VERBOSE,
)


def _parse_requirements(text: str) -> list[tuple[str, str]]:
    """Extract ``name==version`` pins. Everything else (>=, ~=, no pin) is skipped.

    A loose pin can't be mapped to a single OSV query, and getting it wrong
    is worse than missing a finding for an audit tool — false positives
    train users to ignore output.
    """
    pins: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        m = _REQ_LINE.match(line)
        if m:
            pins.append((m.group("name"), m.group("version")))
    return pins


def _parse_pyproject_pins(text: str) -> list[tuple[str, str]]:
    """Pull ``name==version`` pins from a ``pyproject.toml`` ``dependencies`` list.

    Uses stdlib ``tomllib`` (3.11+). Same exact-pin policy as requirements.
    """
    try:
        import tomllib
    except ImportError:  # pragma: no cover - 3.10 only
        return []
    try:
        data = tomllib.loads(text)
    except Exception:
        return []
    deps: list[str] = []
    project = data.get("project") or {}
    if not isinstance(project, dict):
        return []
    if isinstance(project.get("dependencies"), list):
        deps.extend(str(x) for x in project["dependencies"])
    optional = project.get("optional-dependencies") or {}
    if isinstance(optional, dict):
        for group in optional.values():
            if isinstance(group, list):
                deps.extend(str(x) for x in group)
    pins: list[tuple[str, str]] = []
    for dep in deps:
        m = _REQ_LINE.match(dep)
        if m:
            pins.append((m.group("name"), m.group("version")))
    return pins


def _discover_plugins(hermes_home: Path) -> list[Component]:
    """Python deps declared by plugins under ``~/.superforecasting-agent/plugins``.

    Plugins typically don't install into the venv (they're directory-based
    with relative imports), so their stated requirements are useful audit
    surface even when the venv scan misses them.
    """
    plugins_dir = hermes_home / "plugins"
    if not plugins_dir.is_dir():
        return []

    out: list[Component] = []
    for plugin_dir in sorted(plugins_dir.iterdir()):
        if not plugin_dir.is_dir() or plugin_dir.name.startswith("."):
            continue
        source = f"plugin:{plugin_dir.name}"
        for req_file in ("requirements.txt", "requirements-dev.txt"):
            path = plugin_dir / req_file
            if path.is_file():
                try:
                    pins = _parse_requirements(path.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
                for name, version in pins:
                    out.append(Component(name=name, version=version, ecosystem="PyPI", source=source))
        pyproject = plugin_dir / "pyproject.toml"
        if pyproject.is_file():
            try:
                pins = _parse_pyproject_pins(pyproject.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            for name, version in pins:
                out.append(Component(name=name, version=version, ecosystem="PyPI", source=source))
    return out


# npx forms we recognise:
#   npx -y @scope/pkg@1.2.3
#   npx --yes pkg@1.2.3
#   npx pkg@1.2.3 [...args]
# We deliberately don't try to resolve unversioned names — that maps to
# "latest" at runtime and isn't a stable audit subject.
_NPX_PKG = re.compile(r"^(@[A-Za-z0-9._-]+/[A-Za-z0-9._-]+|[A-Za-z0-9._-]+)@([A-Za-z0-9._+-]+)$")
# uvx forms:
#   uvx pkg==1.2.3
#   uvx --with pkg==1.2.3 entrypoint
_UVX_PKG = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9._+!-]+)$")


def _extract_mcp_component(server_name: str, command: str, args: list[str]) -> Optional[Component]:
    """Best-effort: parse `command/args` into a (name, version, ecosystem).

    Returns None when the entry doesn't pin a version we can audit (local
    paths, Docker images, unversioned npx, etc.). Audit output stays silent
    rather than guess.
    """
    cmd = (command or "").strip().lower()
    if not args:
        return None
    # npx (any prefix path)
    if cmd.endswith("npx") or cmd == "npx":
        # Skip flag tokens until we see the first thing that looks like a pkg ref
        for token in args:
            if token.startswith("-"):
                continue
            m = _NPX_PKG.match(token)
            if m:
                return Component(
                    name=m.group(1),
                    version=m.group(2),
                    ecosystem="npm",
                    source=f"mcp:{server_name}",
                )
            return None  # First non-flag token isn't a pinned ref
    # uvx (any prefix path)
    if cmd.endswith("uvx") or cmd == "uvx":
        for token in args:
            if token.startswith("-"):
                continue
            m = _UVX_PKG.match(token)
            if m:
                return Component(
                    name=m.group(1),
                    version=m.group(2),
                    ecosystem="PyPI",
                    source=f"mcp:{server_name}",
                )
            return None
    return None


def _discover_mcp() -> list[Component]:
    """Pinned MCP server packages from ``config.yaml``."""
    try:
        from superforecasting_agent.runtime.mcp_config import _get_mcp_servers
    except Exception:
        return []

    out: list[Component] = []
    servers = _get_mcp_servers()
    if not isinstance(servers, dict):
        return []
    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            continue
        command = cfg.get("command", "") or ""
        args = cfg.get("args") or []
        if not isinstance(args, list):
            continue
        comp = _extract_mcp_component(name, command, [str(a) for a in args])
        if comp is not None:
            out.append(comp)
    return out
