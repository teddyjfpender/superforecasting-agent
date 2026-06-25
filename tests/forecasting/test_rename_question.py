"""rename_question: the only safe in-place question-identity edit. The agent reported it
had no way to rename binary questions, so it buried candidate names in metadata. This
renames the title, re-checks the generic-title rule, and audits the prior title — leaving
id/snapshots/scores untouched (nothing keys off the title)."""

from __future__ import annotations

import pytest

from forecasting.ledger import ForecastLedger
from forecasting.models import OutcomeSpace

_CRIT = "Resolves YES if the named candidate wins the seat per the certified state result on election day."


def _ledger(tmp_path):
    return ForecastLedger(db_path=str(tmp_path / "rq.db"))


def _question(lg, title="Will the incumbent hold the Ohio Senate seat in 2026?"):
    return lg.create_question(
        title=title,
        resolution_criteria=_CRIT,
        domain="politics",
        outcome_space=OutcomeSpace(type="binary"),
    )


def test_rename_updates_title_preserves_id_and_audits(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)
    old = q.title
    new = "Will Moreno (R) defeat Brown (D) for the Ohio Senate seat in 2026?"
    renamed = lg.rename_question(q.id, new, actor="agent")
    assert renamed.id == q.id  # id is the key; preserved
    assert renamed.title == new
    hist = renamed.metadata.get("title_history")
    assert hist and hist[-1]["old"] == old and hist[-1]["new"] == new and hist[-1]["actor"] == "agent"
    # the rename is durable
    assert lg.get_question(q.id).title == new


def test_rename_rejects_empty(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)
    with pytest.raises(Exception):
        lg.rename_question(q.id, "   ")


def test_rename_rejects_generic_title(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)
    with pytest.raises(Exception):
        lg.rename_question(q.id, "Forecast")  # _scoreability_issues -> "title is too generic"


def test_rename_noop_when_unchanged(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)
    r = lg.rename_question(q.id, q.title)
    assert r.title == q.title
    assert "title_history" not in (r.metadata or {})  # no audit churn for a no-op


def test_add_reference_class_records_sample_size(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)
    rc = lg.add_reference_class(
        question_id=q.id,
        name="US Senate incumbents holding in midterms",
        inclusion_criteria="elected US Senate incumbents seeking re-election in midterm cycles 1980-2024",
        base_rate=0.82,
        sample_size=140,
    )
    assert rc["sample_size"] == 140
    assert lg.get_reference_class(rc["id"])["sample_size"] == 140  # round-trips via dict(row)


def test_add_reference_class_rejects_negative_sample_size(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)
    with pytest.raises(Exception):
        lg.add_reference_class(question_id=q.id, name="X", inclusion_criteria="a sufficiently long inclusion", sample_size=-3)


def test_delete_reference_class_removes_it(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)
    rc = lg.add_reference_class(question_id=q.id, name="Anchor", inclusion_criteria="a sufficiently long inclusion criteria")
    lg.delete_reference_class(rc["id"])
    assert all(r["id"] != rc["id"] for r in lg.list_reference_classes(q.id))
