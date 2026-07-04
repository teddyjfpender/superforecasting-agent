"""Render ``docs/reference/tool-actions.md`` from the forecast tool's action schema.

Source of truth: ``tools/forecasting_tool.py`` — the ``FORECAST_LEDGER_SCHEMA``
dict registered as the ``forecast_ledger`` tool. The agent drives the entire
forecast desk through this one tool; every ``action`` is one operation.
"""

from __future__ import annotations

from typing import Any

from scripts.docgen.common import header

SOURCE = "tools/forecasting_tool.py (FORECAST_LEDGER_SCHEMA)"


def _schema() -> dict[str, Any]:
    from tools.forecasting_tool import FORECAST_LEDGER_SCHEMA

    return FORECAST_LEDGER_SCHEMA


def _param_type(spec: dict[str, Any]) -> str:
    t = spec.get("type", "")
    if t == "array":
        items = spec.get("items", {})
        it = items.get("type") if isinstance(items, dict) else None
        return f"array<{it}>" if it else "array"
    return str(t) if t else "any"


def _allowed(spec: dict[str, Any]) -> str:
    enum = spec.get("enum")
    if isinstance(enum, list) and enum:
        joined = ", ".join(f"`{v}`" for v in enum)
        return joined if len(joined) <= 220 else f"{len(enum)} values (see source)"
    return ""


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def render() -> str:
    schema = _schema()
    name = schema.get("name", "forecast_ledger")
    props: dict[str, Any] = schema["parameters"]["properties"]
    actions = list(props["action"]["enum"])
    required = schema["parameters"].get("required", [])

    blocks: list[str] = [
        header(
            "Forecast Tool Actions",
            SOURCE,
            blurb=(
                f"The agent operates the forecast desk through a single tool,"
                f" **`{name}`**. Its `action` parameter selects one of"
                f" **{len(actions)} operations**; the remaining parameters form a"
                f" shared bag (each operation reads the subset it needs). The only"
                f" globally-required parameter is `{', '.join(required) or 'action'}`;"
                f" per-action requirements are enforced in the handler."
            ),
        )
    ]

    blocks.append("## Actions\n")
    blocks.append(_one_line(schema.get("description", "")))
    rows = ["| action |", "| --- |"]
    for action in sorted(actions):
        rows.append(f"| `{action}` |")
    blocks.append("\n".join(rows))

    # Highlight the sub-mode enums that select routines within an action.
    submodes = [
        ("bayes_action", "the `bayes` action's Bayesian/distributional routine"),
        ("pm_mode", "the `pm_query` action's read mode"),
        ("market_query_kind", "the `market_query` action's read mode"),
        ("stage", "the `pipeline`/`protocol` forecast stage"),
        ("source_type", "the evidence-source adapter for `import_source_evidence`"),
    ]
    submode_lines: list[str] = []
    for key, note in submodes:
        spec = props.get(key)
        if not isinstance(spec, dict):
            continue
        enum = spec.get("enum")
        if not isinstance(enum, list) or not enum:
            continue
        values = ", ".join(f"`{v}`" for v in enum)
        submode_lines.append(f"- **`{key}`** — {note}: {values}")
    if submode_lines:
        blocks.append("## Sub-mode selectors\n")
        blocks.append(
            "Several actions branch on a secondary enum parameter (e.g. `bayes` picks"
            " a routine via `bayes_action`):"
        )
        blocks.append("\n".join(submode_lines))

    # Full parameter reference (sorted; `action` first for readability).
    blocks.append("## Parameters\n")
    blocks.append(
        "Every parameter the tool accepts, sorted by name. Descriptions are often"
        " prefixed with the action they apply to."
    )
    prows = ["| parameter | type | allowed values | description |", "| --- | --- | --- | --- |"]
    for pname in sorted(props):
        spec = props[pname]
        if not isinstance(spec, dict):
            continue
        desc = _one_line(spec.get("description", ""))
        prows.append(
            f"| `{pname}` | {_param_type(spec)} | {_allowed(spec)} | {desc} |"
        )
    blocks.append("\n".join(prows))

    return "\n\n".join(blocks) + "\n"
