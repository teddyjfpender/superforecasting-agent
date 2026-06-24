"""Resolver framework (feedback #9): structured resolution rules let the desk
PROPOSE a resolution from ingested source data instead of resolving by hand — the
generic metric-threshold engine behind the earnings/benchmark/infrastructure
resolvers. Propose-only: nothing is auto-committed, nothing fabricated."""

from __future__ import annotations

import pytest

from forecasting.ledger import ForecastLedger
from forecasting.models import ValidationError
from forecasting.resolvers import (
    propose_metric_threshold,
    validate_metric_threshold_rule,
)
from forecasting.models import json_dumps, utc_now_iso

CRIT = "Resolves yes if reported segment revenue beats consensus next quarter."
RULE = {"resolver": "metric_threshold", "field": "segment_revenue", "comparator": ">=", "threshold": 5.0, "source_role": "resolver"}


# ── pure engine ──────────────────────────────────────────────────────────────
def test_propose_yes_when_threshold_met():
    p = propose_metric_threshold(question_id="q", rule=RULE, observed_value=5.2)
    assert p.determinable and p.outcome == "yes"


def test_propose_no_when_threshold_missed():
    p = propose_metric_threshold(question_id="q", rule=RULE, observed_value=4.1)
    assert p.determinable and p.outcome == "no"


def test_no_value_is_undetermined_never_fabricated():
    p = propose_metric_threshold(question_id="q", rule=RULE, observed_value=None)
    assert p.determinable is False and p.outcome is None


def test_nan_and_inf_are_undetermined_not_fabricated():
    # NaN/inf are garbage data, not observations — must never produce a YES/NO.
    for bad in (float("nan"), float("inf"), float("-inf")):
        p = propose_metric_threshold(question_id="q", rule=RULE, observed_value=bad)
        assert p.determinable is False and p.outcome is None


def test_rule_validation_flags_problems():
    assert validate_metric_threshold_rule(RULE) == []
    assert validate_metric_threshold_rule({"comparator": "~", "threshold": "x", "field": ""})  # 3 problems


# ── ledger dispatch (reads the latest ingested source value) ──────────────────
def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "r.db"))
    lg.initialize_schema()
    return lg


def _ingest_value(lg, question_id, watched_source_id, field, value):
    # White-box: drop a source snapshot carrying the parsed field the rule reads.
    with lg._connect() as conn:
        conn.execute(
            "INSERT INTO source_snapshots (id, question_id, watched_source_id, source_type, retrieved_at, parsed_values) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("ss_test1", question_id, watched_source_id, "rss", utc_now_iso(), json_dumps({field: value})),
        )


def test_propose_resolution_reads_ingested_value(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Will the segment beat consensus?", resolution_criteria=CRIT)
    ws = lg.add_watched_source(scope_type="question", scope_ref=q.id, source="https://x/earnings", source_type="rss", role="resolver")
    lg.set_resolution_rule(q.id, field="segment_revenue", comparator=">=", threshold=5.0, source_role="resolver")

    # No data yet -> undetermined (and definitely NOT resolved).
    assert lg.propose_resolution(q.id)["determinable"] is False
    assert lg.get_question(q.id).status != "resolved"

    # Source reports a beat -> proposes YES, still uncommitted.
    _ingest_value(lg, q.id, ws["id"], "segment_revenue", 5.6)
    proposal = lg.propose_resolution(q.id)
    assert proposal["determinable"] and proposal["outcome"] == "yes"
    assert proposal["source_ref"] == ws["id"]
    assert lg.get_question(q.id).status != "resolved"  # propose-only


def test_propose_due_resolutions_alerts_once_then_dedups(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Will the segment beat consensus?", resolution_criteria=CRIT)
    ws = lg.add_watched_source(scope_type="question", scope_ref=q.id, source="https://x/e", source_type="rss", role="resolver")
    lg.set_resolution_rule(q.id, field="segment_revenue", comparator=">=", threshold=5.0)

    # No data yet -> nothing proposed.
    assert lg.propose_due_resolutions() == []

    _ingest_value(lg, q.id, ws["id"], "segment_revenue", 6.2)
    first = lg.propose_due_resolutions()
    assert len(first) == 1 and first[0]["outcome"] == "yes" and first[0]["alerted"] is True
    # Exactly one confirm-me alert raised; the question is NOT auto-resolved.
    open_alerts = [a for a in lg.list_alerts(unresolved_only=True) if "resolution proposed" in a.reason.lower()]
    assert len(open_alerts) == 1
    assert lg.get_question(q.id).status != "resolved"

    # Second sweep dedups against the open alert (no re-alert spam).
    second = lg.propose_due_resolutions()
    assert second[0]["alerted"] is False
    open_after = [a for a in lg.list_alerts(unresolved_only=True) if "resolution proposed" in a.reason.lower()]
    assert len(open_after) == 1


def test_flipped_outcome_re_alerts(tmp_path):
    # If the data flips the proposal (YES -> NO), the operator MUST see the new one;
    # the outcome-aware dedup must not suppress a changed outcome.
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Will the segment beat consensus?", resolution_criteria=CRIT)
    ws = lg.add_watched_source(scope_type="question", scope_ref=q.id, source="https://x/e", source_type="rss", role="resolver")
    lg.set_resolution_rule(q.id, field="segment_revenue", comparator=">=", threshold=5.0)

    _ingest_value(lg, q.id, ws["id"], "segment_revenue", 6.2)  # YES
    assert lg.propose_due_resolutions()[0]["alerted"] is True
    # A later, lower reading flips it to NO -> must raise a fresh alert (not skip).
    with lg._connect() as conn:
        conn.execute(
            "INSERT INTO source_snapshots (id, question_id, watched_source_id, source_type, retrieved_at, parsed_values) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("ss_flip", q.id, ws["id"], "rss", "2999-01-01T00:00:00Z", json_dumps({"segment_revenue": 4.0})),
        )
    flipped = lg.propose_due_resolutions()
    assert flipped[0]["outcome"] == "no" and flipped[0]["alerted"] is True


def test_no_rule_returns_none(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="No rule here?", resolution_criteria=CRIT)
    assert lg.propose_resolution(q.id) is None


def test_set_rule_rejects_bad_inputs(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Q?", resolution_criteria=CRIT)
    with pytest.raises(ValidationError):
        lg.set_resolution_rule(q.id, field="x", comparator="~", threshold=1.0)  # bad comparator
    with pytest.raises(ValidationError):
        lg.set_resolution_rule(q.id, field="x", comparator=">=", threshold=1.0, source_role="bogus")
