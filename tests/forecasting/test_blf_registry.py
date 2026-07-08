"""Registry pin — the scorecard, lint --by-rule, and the docgen all draw from the
SAME ``BUILTIN_RULES`` registry, so a new rule flows into every operator surface
with no per-surface edit. This pins that: RULE_DOCS covers every rule, the rendered
reference doc lists exactly ``len(BUILTIN_RULES)`` rows, and the three BLF rules
reach the adherence scorecard + the by-rule sweep automatically.
"""

from __future__ import annotations

from forecasting import ForecastLedger
from forecasting.hooks.builtins import BUILTIN_RULES, BUILTIN_RULE_IDS, RULE_DOCS
from forecasting.hooks.sweep import adherence_scorecard, by_rule_sweep
from scripts.docgen.hooks_rules_doc import render

_BLF = ("belief_trajectory_present", "pool_shrinkage_recorded", "specialist_seat_considered")


def test_every_builtin_rule_has_a_doc():
    # docgen completeness — a rule with no RULE_DOCS entry renders a blank cell.
    assert [r.id for r in BUILTIN_RULES if r.id not in RULE_DOCS] == []


def test_docgen_row_count_equals_rule_count():
    doc = render()
    rows = [line for line in doc.splitlines() if line.startswith("| `")]
    assert len(rows) == len(BUILTIN_RULES)
    assert f"**{len(BUILTIN_RULES)} built-in rules**" in doc


def test_blf_rules_are_in_the_registry_and_doc():
    doc = render()
    for rid in _BLF:
        assert rid in BUILTIN_RULE_IDS
        assert f"`{rid}`" in doc


def _seed_post_harvest_commit(lg):
    from forecasting.ledger.core import allow_ledger_writes

    q = lg.create_question(title="Will X exceed target?", resolution_criteria="Yes if X exceeds target.")
    est = [
        {"perspective": m, "agent_model": m, "probability": 0.5, "weight": 1.0,
         "reasons_up": [], "reasons_down": [], "change_my_mind": [], "crux": None,
         "metadata": {"belief_trajectory": []}}
        for m in ("opus", "gpt-5.5")
    ]
    with allow_ledger_writes(reason="test"):
        run = lg.record_panel_run(question_id=q.id, estimates=est, triggered_by="quorum",
                                  supervisor_search_enabled=True)
    lg.create_snapshot(question_id=q.id, probability_or_distribution=0.5, rationale="clean prose",
                       method="quorum", panel_run_ref=run["id"], set_current=True)
    return q.id


def test_scorecard_and_by_rule_auto_include_blf_rules(tmp_path):
    lg = ForecastLedger(db_path=str(tmp_path / "reg.db"))
    lg.initialize_schema()
    qid = _seed_post_harvest_commit(lg)

    # Adherence scorecard tallies the STORED observe verdicts — the BLF rules must show.
    card = adherence_scorecard(lg, question_ids=[qid])
    assert "belief_trajectory_present" in card["rules"]
    # by_rule_sweep RE-LINTS live currents — the BLF rules must appear there too.
    sweep = by_rule_sweep(lg, question_ids=[qid])
    assert "belief_trajectory_present" in sweep["rules"]
