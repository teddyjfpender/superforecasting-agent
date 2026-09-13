"""Promotion behavior tests and opt-in audits of an explicitly supplied ledger.

The ordinary suite uses isolated fixtures. Set FORECAST_TEST_AUDIT_DB to a
review copy to run the historical promotion pre-checks; never discover the
operator's personal ledger implicitly.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from forecasting.hooks import by_rule_sweep, promotion_queue
from forecasting.hooks.profiles import profile_severities
from forecasting.hooks.spec import Severity

# The rules the 2026-07-09 wave verified at 100% live pass and holds at ERROR in the
# standard profile. Six were promoted WARN->ERROR in this wave;
# ``require_outside_view_anchor`` was already ERROR from an earlier promotion and is
# re-verified here so the wave's proof covers the full sweep-2 set. Every rule listed
# MUST be ERROR in standard (this list IS the contract) and MUST pass on every live
# active (the pre-check below). ``lessons_applied`` was verified 0-live-fail too but
# is deliberately HELD at WARN — ERROR would brick the documented live opt-out
# ``use_active_lessons=false`` (see HELD_AT_WARN below).
PROMOTED_2026_07_09 = (
    "terminal_calibration_applied",
    "uncertainty_width_sane",
    "quorum_judged",
    "calibration_bias_applied",
    "crux_named",
    "belief_trajectory_present",
    "require_outside_view_anchor",  # already ERROR pre-wave; re-verified
)

# Verified 0-live-fail but intentionally NOT promoted (promotion would brick a
# documented flow). Kept as a contract so a future refactor cannot quietly flip it.
HELD_AT_WARN = ("lessons_applied",)


def _live_ledger_path() -> Path:
    """Explicit audit input; ordinary test runs never select a personal book."""
    explicit = os.environ.get("FORECAST_TEST_AUDIT_DB")
    if not explicit:
        pytest.skip("live audit requires an explicit isolated FORECAST_TEST_AUDIT_DB")
    return Path(explicit)


def test_every_promoted_rule_is_error_in_standard():
    """The promotion landed: each promoted rule blocks in the standard profile."""
    std = profile_severities("standard")
    for rid in PROMOTED_2026_07_09:
        assert std[rid] is Severity.ERROR, rid


def test_held_rule_stays_warn_in_standard():
    """lessons_applied is deliberately held at WARN: ERROR would brick the documented
    live opt-out use_active_lessons=false. The hold is part of the contract, and the
    queue must ANNOTATE it so the advisor never reads as an instruction to flip it."""
    from forecasting.hooks.profiles import PROMOTION_HOLDS

    std = profile_severities("standard")
    for rid in HELD_AT_WARN:
        assert std[rid] is Severity.WARN, rid
        assert rid in PROMOTION_HOLDS, rid


def test_promotion_queue_annotates_holds(monkeypatch):
    from forecasting.hooks import sweep as sweep_mod

    fake = {
        "questions_scored": 10,
        "rules": {"lessons_applied": {"checked": 10, "failed_warn": 0, "failed_block": 0, "failed": 0}},
    }
    monkeypatch.setattr(sweep_mod, "by_rule_sweep", lambda *a, **k: fake)
    q = promotion_queue(object())
    row = next(r for r in q["promotable"] if r["rule_id"] == "lessons_applied")
    assert "use_active_lessons" in row.get("hold", "")


@pytest.mark.parametrize("rule_id", PROMOTED_2026_07_09)
def test_promoted_rule_has_zero_live_failures(rule_id):
    """PRE-CHECK: the promoted rule passes on EVERY live active (read-only re-lint),
    so flipping it to ERROR blocks nothing currently on the books. If this fails,
    the sweep data has aged and the rule should have stayed WARN — leave it WARN and
    report (per the promotion instruction), do NOT weaken this assertion."""
    db = _live_ledger_path()
    if not db.exists():
        pytest.skip(f"no live ledger at {db} — pre-check is an environment proof")
    from forecasting.ledger.core import ForecastLedger

    table = by_rule_sweep(ForecastLedger(str(db)))
    bucket = table["rules"].get(rule_id)
    failed = bucket["failed"] if bucket else 0
    assert failed == 0, (
        f"{rule_id} shows {failed} live failure(s) across {table['questions_scored']} "
        f"live actives — promoting it to ERROR would brick those commits; keep it WARN"
    )


def test_promotion_queue_partitions_and_excludes_error_rules(monkeypatch):
    """Unit-level: the queue lists ONLY WARN-in-standard rules, partitions them by
    live failure count, and never surfaces a rule already at ERROR (a just-promoted
    rule drops off the queue) or a rule with no live evaluations."""
    from forecasting.hooks import sweep as sweep_mod

    def _r(checked, failed):
        return {"checked": checked, "failed_warn": failed, "failed_block": 0, "failed": failed}

    fake = {
        "questions_scored": 100,
        "rules": {
            "pool_shrinkage_recorded": _r(5, 0),   # WARN in standard, clean -> promotable
            "reasoning_composition": _r(80, 12),   # WARN in standard, fails  -> blocked
            "calibration_bias_applied": _r(90, 0),  # ERROR in standard        -> excluded
            "quorum_judged": _r(90, 0),            # ERROR in standard         -> excluded
            "specialist_seat_considered": _r(0, 0),  # WARN but never evaluated -> excluded
        },
    }
    monkeypatch.setattr(sweep_mod, "by_rule_sweep", lambda *a, **k: fake)

    q = promotion_queue(object())
    promotable = {r["rule_id"] for r in q["promotable"]}
    blocked = {r["rule_id"] for r in q["blocked"]}

    assert promotable == {"pool_shrinkage_recorded"}
    assert blocked == {"reasoning_composition"}
    # ERROR-in-standard rules never appear in either list.
    assert "calibration_bias_applied" not in promotable | blocked
    assert "quorum_judged" not in promotable | blocked
    # A rule with 0 live evaluations is not a candidate (no evidence it passes).
    assert "specialist_seat_considered" not in promotable | blocked
    # Every promotable row is genuinely clean; every blocked row genuinely fails.
    assert all(r["failed"] == 0 for r in q["promotable"])
    assert all(r["failed"] > 0 for r in q["blocked"])
    assert q["questions_scored"] == 100


def test_promotion_queue_never_lists_a_promoted_rule_against_live():
    """End-to-end against the live ledger: none of the just-promoted rules can appear
    in the queue (they are ERROR now), and every promotable row is a clean WARN."""
    db = _live_ledger_path()
    if not db.exists():
        pytest.skip(f"no live ledger at {db}")
    from forecasting.ledger.core import ForecastLedger

    q = promotion_queue(ForecastLedger(str(db)))
    listed = {r["rule_id"] for r in q["promotable"]} | {r["rule_id"] for r in q["blocked"]}
    for rid in PROMOTED_2026_07_09:
        assert rid not in listed, rid
    std = profile_severities("standard")
    for r in q["promotable"]:
        assert std[r["rule_id"]] is not Severity.ERROR
        assert r["failed"] == 0


def test_cmd_hooks_promotions_renders(capsys, tmp_path):
    """The CLI verb runs and prints the queue header (JSON + human paths)."""
    from forecasting import ForecastLedger
    db = tmp_path / "ledger.db"
    ForecastLedger(db)
    from forecasting.cli import _cmd_hooks_promotions

    _cmd_hooks_promotions(SimpleNamespace(db=str(db), json=False))
    out = capsys.readouterr().out
    assert "promotion queue" in out.lower()

    _cmd_hooks_promotions(SimpleNamespace(db=str(db), json=True))
    import json as _json

    payload = _json.loads(capsys.readouterr().out.strip())
    assert set(payload) >= {"questions_scored", "promotable", "blocked", "standard_warn_rules"}
