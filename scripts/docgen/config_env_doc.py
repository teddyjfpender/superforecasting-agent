"""Render ``docs/reference/config-and-env.md`` from the source itself.

Source of truth: every ``os.getenv`` / ``os.environ.get`` / ``os.environ[...]``
read across ``forecasting/``, ``tui_gateway/``, ``tools/``, and ``superforecasting_agent/``.

There is no hand-maintained list of environment variables — there cannot be one
without it drifting. Instead this page is derived by walking the AST of every
module under those packages and collecting the string key of every environment
read, together with the default it falls back to and the module that reads it.
Add a ``os.getenv("NEW_THING")`` anywhere in those trees and this page grows a
row on the next regeneration; the ``--check`` gate fails until it does.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from scripts.docgen.common import header

SOURCE = "os.getenv / os.environ reads across forecasting/, tui_gateway/, tools/, superforecasting_agent/"

# The package roots we scan. Only production source — no test trees exist under
# these packages (verified), so no filtering is needed beyond __pycache__, which
# rglob("*.py") never returns.
_PACKAGES = ("forecasting", "tui_gateway", "tools", "superforecasting_agent")

# A variable is flagged a **secret** purely by name — anything whose name carries
# one of these tokens is treated as a credential and grouped apart so an operator
# can see at a glance which values must never be logged or committed. This is a
# name heuristic, not a taint analysis; it is intentionally conservative (it will
# flag a path-to-a-key as a secret).
_SECRET_TOKENS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL")


def _is_secret(name: str) -> bool:
    return any(tok in name for tok in _SECRET_TOKENS)


@dataclass
class _Var:
    name: str
    defaults: set[str] = field(default_factory=set)
    modules: set[str] = field(default_factory=set)


def _is_environ(node: ast.AST) -> bool:
    """True for ``os.environ`` or a bare ``environ`` (``from os import environ``)."""

    if (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    ):
        return True
    return isinstance(node, ast.Name) and node.id == "environ"


def _default_repr(args: list[ast.expr]) -> str:
    """Render the default (2nd) arg of a getenv/get call as a stable token."""

    if len(args) < 2:
        return "None"  # os.getenv("X") with no default returns None
    try:
        return repr(ast.literal_eval(args[1]))
    except (ValueError, TypeError, SyntaxError):
        return "(computed)"


def _scan_module(tree: ast.AST) -> list[tuple[str, str]]:
    """Return ``(var_name, default_token)`` for every env read in one module."""

    out: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        # os.getenv(...) / getenv(...)   and   os.environ.get(...) / environ.get(...)
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "getenv"
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
            ) or (isinstance(func, ast.Name) and func.id == "getenv"):
                key = node.args[0] if node.args else None
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    out.append((key.value, _default_repr(node.args)))
            elif (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and _is_environ(func.value)
            ):
                key = node.args[0] if node.args else None
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    out.append((key.value, _default_repr(node.args)))
        # os.environ["X"] / environ["X"] in a READ position (raises if unset).
        elif (
            isinstance(node, ast.Subscript)
            and _is_environ(node.value)
            and isinstance(node.ctx, ast.Load)
        ):
            key = node.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                out.append((key.value, "(required)"))
    return out


def _collect(root: Path) -> dict[str, _Var]:
    found: dict[str, _Var] = {}
    for pkg in _PACKAGES:
        pkg_dir = root / pkg
        if not pkg_dir.is_dir():
            continue
        for path in sorted(pkg_dir.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            module = ".".join(path.relative_to(root).with_suffix("").parts)
            for name, default in _scan_module(tree):
                var = found.setdefault(name, _Var(name))
                var.defaults.add(default)
                var.modules.add(module)
    return found


def _table(vars_: list[_Var]) -> str:
    rows = ["| variable | default | read in |", "| --- | --- | --- |"]
    for var in vars_:
        defaults = ", ".join(f"`{d}`" for d in sorted(var.defaults))
        modules = ", ".join(f"`{m}`" for m in sorted(var.modules))
        rows.append(f"| `{var.name}` | {defaults} | {modules} |")
    return "\n".join(rows)


def render() -> str:
    root = Path(__file__).resolve().parents[2]
    found = _collect(root)

    secrets = sorted((v for v in found.values() if _is_secret(v.name)), key=lambda v: v.name)
    config = sorted((v for v in found.values() if not _is_secret(v.name)), key=lambda v: v.name)

    blocks: list[str] = [
        header(
            "Configuration & Environment Variables",
            SOURCE,
            blurb=(
                f"Every environment variable the server, tools, and CLI actually"
                f" **read** — harvested by walking the AST of every module under"
                f" `forecasting/`, `tui_gateway/`, `tools/`, and `superforecasting_agent/` for"
                f" `os.getenv` / `os.environ.get` / `os.environ[...]`. There are"
                f" **{len(found)} variables** ({len(secrets)} flagged as secrets,"
                f" {len(config)} configuration/runtime). The **default** column shows"
                f" the fallback passed at the call site — `None` means a bare"
                f" `os.getenv` (unset → `None`), `(required)` means a subscript that"
                f" raises `KeyError` when unset, `(computed)` means a non-literal"
                f" default. A variable read in several modules lists each; differing"
                f" defaults are all shown."
            ),
        )
    ]

    blocks.append(
        "> **Secrets** are classified by name (any variable whose name contains"
        f" {', '.join(f'`{t}`' for t in _SECRET_TOKENS)}). This is a conservative"
        " naming heuristic, not a data-flow analysis — treat the list as"
        " \"never log or commit these\", and audit the source before assuming a"
        " variable *not* listed here is safe to print."
    )

    blocks.append("## Secrets & credentials\n")
    if secrets:
        blocks.append(
            f"**{len(secrets)} variables** carry a credential-shaped name. Provide"
            " them via the environment or the credential store; never commit them."
        )
        blocks.append(_table(secrets))
    else:  # pragma: no cover - defensive
        blocks.append("_(none)_")

    blocks.append("## Configuration & runtime\n")
    blocks.append(
        f"**{len(config)} variables** tune runtime behaviour, endpoints, paths, and"
        " feature flags, or are inherited from the surrounding shell/OS. Everything"
        " here is read directly from the environment at the call site shown."
    )
    blocks.append(_table(config))

    return "\n\n".join(blocks) + "\n"
