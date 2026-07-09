"""Orphaned-anchor re-link — the mechanical remediation for a reference class that
EXISTS on a question but is ABSENT from its current snapshot's refs.

Locks: (a) an orphan with a single distinct class name is re-linked; (b) an
orphan under >1 distinct name is SKIPPED (ambiguous, a human picks); (c) a
snapshot already citing an active class is left alone; (d) apply is idempotent
(re-running relinks nothing new); (e) same-name duplicate classes are one
conceptual anchor and are linked together.
"""

from __future__ import annotations

import pytest

from forecasting.ledger import ForecastLedger


def _ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("FORECAST_GATE_DIRECT_WRITES", "off")
    lg = ForecastLedger(db_path=str(tmp_path / "anchors.db"))
    lg.initialize_schema()
    return lg


def _question_with_snapshot(lg, *, refs=None, title="Will X happen by close?"):
    q = lg.create_question(
        title=title,
        resolution_criteria="Resolves yes if X happens by close; otherwise no.",
        impact="medium",
    )
    lg.add_evidence(question_id=q.id, source_or_note="s", claim="c")
    lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.42, rationale="read",
        require_panel=False, reference_class_refs=list(refs or []),
        enforce_resolved_hooks=False,
    )
    return q


def test_orphan_single_name_is_relinkable(tmp_path, monkeypatch):
    lg = _ledger(tmp_path, monkeypatch)
    q = _question_with_snapshot(lg, refs=[])  # snapshot carries NO refs
    rc = lg.add_reference_class(question_id=q.id, name="hist", inclusion_criteria="prior cases", base_rate=0.4)

    dry = lg.relink_orphaned_anchors(question_ids=[q.id], apply=False)
    assert dry["relinkable"] == 1 and dry["ambiguous"] == 0 and dry["applied"] == 0
    # Dry run does NOT mutate the snapshot.
    assert (lg.get_current_snapshot(q.id).reference_class_refs or []) == []

    applied = lg.relink_orphaned_anchors(question_ids=[q.id], apply=True)
    assert applied["applied"] == 1
    assert rc["id"] in (lg.get_current_snapshot(q.id).reference_class_refs or [])


def test_ambiguous_multiple_names_skipped(tmp_path, monkeypatch):
    lg = _ledger(tmp_path, monkeypatch)
    q = _question_with_snapshot(lg, refs=[])
    lg.add_reference_class(question_id=q.id, name="view A", inclusion_criteria="cases A", base_rate=0.3)
    lg.add_reference_class(question_id=q.id, name="view B", inclusion_criteria="cases B", base_rate=0.6)

    res = lg.relink_orphaned_anchors(question_ids=[q.id], apply=True)
    assert res["ambiguous"] == 1 and res["relinkable"] == 0 and res["applied"] == 0
    # Nothing linked — a human must choose which outside view is THE anchor.
    assert (lg.get_current_snapshot(q.id).reference_class_refs or []) == []


def test_same_name_duplicates_are_one_anchor(tmp_path, monkeypatch):
    lg = _ledger(tmp_path, monkeypatch)
    q = _question_with_snapshot(lg, refs=[])
    a = lg.add_reference_class(question_id=q.id, name="swing-state races", inclusion_criteria="c1", base_rate=0.4)
    b = lg.add_reference_class(question_id=q.id, name="swing-state races", inclusion_criteria="c2", base_rate=0.5)

    res = lg.relink_orphaned_anchors(question_ids=[q.id], apply=True)
    assert res["relinkable"] == 1 and res["applied"] == 1
    refs = set(lg.get_current_snapshot(q.id).reference_class_refs or [])
    assert {a["id"], b["id"]} <= refs  # both same-name dupes linked


def test_already_linked_is_left_alone(tmp_path, monkeypatch):
    lg = _ledger(tmp_path, monkeypatch)
    q = _question_with_snapshot(lg, refs=[])
    rc = lg.add_reference_class(question_id=q.id, name="hist", inclusion_criteria="c", base_rate=0.4)
    lg.set_snapshot_reference_class_refs(lg.get_current_snapshot(q.id).forecast_id, [rc["id"]])

    res = lg.relink_orphaned_anchors(question_ids=[q.id], apply=True)
    assert res["already_linked"] == 1 and res["relinkable"] == 0 and res["applied"] == 0


def test_relink_refreshes_stored_saturation(tmp_path, monkeypatch):
    lg = _ledger(tmp_path, monkeypatch)
    q = lg.create_question(
        title="Will X happen by close?",
        resolution_criteria="Resolves yes if X happens by close; otherwise no.",
        impact="high",
    )
    lg.add_evidence(question_id=q.id, source_or_note="s", claim="c")
    rc = lg.add_reference_class(question_id=q.id, name="hist", inclusion_criteria="prior cases", base_rate=0.4)
    snap = lg.create_snapshot(
        question_id=q.id,
        probability_or_distribution=0.42,
        rationale="read",
        require_panel=False,
        reference_class_refs=[],
        enforce_resolved_hooks=False,
    )
    before = (snap.metadata or {}).get("saturation") or {}
    assert "anchor_refs_attached" in before.get("warnings", [])

    lg.set_snapshot_reference_class_refs(snap.forecast_id, [rc["id"]])

    after = (lg.get_current_snapshot(q.id).metadata or {}).get("saturation") or {}
    failed = {v["rule_id"] for v in after.get("verdicts", []) if not v.get("passed", True)}
    assert "anchor_refs_attached" not in failed


def test_no_reference_class_is_not_a_candidate(tmp_path, monkeypatch):
    lg = _ledger(tmp_path, monkeypatch)
    q = _question_with_snapshot(lg, refs=[])  # no reference class at all
    res = lg.relink_orphaned_anchors(question_ids=[q.id], apply=True)
    assert res["scanned_with_reference_class"] == 0 and res["relinkable"] == 0


def test_apply_is_idempotent(tmp_path, monkeypatch):
    lg = _ledger(tmp_path, monkeypatch)
    q = _question_with_snapshot(lg, refs=[])
    lg.add_reference_class(question_id=q.id, name="hist", inclusion_criteria="c", base_rate=0.4)

    first = lg.relink_orphaned_anchors(question_ids=[q.id], apply=True)
    assert first["applied"] == 1
    second = lg.relink_orphaned_anchors(question_ids=[q.id], apply=True)
    assert second["applied"] == 0 and second["already_linked"] == 1


def test_setter_rejects_unknown_snapshot(tmp_path, monkeypatch):
    from forecasting.models import LedgerNotFoundError

    lg = _ledger(tmp_path, monkeypatch)
    with pytest.raises(LedgerNotFoundError):
        lg.set_snapshot_reference_class_refs("fs_does_not_exist", ["rc_x"])
