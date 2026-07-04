"""Shared rendering helpers for the reference-doc generators.

Deterministic, dependency-free. No timestamps anywhere — a generated file must be
byte-identical run-to-run so the ``--check`` staleness gate is meaningful.
"""

from __future__ import annotations

import inspect
from typing import Any

# Reuse the protocol codegen's type mapping so the doc's field types are the SAME
# shapes the TypeScript wire types use — one vocabulary across the whole system.
from protocol.codegen import _split_optional, _ts_scalar

_EDIT_TARGET = "python -m scripts.docgen"


def header(title: str, source: str, *, blurb: str = "") -> str:
    """The DO-NOT-EDIT banner every generated file opens with.

    ``source`` names the Python module(s) the file is derived from so a reader
    knows where the truth lives; ``blurb`` is an optional one-line summary.
    """

    lines = [
        f"# {title}",
        "",
        "<!-- GENERATED FILE - DO NOT EDIT BY HAND. -->",
        f"<!-- Source of truth: {source} -->",
        f"<!-- Regenerate:      {_EDIT_TARGET} -->",
        f"<!-- Staleness gate:  {_EDIT_TARGET} --check -->",
        "",
        "> This page is generated from code. Do not edit it by hand — your change"
        " would be overwritten on the next regeneration and the staleness gate"
        " would fail. Edit the source instead, then run"
        f" `{_EDIT_TARGET}`.",
        "",
        f"> **Source of truth:** `{source}`",
        "",
    ]
    if blurb:
        lines.append(blurb)
        lines.append("")
    return "\n".join(lines)


def wire_type(field: Any) -> str:
    """Render a pydantic ``FieldInfo`` annotation as a compact type string.

    Uses the protocol codegen's mapping (so ``list[X]`` → ``X[]``, ``X | None`` →
    ``X``) and appends an optionality marker derived from the field.
    """

    inner, nullable = _split_optional(field.annotation)
    text = _ts_scalar(inner)
    extra = field.json_schema_extra if isinstance(field.json_schema_extra, dict) else {}
    if extra.get("wireOptional"):
        return f"{text}?" if not (extra.get("wireNullable") and nullable) else f"{text}? | null"
    if nullable:
        return f"{text} | null"
    return text


def model_fields_table(model: Any) -> list[str]:
    """A markdown table of ``model``'s fields (sorted), or a one-line note when the
    model carries no fields."""

    names = sorted(model.model_fields)
    if not names:
        return ["_(no fields)_", ""]
    rows = ["| field | type |", "| --- | --- |"]
    for name in names:
        rows.append(f"| `{name}` | `{wire_type(model.model_fields[name])}` |")
    rows.append("")
    return rows


def first_docline(obj: Any) -> str:
    """The first non-empty line of an object's (or its module's) docstring."""

    doc = inspect.getdoc(obj) or ""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def module_docline(func: Any) -> str:
    """The first line of the docstring of the module that defines ``func``."""

    import sys

    module = sys.modules.get(getattr(func, "__module__", ""))
    return first_docline(module) if module is not None else ""
