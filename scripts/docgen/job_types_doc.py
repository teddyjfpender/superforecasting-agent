"""Render ``docs/reference/job-types.md`` from the jobs registry.

Source of truth: ``forecasting/jobs/types/`` — every module registers a
``JobType`` on the one detached-job runtime (Arc B). Quorum, reforecast, refresh,
task, and warning-automode are all TYPES on that single runtime.
"""

from __future__ import annotations

from scripts.docgen.common import header, module_docline

SOURCE = "forecasting/jobs/types/ (registered_types + resolve)"


def render() -> str:
    from forecasting.jobs.types import registered_types, resolve

    names = registered_types()  # already sorted

    blocks: list[str] = [
        header(
            "Background Job Types",
            SOURCE,
            blurb=(
                f"Long-running desk work runs as a **detached job** on one runtime"
                f" (`forecasting/jobs/runtime.py`) with shared progress coalescing,"
                f" cancellation, persistence, and desk re-attach. Each capability is"
                f" a registered `JobType`. There are **{len(names)} types**."
                f" `spend_class` `agent` means the job spends model budget (it drives"
                f" the agent); `free` means it does not."
            ),
        )
    ]

    rows = [
        "| type | spend class | min interval (s) | legacy alias namespace | what it does |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name in names:
        jt = resolve(name)
        alias = jt.alias_namespace or "—"
        desc = module_docline(jt.execute) or ""
        rows.append(
            f"| `{jt.name}` | `{jt.spend_class}` | {jt.min_interval_s} | `{alias}` | {desc} |"
        )
    blocks.append("\n".join(rows))

    blocks.append(
        "Jobs are started over the wire via the `jobs.start` RPC and stream"
        " `jobs.progress` / `jobs.complete` / `jobs.error` events (see the"
        " [protocol reference](protocol.md)). A job also runs standalone as a"
        " detached process: `python -m forecasting.jobs run <id>`."
    )

    return "\n\n".join(blocks) + "\n"
