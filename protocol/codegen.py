"""Emit ``ui-tui/src/protocol/generated.ts`` from the protocol registry.

A hand-rolled, dependency-free emitter that walks the registered pydantic models
(and their nested models) and renders TypeScript interfaces, the string-literal
event names, and the ``PROTOCOL_VERSION`` const. Output is DETERMINISTIC —
interfaces sorted by TS name, fields sorted by name, union members sorted — so
the file is diff-stable and a staleness gate can assert it is unchanged.

Usage
-----
    python -m protocol.codegen            # (re)write generated.ts
    python -m protocol.codegen --check    # exit nonzero if it would change
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import UnionType
from typing import Any, Union, get_args, get_origin

from protocol import EVENT_SPECS, PROTOCOL_VERSION, registered_models
from protocol.types import WireModel

_NONE = type(None)

_GENERATED_REL = Path("ui-tui/src/protocol/generated.ts")

_HEADER = """\
// GENERATED FILE — DO NOT EDIT BY HAND.
// Source of truth: the `protocol/` Python package (pydantic models).
// Regenerate:      python -m protocol.codegen
// Staleness gate:  python -m protocol.codegen --check
"""


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _ts_name(model: type[WireModel]) -> str:
    return model.TS_NAME or model.__name__


def _event_const_name(wire_name: str) -> str:
    """``'gateway.ready'`` -> ``'GATEWAY_READY'`` — a TS-safe SCREAMING_SNAKE key
    for the ``WireEvent`` constant object (used as switch/case labels so no raw
    event-name string literal survives in the TUI)."""

    return "".join(ch if ch.isalnum() else "_" for ch in wire_name).upper()


def _split_optional(annotation: Any) -> tuple[Any, bool]:
    """Return ``(inner, nullable)`` — strips a trailing ``| None`` union.

    ``inner`` is the single remaining type, or a TUPLE of them for a genuine
    multi-member union (``float | dict | str | None`` → ``((float, dict, str),
    True)``) so the emitter can render ``null | number | Record<…> | string``.
    A plain ``X | None`` still returns the single ``X`` — existing output is
    byte-identical.
    """

    if get_origin(annotation) in (Union, UnionType):
        args = get_args(annotation)
        non_none = [a for a in args if a is not _NONE]
        nullable = len(non_none) != len(args)
        if len(non_none) == 1:
            return non_none[0], nullable
        return tuple(non_none), nullable
    return annotation, False


def _ts_scalar(annotation: Any) -> str:
    """Map a (non-optional) python annotation to a TypeScript type."""

    if isinstance(annotation, tuple):
        # A multi-member union — render each member and join, sorted for a
        # deterministic diff-stable line (TS unions are order-independent).
        return " | ".join(sorted(_ts_scalar(member) for member in annotation))

    if isinstance(annotation, type) and issubclass(annotation, WireModel):
        return _ts_name(annotation)

    origin = get_origin(annotation)
    if origin in (list,):
        (inner,) = get_args(annotation)
        return f"{_ts_scalar(inner)}[]"
    if origin in (dict,) or annotation is dict:
        args = get_args(annotation)
        # A typed value (``dict[str, int]`` → ``Record<string, number>``); a bare
        # ``dict`` or ``dict[str, Any]`` stays ``Record<string, unknown>``.
        if len(args) == 2:
            return f"Record<string, {_ts_scalar(args[1])}>"
        return "Record<string, unknown>"

    if annotation is str:
        return "string"
    if annotation is bool:
        return "boolean"
    if annotation in (int, float):
        return "number"
    if annotation is Any:
        return "unknown"

    raise TypeError(f"codegen: no TypeScript mapping for {annotation!r}")


def _field_line(name: str, field: Any) -> str:
    inner, nullable = _split_optional(field.annotation)
    ts = _ts_scalar(inner)
    extra = field.json_schema_extra if isinstance(field.json_schema_extra, dict) else {}
    if extra.get("wireOptional"):
        # Conditionally emitted: the key is DROPPED (absent) when None, never
        # sent as null — so the TS is `name?: T`, not `name?: null | T`.
        # ``wireNullable`` opts a field back INTO the null union: `name?: null | T`
        # for a key the server may omit OR emit as null (the forecast mirrors).
        if extra.get("wireNullable") and nullable:
            return f"  {name}?: null | {ts}"
        return f"  {name}?: {ts}"
    if nullable:
        ts = f"null | {ts}"
    return f"  {name}: {ts}"


def _interface(model: type[WireModel]) -> str:
    lines = [f"export interface {_ts_name(model)} {{"]
    for field_name in sorted(model.model_fields):
        lines.append(_field_line(field_name, model.model_fields[field_name]))
    lines.append("}")
    return "\n".join(lines)


def _collect(models: list[type[WireModel]]) -> list[type[WireModel]]:
    """Transitively collect every model reachable from ``models``, deduped by TS
    name and returned in a stable (sorted) order."""

    seen: dict[str, type[WireModel]] = {}
    stack = list(models)
    while stack:
        model = stack.pop()
        name = _ts_name(model)
        if name in seen:
            continue
        seen[name] = model
        for field in model.model_fields.values():
            inner, _ = _split_optional(field.annotation)
            # A multi-member union yields a tuple; walk every member so nested
            # models referenced only inside a union still get collected.
            for candidate in inner if isinstance(inner, tuple) else (inner,):
                # Unwrap a container to the referenced element/value type: a model
                # nested only inside ``list[Model]`` or ``dict[str, Model]`` must
                # still be discovered and emitted.
                if get_origin(candidate) in (list,):
                    (candidate,) = get_args(candidate)
                elif get_origin(candidate) in (dict,):
                    args = get_args(candidate)
                    candidate = args[1] if len(args) == 2 else Any
                if isinstance(candidate, type) and issubclass(candidate, WireModel):
                    stack.append(candidate)
    return [seen[name] for name in sorted(seen)]


def render() -> str:
    """Render the full ``generated.ts`` source as a string."""

    models = _collect(registered_models())
    event_names = sorted(spec.name for spec in EVENT_SPECS)

    blocks: list[str] = [_HEADER.rstrip("\n")]
    blocks.append(f"export const PROTOCOL_VERSION = {PROTOCOL_VERSION}")

    union = " | ".join(f"'{name}'" for name in event_names)
    blocks.append(f"export type WireEventName = {union}")
    literal = ", ".join(f"'{name}'" for name in event_names)
    blocks.append(f"export const WIRE_EVENT_NAMES: readonly WireEventName[] = [{literal}]")

    # Named constants — the ONLY place a raw event-name literal is allowed to
    # live. Every gw.on/emit/switch-case in the TUI references `WireEvent.X`, so
    # a renamed/removed event is a compile error, never a silent miss.
    const_entries = sorted(
        (_event_const_name(name), name) for name in event_names
    )
    const_lines = "\n".join(f"  {key}: '{name}'," for key, name in const_entries)
    blocks.append(f"export const WireEvent = {{\n{const_lines}\n}} as const")

    for model in models:
        blocks.append(_interface(model))

    return "\n\n".join(blocks) + "\n"


def generated_path() -> Path:
    return _repo_root() / _GENERATED_REL


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    check = "--check" in argv
    path = generated_path()
    rendered = render()

    if check:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != rendered:
            sys.stderr.write(
                "error: generated TypeScript types are STALE.\n"
                f"  {path} does not match the protocol/ models.\n"
                "  fix: run  python -m protocol.codegen  and commit the result.\n"
            )
            return 1
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    sys.stdout.write(f"wrote {path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
