"""Render ``docs/reference/protocol.md`` from the protocol registry.

Source of truth: ``protocol/__init__.py`` (``RPC_SPECS``, ``EVENT_SPECS``) and the
pydantic request/response/event models under ``protocol/rpc`` + ``protocol/events``.
"""

from __future__ import annotations

from protocol import EVENT_SPECS, PROTOCOL_VERSION, RPC_SPECS, registered_models
from protocol.codegen import _collect, _ts_name
from scripts.docgen.common import header, model_fields_table

SOURCE = "protocol/__init__.py (RPC_SPECS, EVENT_SPECS) + protocol/rpc, protocol/events"


def render() -> str:
    blocks: list[str] = [
        header(
            "Gateway Wire Protocol",
            SOURCE,
            blurb=(
                f"The gateway speaks **protocol version {PROTOCOL_VERSION}**. Every"
                f" request, response, and event below is a pydantic model in the"
                f" `protocol/` package; the TUI's TypeScript wire types"
                f" (`ui-tui/src/protocol/generated.ts`) are generated from the same"
                f" registry via `python -m protocol.codegen`. There are"
                f" **{len(RPC_SPECS)} RPCs** and **{len(EVENT_SPECS)} events**."
            ),
        )
    ]

    # ── RPC summary table ────────────────────────────────────────────────────
    blocks.append("## RPC methods\n")
    rpc_rows = ["| method | request | response |", "| --- | --- | --- |"]
    for spec in sorted(RPC_SPECS, key=lambda s: s.method):
        rpc_rows.append(
            f"| `{spec.method}` | [`{_ts_name(spec.request)}`](#{_anchor(_ts_name(spec.request))})"
            f" | [`{_ts_name(spec.response)}`](#{_anchor(_ts_name(spec.response))}) |"
        )
    blocks.append("\n".join(rpc_rows))

    # ── event summary table ──────────────────────────────────────────────────
    blocks.append("## Events\n")
    ev_rows = ["| event | payload |", "| --- | --- |"]
    for spec in sorted(EVENT_SPECS, key=lambda s: s.name):
        ev_rows.append(
            f"| `{spec.name}` | [`{_ts_name(spec.model)}`](#{_anchor(_ts_name(spec.model))}) |"
        )
    blocks.append("\n".join(ev_rows))

    # ── model field schemas (every reachable model, sorted) ──────────────────
    blocks.append("## Model schemas\n")
    blocks.append(
        "Every model reachable from the registry, sorted by name. Types mirror the"
        " generated TypeScript (`list[X]` → `X[]`, `X | None` → nullable, `?` marks"
        " a conditionally-emitted key)."
    )
    for model in _collect(registered_models()):
        name = _ts_name(model)
        lines = [f"### {name}", ""]
        lines.extend(model_fields_table(model))
        blocks.append("\n".join(lines).rstrip())

    return "\n\n".join(blocks) + "\n"


def _anchor(name: str) -> str:
    """GitHub-style heading anchor for a model name (lowercased)."""

    return name.lower()
