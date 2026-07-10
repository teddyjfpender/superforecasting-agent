"""Workspace panel-detail section (carved from ``dashboard.py``).

The Wave-4 §W3.b ``panel`` section: the multi-perspective panel-run detail card
(``_workspace_panel``) and the compact BLF belief-trajectory line
(``_belief_trajectory_line``) the workspace payload attaches to each forecast.
Imported back into :mod:`forecasting.dashboard.core` (``build_workspace_payload``
builds the panel section) and re-exported by the façade unchanged.
"""
from __future__ import annotations

from typing import Any

def _belief_trajectory_line(metadata: Any) -> str | None:
    """A compact 'what moved the number' line for one panelist from its BLF belief
    trajectory: the belief ARC (first→last probability) plus what moved the last
    step (``moved_by``). None when the panelist carried no trajectory (a legacy /
    pre-harvest estimate), so the modal simply omits the line rather than faking one."""
    if not isinstance(metadata, dict):
        return None
    traj = metadata.get("belief_trajectory")
    if not isinstance(traj, list) or not traj:
        return None
    steps = [s for s in traj if isinstance(s, dict)]
    if not steps:
        return None

    def _p(step: dict[str, Any]) -> str | None:
        v = step.get("probability")
        return f"{float(v):.0%}" if isinstance(v, (int, float)) else None

    first, last = _p(steps[0]), _p(steps[-1])
    arc = f"{first}→{last}" if (first and last and len(steps) > 1) else (last or first)
    moved = str(steps[-1].get("moved_by") or "").strip()
    n = len(steps)
    head = f"{arc} · {n} step{'s' if n != 1 else ''}" if arc else f"{n} step{'s' if n != 1 else ''}"
    return f"{head} · moved by: {moved}" if moved else head


def _workspace_panel(run: dict[str, Any]) -> dict[str, Any]:
    estimates = [
        {
            "perspective": row.get("perspective"),
            "probability": row.get("probability"),
            "weight": row.get("weight"),
            "trimmed": bool(row.get("trimmed")),
            "crux": row.get("crux"),
            "confidence_low": row.get("confidence_low"),
            "confidence_high": row.get("confidence_high"),
            # BLF A1 — the compact per-panelist belief arc for the desk panel modal.
            "belief": _belief_trajectory_line(row.get("metadata")),
        }
        for row in (run.get("estimates") or [])
    ]
    return {
        "id": run.get("id"),
        "created_at": run.get("created_at"),
        "aggregation_method": run.get("aggregation_method"),
        "trim": run.get("trim"),
        "aggregate_probability": run.get("aggregate_probability"),
        # AIA P0.3: which branch produced the committed aggregate
        # ('pool' | 'judge_high'), defaulting to 'pool' for pre-P0.3 runs.
        "final_source": run.get("final_source") or "pool",
        "spread": run.get("spread_summary") or {},
        "estimates": estimates,
    }
