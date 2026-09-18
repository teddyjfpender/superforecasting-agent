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
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel

from protocol import EVENT_SPECS, PROTOCOL_VERSION, RPC_SPECS, registered_models

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


def _ts_name(model: type[BaseModel]) -> str:
    return getattr(model, "TS_NAME", "") or model.__name__


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

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _ts_name(annotation)

    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        return " | ".join(sorted(_ts_scalar(member) for member in get_args(annotation)))
    if origin is Literal:
        # A ``Literal['a', 'b']`` becomes a TS string-literal union — sorted for a
        # deterministic diff-stable line (TS unions are order-independent). String
        # members are quoted; bool/int members render as their TS scalar.
        members = [
            f"'{arg}'" if isinstance(arg, str) else _ts_scalar(type(arg))
            for arg in get_args(annotation)
        ]
        return " | ".join(sorted(members))
    if origin in (tuple,):
        args = get_args(annotation)
        if len(args) == 2 and args[1] is Ellipsis:
            return f"Array<{_ts_scalar(args[0])}>"
        # A fixed-length ``tuple[str, str]`` → ``[string, string]`` (POSITIONAL —
        # never sorted; a TS tuple's order is significant).
        return "[" + ", ".join(_ts_scalar(a) for a in get_args(annotation)) + "]"
    if origin in (list,):
        (inner,) = get_args(annotation)
        scalar = _ts_scalar(inner)
        return f"({scalar})[]" if " | " in scalar else f"{scalar}[]"
    if origin in (dict,) or annotation is dict:
        args = get_args(annotation)
        # A typed value (``dict[str, int]`` → ``Record<string, number>``); a bare
        # ``dict`` or ``dict[str, Any]`` stays ``Record<string, unknown>``.
        if len(args) == 2:
            return f"Record<string, {_ts_scalar(args[1])}>"
        return "Record<string, unknown>"

    if annotation is _NONE:
        return "null"
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


def _interface(model: type[BaseModel]) -> str:
    if getattr(model, "__pydantic_root_model__", False):
        return f"export type {_ts_name(model)} = {_ts_scalar(model.model_fields['root'].annotation)}"
    lines = [f"export interface {_ts_name(model)} {{"]
    for field_name in sorted(model.model_fields):
        lines.append(_field_line(field_name, model.model_fields[field_name]))
    lines.append("}")
    return "\n".join(lines)


def _collect(models: list[type[BaseModel]]) -> list[type[BaseModel]]:
    """Transitively collect every model reachable from ``models``, deduped by TS
    name and returned in a stable (sorted) order."""

    seen: dict[str, type[BaseModel]] = {}
    stack = list(models)
    while stack:
        model = stack.pop()
        name = _ts_name(model)
        if name in seen:
            if seen[name] is not model and _interface(seen[name]) != _interface(model):
                raise ValueError(
                    f"codegen: incompatible models share TypeScript name {name!r}; set an explicit unique TS_NAME"
                )
            continue
        seen[name] = model
        candidates = [field.annotation for field in model.model_fields.values()]
        while candidates:
            candidate = candidates.pop()
            if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                stack.append(candidate)
            elif get_origin(candidate) in (list, tuple, dict, Union, UnionType):
                candidates.extend(
                    arg for arg in get_args(candidate) if arg is not Ellipsis
                )
    return [seen[name] for name in sorted(seen)]


def render() -> str:
    """Render the full ``generated.ts`` source as a string."""

    from protocol.server_requests import SERVER_REQUESTS

    models = _collect(registered_models())
    event_names = sorted(spec.name for spec in EVENT_SPECS)

    blocks: list[str] = [_HEADER.rstrip("\n")]
    blocks.append(f"export const PROTOCOL_VERSION = {PROTOCOL_VERSION}")

    union = " | ".join(f"'{name}'" for name in event_names)
    blocks.append(f"export type WireEventName = {union}")
    literal = ", ".join(f"'{name}'" for name in event_names)
    blocks.append(
        f"export const WIRE_EVENT_NAMES: readonly WireEventName[] = [{literal}]"
    )

    # Named constants — the ONLY place a raw event-name literal is allowed to
    # live. Every gw.on/emit/switch-case in the TUI references `WireEvent.X`, so
    # a renamed/removed event is a compile error, never a silent miss.
    const_entries = sorted((_event_const_name(name), name) for name in event_names)
    const_lines = "\n".join(f"  {key}: '{name}'," for key, name in const_entries)
    blocks.append(f"export const WireEvent = {{\n{const_lines}\n}} as const")

    for model in models:
        blocks.append(_interface(model))

    names = ", ".join(repr(name) for name in sorted(SERVER_REQUESTS))
    blocks.append(f"export const SERVER_REQUEST_NAMES = [{names}] as const")
    server_methods = ["export interface ServerRequestMethods {"]
    for name, (request, result) in sorted(SERVER_REQUESTS.items()):
        server_methods.append(
            f"  '{name}': {{ params: Omit<{_ts_name(request)}, 'request_id'> & {{ session_id: string }}; result: {_ts_name(result)} }}"
        )
    server_methods.append("}")
    blocks.append("\n".join(server_methods))

    methods = ["export interface RpcMethods {"]
    for spec in sorted(RPC_SPECS, key=lambda item: item.method):
        methods.append(f"  '{spec.method}': {{")
        if not spec.request.model_fields:
            methods.append("    params: Record<string, never>")
            methods.append(f"    result: {_ts_name(spec.response)}")
            methods.append("  }")
            continue
        methods.append("    params: {")
        for name, field in sorted(spec.request.model_fields.items()):
            line = _field_line(name, field)
            if not field.is_required() and f"{name}?:" not in line:
                line = line.replace(f"{name}:", f"{name}?:", 1)
            methods.append("    " + line)
        methods.append("    }")
        methods.append(f"    result: {_ts_name(spec.response)}")
        methods.append("  }")
    methods.append("}")
    blocks.append("\n".join(methods))
    blocks.append("export type RpcMethod = keyof RpcMethods")
    blocks.append(
        "export type RpcArgs<M extends RpcMethod> = {} extends RpcMethods[M]['params'] ? [params?: RpcMethods[M]['params']] : [params: RpcMethods[M]['params']]"
    )
    blocks.append(
        "export type RpcRequest = <M extends RpcMethod>(method: M, ...args: RpcArgs<M>) => Promise<RpcMethods[M]['result']>"
    )

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
