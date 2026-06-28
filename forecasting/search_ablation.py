"""AIA P2.2 — search-ablation 2x2 harness (attribute Brier to search vs judge).

The AIA paper attributes its Brier improvement to two orthogonal components by
running a 2x2 ablation:

    agentic-search  ON / OFF   x   judge/supervisor  ON / OFF

Mean-Brier per cell, then the marginal contribution of each component (the Brier
*reduction* it buys, averaged over the levels of the other component that have
BOTH arms present), plus the non-additive interaction term. A positive
contribution means turning the component ON lowered the mean Brier.

This module is PURE analysis (the decomposition math is unit-tested without a
ledger) plus an honest collector that groups resolved binary backtest cases by
the arm that was ACTUALLY recorded — never by an arm we infer or fabricate. It is
surfaced READ-ONLY (a `forecast ablation` CLI subcommand and an OPT-IN
`include_search_ablation` row in the evidence-status surface). It never touches a
committed forecast, the live default search/judge configuration, or readiness.

Recorded signals (see ``collect_ablation_cells``):

  * SEARCH arm — the linked panel run's ``research_rounds`` (the AIA P1.1
    supervisor fresh-search counter): ``> 0`` means the supervisor ran a fresh
    agentic-search round (search ON); ``0`` means it did not (search OFF). This is
    the most precise RECORDED analog to the paper's search-on/off, not a name
    heuristic; it is sparse until the supervisor search seam is wired live (the
    coverage tally shows this honestly).
  * JUDGE arm — the same linked panel run's ``final_source``: ``"judge_high"``
    (the AIA P0.3 confidence-gated judge override) is judge ON; ``"pool"`` is judge
    OFF. No linked panel run -> NEITHER arm is recorded for that case; it is
    excluded and counted under an honest uncovered tally — never guessed.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

# The four cells of the 2x2, keyed (search_on, judge_on).
_CELLS: tuple[tuple[bool, bool], ...] = (
    (False, False),
    (False, True),
    (True, False),
    (True, True),
)

def _mean(values: Sequence[float]) -> float | None:
    # Guard NaN/inf so a single poisoned Brier cannot silently corrupt a cell mean
    # or make best_cell's min() comparisons undefined.
    vals = [float(v) for v in values if float(v) == float(v) and float(v) not in (float("inf"), float("-inf"))]
    if not vals:
        return None
    return sum(vals) / len(vals)


def ablation_decomposition(
    cells: Mapping[tuple[bool, bool], Sequence[float]],
) -> dict[str, Any]:
    """Decompose a 2x2 search/judge ablation into per-component Brier attribution.

    ``cells`` maps ``(search_on, judge_on)`` -> a list of per-case Brier scores.
    Cells may be missing or empty; a missing cell is one with no recorded cases.

    Returns a dict with:

      * ``cell_brier`` — mean Brier per PRESENT cell, keyed by the cell tuple.
      * ``baseline_cell`` — the ``(False, False)`` mean (search OFF, judge OFF), or
        None when that cell is absent.
      * ``best_cell`` — ``{"cell": (s, j), "brier": <min mean>}`` (lowest mean
        Brier across present cells), or None when no cell is present.
      * ``search_contribution`` — mean Brier *reduction* from turning search ON,
        averaged over the judge levels that have BOTH the search-OFF and search-ON
        arm present. None when no judge level has both arms. A reduction is a
        POSITIVE number.
      * ``judge_contribution`` — the same, for turning judge ON (averaged over the
        search levels that have both judge arms). None when unavailable.
      * ``interaction`` — the non-additive term, only when ALL FOUR cells are
        present: ``(b_FF - b_TF) - (b_FT - b_TT)``. This is
        ``search_effect|judge_off  -  search_effect|judge_on`` — a positive value
        means search helps MORE when the judge is off (sub-additive components).
        None when any cell is absent.
      * ``coverage`` — which of the 4 cells are present, n per present cell, the
        count of present cells, and a ``complete`` flag (all four present).

    Divide-by-zero / missing-cell safe: every contribution is None (never a
    fabricated arm) when the cells it needs are absent, with the gap visible in
    ``coverage``. PURE — no I/O.
    """

    # Mean (and n) per present, non-empty cell.
    cell_brier: dict[tuple[bool, bool], float] = {}
    cell_n: dict[tuple[bool, bool], int] = {}
    for cell in _CELLS:
        values = cells.get(cell)
        if not values:
            continue
        m = _mean(values)
        if m is None:
            continue
        cell_brier[cell] = m
        cell_n[cell] = len(values)

    baseline_cell = cell_brier.get((False, False))

    best_cell: dict[str, Any] | None = None
    if cell_brier:
        best = min(cell_brier.items(), key=lambda kv: kv[1])
        best_cell = {"cell": list(best[0]), "brier": round(best[1], 6)}

    # SEARCH contribution: for each judge level j in {False, True}, if BOTH
    # (False, j) and (True, j) are present, the reduction is b(off) - b(on).
    # Average those reductions over the judge levels that qualify.
    search_reductions: list[float] = []
    for j in (False, True):
        off = cell_brier.get((False, j))
        on = cell_brier.get((True, j))
        if off is not None and on is not None:
            search_reductions.append(off - on)
    search_contribution = _mean(search_reductions)

    # JUDGE contribution: for each search level s, if BOTH (s, False) and
    # (s, True) are present, the reduction is b(judge off) - b(judge on).
    judge_reductions: list[float] = []
    for s in (False, True):
        off = cell_brier.get((s, False))
        on = cell_brier.get((s, True))
        if off is not None and on is not None:
            judge_reductions.append(off - on)
    judge_contribution = _mean(judge_reductions)

    # Interaction (non-additivity) — only when all four cells are present.
    interaction: float | None = None
    if all(cell in cell_brier for cell in _CELLS):
        b_ff = cell_brier[(False, False)]
        b_tf = cell_brier[(True, False)]
        b_ft = cell_brier[(False, True)]
        b_tt = cell_brier[(True, True)]
        interaction = (b_ff - b_tf) - (b_ft - b_tt)

    present_cells = [cell for cell in _CELLS if cell in cell_brier]
    coverage = {
        "present_cells": [list(cell) for cell in present_cells],
        "n_by_cell": {f"{int(s)}{int(j)}": cell_n[(s, j)] for (s, j) in present_cells},
        "present_count": len(present_cells),
        "complete": len(present_cells) == 4,
    }

    return {
        "cell_brier": {f"{int(s)}{int(j)}": round(b, 6) for (s, j), b in cell_brier.items()},
        "baseline_cell": None if baseline_cell is None else round(baseline_cell, 6),
        "best_cell": best_cell,
        "search_contribution": None if search_contribution is None else round(search_contribution, 6),
        "judge_contribution": None if judge_contribution is None else round(judge_contribution, 6),
        "interaction": None if interaction is None else round(interaction, 6),
        "coverage": coverage,
    }


def _search_arm(panel_run: Mapping[str, Any] | None) -> bool | None:
    """Classify the search arm from the snapshot's linked panel run.

    True when the AIA P1.1 supervisor ran a fresh agentic-search round
    (``research_rounds > 0``), False when it did not (``research_rounds == 0``),
    None when no panel run is linked (the arm is NOT recorded — never guessed).
    Using the recorded ``research_rounds`` (rather than a probability-source name
    heuristic) is exact and substring-collision-proof.
    """

    if not panel_run:
        return None
    rounds = panel_run.get("research_rounds")
    if rounds is None:
        return None
    try:
        return int(rounds) > 0
    except (TypeError, ValueError):
        return None


def _judge_arm(panel_run: Mapping[str, Any] | None) -> bool | None:
    """Classify the judge arm from the snapshot's linked panel run.

    True when the confidence-gated judge overrode the pool
    (``final_source == "judge_high"``), False when the pool was committed
    (``final_source == "pool"``), None when no panel run is linked (the judge arm
    is NOT recorded for this case).
    """

    if not panel_run:
        return None
    final_source = str(panel_run.get("final_source") or "").strip().lower()
    if final_source == "judge_high":
        return True
    if final_source == "pool":
        return False
    return None


def collect_ablation_cells(ledger: Any) -> dict[str, Any]:
    """Group resolved BINARY backtest cases by their recorded (search, judge) arm.

    Walks every backtest run's cases, keeps the resolved binary ones with a stored
    Brier, and bins each into a 2x2 cell BY THE ARM THAT WAS ACTUALLY RECORDED:

      * search arm from the linked panel run's ``research_rounds``
        (:func:`_search_arm`), and
      * judge arm from the same panel run's ``final_source`` (:func:`_judge_arm`).

    A case with no linked panel run (NEITHER arm recorded), or whose judge arm is
    unrecognised, is EXCLUDED and tallied under ``uncovered`` (with the reason) —
    never guessed into a cell. Returns ``{"cells": {(s, j): [brier, ...]},
    "uncovered": {...}, "n_cases": N, "n_binned": M}``.
    """

    # Index panel runs by the snapshot they were attached to, so a snapshot can
    # find "its" judge decision. Most recent wins on the (rare) collision.
    panel_by_snapshot: dict[str, Mapping[str, Any]] = {}
    try:
        panel_runs = ledger.list_panel_runs()
    except Exception:  # noqa: BLE001 — a ledger without panels yields no judge arm
        panel_runs = []
    for panel in panel_runs:
        snap_id = panel.get("snapshot_id")
        if snap_id:
            panel_by_snapshot.setdefault(str(snap_id), panel)

    cells: dict[tuple[bool, bool], list[float]] = {}
    uncovered = {
        "no_panel_run": 0,
        "no_judge_marker": 0,
        "not_binary": 0,
        "unscored": 0,
        "read_error": 0,
    }
    n_cases = 0
    n_binned = 0

    for run in ledger.list_backtest_runs():
        run_id = run.get("id")
        if not run_id:
            continue
        for case in ledger.list_backtest_cases(run_id):
            n_cases += 1
            score_id = case.get("score_record_id")
            forecast_id = case.get("generated_forecast_id")
            if not score_id or not forecast_id:
                uncovered["unscored"] += 1
                continue
            try:
                score = ledger.get_score(score_id)
            except Exception:  # noqa: BLE001 — a transient read failure, not "unscored"
                uncovered["read_error"] += 1
                continue
            if score.brier_score is None:
                uncovered["unscored"] += 1
                continue
            try:
                snapshot = ledger.get_snapshot(forecast_id)
                question = ledger.get_question(snapshot.question_id)
            except Exception:  # noqa: BLE001 — a transient read failure, not "unscored"
                uncovered["read_error"] += 1
                continue
            outcome_space = getattr(question, "outcome_space", None)
            if getattr(outcome_space, "type", None) != "binary":
                uncovered["not_binary"] += 1
                continue
            # A proper binary outcome must exist for the stored Brier to be honest.
            if ledger._binary_outcome_value(score, outcome_space) is None:
                uncovered["unscored"] += 1
                continue

            # Both arms come from the one panel run linked to this snapshot, so a
            # case with no panel run has NEITHER arm recorded (counted, not guessed).
            panel = panel_by_snapshot.get(str(forecast_id))
            search_on = _search_arm(panel)
            if search_on is None:
                uncovered["no_panel_run"] += 1
                continue
            judge_on = _judge_arm(panel)
            if judge_on is None:
                uncovered["no_judge_marker"] += 1
                continue

            cells.setdefault((search_on, judge_on), []).append(float(score.brier_score))
            n_binned += 1

    return {
        "cells": cells,
        "uncovered": uncovered,
        "n_cases": n_cases,
        "n_binned": n_binned,
    }


def ablation_report(ledger: Any) -> dict[str, Any]:
    """Read-only 2x2 search/judge ablation over resolved binary backtest cases.

    Ties :func:`collect_ablation_cells` to :func:`ablation_decomposition` and
    surfaces the honest uncovered tally alongside the attribution. Analysis ONLY —
    it never alters a committed forecast and never changes the live default
    search/judge configuration.
    """

    collected = collect_ablation_cells(ledger)
    decomposition = ablation_decomposition(collected["cells"])
    return {
        "n_cases": collected["n_cases"],
        "n_binned": collected["n_binned"],
        "uncovered": collected["uncovered"],
        **decomposition,
    }


__all__ = [
    "ablation_decomposition",
    "collect_ablation_cells",
    "ablation_report",
]
