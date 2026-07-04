"""Render ``docs/reference/hooks-rules.md`` from the built-in forecast hooks.

Source of truth: ``forecasting/hooks/builtins.py`` (``BUILTIN_RULES`` + ``RULE_DOCS``).
Hooks are git-hook-style saturation/style/calibration checks the commit gate runs
on every forecast snapshot; a rule's resolved severity decides warn vs. block.
"""

from __future__ import annotations

from scripts.docgen.common import header

SOURCE = "forecasting/hooks/builtins.py (BUILTIN_RULES, RULE_DOCS)"


def render() -> str:
    from forecasting.hooks.builtins import BUILTIN_RULES, RULE_DOCS

    blocks: list[str] = [
        header(
            "Forecast Hooks (Built-in Rules)",
            SOURCE,
            blurb=(
                f"Before a forecast snapshot commits, the hook engine runs these"
                f" checks. Each rule resolves to a severity — `error` **blocks** the"
                f" commit, `warn` surfaces without blocking, `off` is disabled — via"
                f" the active profile and any per-rule override. `weight` is the"
                f" penalty points a failed rule adds to the saturation score. There"
                f" are **{len(BUILTIN_RULES)} built-in rules**; operators can add"
                f" their own with the hooks DSL."
            ),
        )
    ]

    # Grouped by category, categories and rules sorted for determinism.
    by_category: dict[str, list] = {}
    for rule in BUILTIN_RULES:
        by_category.setdefault(rule.category.value, []).append(rule)

    blocks.append(
        "Severities shown are the **defaults** — the shipped profile or an operator"
        " override can raise or lower any of them (`forecast hooks list` shows the"
        " resolved severity)."
    )

    for category in sorted(by_category):
        rules = sorted(by_category[category], key=lambda r: r.id)
        lines = [f"## {category}", ""]
        lines.append("| rule | default severity | weight | what it checks |")
        lines.append("| --- | --- | --- | --- |")
        for rule in rules:
            doc = " ".join(str(RULE_DOCS.get(rule.id, "")).split())
            blocks_flag = " (blocks)" if rule.default_severity.value == "error" else ""
            lines.append(
                f"| `{rule.id}` | `{rule.default_severity.value}`{blocks_flag}"
                f" | {rule.weight} | {doc} |"
            )
        blocks.append("\n".join(lines))

    blocks.append(
        "Inspect and tune from the CLI: `forecast hooks list` (resolved severities),"
        " `forecast hooks profiles`, `forecast hooks explain <signal>`,"
        " `forecast hooks set-severity <rule> off|warn|error`, and"
        " `forecast hooks add <spec.json>` to author a custom rule. See"
        " [forecasting-methodology.md](../forecasting-methodology.md) for how the"
        " gate fits the desk workflow."
    )

    return "\n\n".join(blocks) + "\n"
