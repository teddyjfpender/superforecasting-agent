"""Presentation schema — the agent ↔ TUI contract for Market Models.

A Presentation is a versioned header plus an ordered list of typed render
"blocks". The forecasting agent emits one (via the ``emit_market_presentation``
tool); the TUI renders each block by ``type`` with a tolerant fallback so an
unknown/extended type never crashes the view. ``validate_presentation`` runs
before persistence to keep the contract honest.

This module is deliberately dependency-light (stdlib only) so it can be imported
by the gateway, the tools, and tests without pulling in numpy/agent machinery.
"""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "market-presentation-v1"

# Block types the renderer knows how to draw. Unknown types still render (title +
# note + raw JSON) but validation flags them so we notice drift early.
BLOCK_TYPES: frozenset[str] = frozenset(
    {
        "narrative",
        "finding",
        "metric",
        "timeseries",
        "scatter",
        "regression",
        "bars",
        "table",
        "fan",
        "scenario",
        "assumptions",
        "sources",
    }
)

_STATUSES = frozenset({"complete", "partial", "failed"})

# Per-type required fields (beyond the common {type,id}). Kept intentionally
# small — the renderer is defensive, so we only require what it cannot invent.
_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "narrative": ("body",),
    "finding": ("claim",),
    "metric": ("label", "value"),
    "timeseries": ("series",),
    "scatter": ("points",),
    "regression": ("r2", "coeffs"),
    "bars": ("series",),
    "table": ("columns", "rows"),
    "fan": ("x", "median"),
    "scenario": ("scenarios",),
    "assumptions": ("items",),
    "sources": ("items",),
}


def new_block_id(prefix: str, index: int) -> str:
    """Stable, human-readable block id (no randomness — replayable)."""
    return f"{prefix}-{index}"


def validate_presentation(obj: Any) -> tuple[bool, list[str]]:
    """Return ``(ok, errors)``. Non-raising: callers decide how to handle.

    Enforces the structural contract: a dict header with a ``blocks`` list whose
    entries each have a known ``type`` + their required fields. ``ok`` is True
    only when there are zero errors; ``errors`` always lists every problem so a
    self-repair loop can fix them in one pass.
    """
    errors: list[str] = []

    if not isinstance(obj, dict):
        return False, ["presentation must be a JSON object"]

    if not str(obj.get("title") or "").strip():
        errors.append("missing title")

    status = obj.get("status")
    if status is not None and status not in _STATUSES:
        errors.append(f"status must be one of {sorted(_STATUSES)}; got {status!r}")

    blocks = obj.get("blocks")
    if not isinstance(blocks, list):
        return False, errors + ["blocks must be a list"]

    seen_ids: set[str] = set()
    for i, block in enumerate(blocks):
        where = f"blocks[{i}]"
        if not isinstance(block, dict):
            errors.append(f"{where} must be an object")
            continue

        btype = block.get("type")
        if not isinstance(btype, str) or not btype:
            errors.append(f"{where} missing type")
            continue
        if btype not in BLOCK_TYPES:
            errors.append(f"{where} unknown type {btype!r} (renders as fallback)")

        bid = block.get("id")
        if isinstance(bid, str) and bid:
            if bid in seen_ids:
                errors.append(f"{where} duplicate id {bid!r}")
            seen_ids.add(bid)

        for field in _REQUIRED_FIELDS.get(btype, ()):  # type: ignore[arg-type]
            if field not in block or block.get(field) in (None, ""):
                errors.append(f"{where} ({btype}) missing required field {field!r}")

    return (len([e for e in errors if "renders as fallback" not in e]) == 0), errors


def build_presentation(
    *,
    model_id: str,
    version: int,
    title: str,
    question: str,
    blocks: list[dict],
    summary: str = "",
    status: str = "complete",
    as_of_analysis: str | None = None,
    as_of_data: str | None = None,
    data_refs: list[str] | None = None,
    model_run_refs: list[str] | None = None,
    diagnostics: dict | None = None,
) -> dict[str, Any]:
    """Assemble a normalized Presentation header. Ensures every block has an id."""
    normalized: list[dict] = []
    for i, block in enumerate(blocks or []):
        if not isinstance(block, dict):
            continue
        b = dict(block)
        if not b.get("id"):
            b["id"] = new_block_id(str(b.get("type") or "block"), i)
        normalized.append(b)

    return {
        "schema_version": SCHEMA_VERSION,
        "model_id": model_id,
        "version": version,
        "title": title,
        "question": question,
        "summary": summary,
        "status": status if status in _STATUSES else "complete",
        "as_of_analysis": as_of_analysis,
        "as_of_data": as_of_data,
        "blocks": normalized,
        "data_refs": list(data_refs or []),
        "model_run_refs": list(model_run_refs or []),
        "diagnostics": dict(diagnostics or {}),
    }


def sanitize_presentation_prose(presentation: dict) -> dict:
    """Apply house-style text cleanup to prose-bearing blocks in place-ish.

    Reuses ``forecasting.writeup.sanitize_writeup_text`` (the canonical em-dash /
    whitespace enforcer) on narrative bodies, finding claims, and notes. Returns
    the same dict for chaining. Best-effort: if writeup import fails, returns the
    presentation untouched.
    """
    try:
        from forecasting.writeup import sanitize_writeup_text
    except Exception:
        return presentation

    for block in presentation.get("blocks", []):
        if not isinstance(block, dict):
            continue
        for key in ("body", "claim", "note", "title", "caption"):
            if isinstance(block.get(key), str):
                block[key] = sanitize_writeup_text(block[key])
    if isinstance(presentation.get("summary"), str):
        presentation["summary"] = sanitize_writeup_text(presentation["summary"])
    return presentation
