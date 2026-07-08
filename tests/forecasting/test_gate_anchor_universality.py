"""G3 · ANCHOR UNIVERSALITY — the outside-view anchor extends beyond high-impact.

Two tiers, designed around the has_prior brick:
  * require_outside_view_anchor now ALSO fires on the FIRST live commit of ANY
    question (not just high-impact) at ERROR — the cheapest, most valuable moment,
    with no re-forecast flow to brick.
  * outside_view_refresh (WARN) nags a routine (non-high-impact) re-forecast of a
    question that has never carried a reference class — visibility, not a block.

The applies matrix + the first-vs-reforecast split are pinned here (pure engine so
has_prior is controlled exactly), plus a behavioral first-commit block through the
ledger. The stale-rerun regression that scoped this rule last time stays green via
test_outside_view_anchor.py (the re-commit tier passes)."""

from __future__ import annotations

from forecasting.hooks import resolve_severities, run_hooks
from forecasting.hooks.spec import HookContext


def _ctx(**kw) -> HookContext:
    base = dict(question_id="fq", event="update", forecast_origin="live", is_thesis_or_factor=False)
    base.update(kw)
    return HookContext(**base)


def _verdict(ctx, rule_id):
    report = run_hooks(ctx, resolve_severities(None, forecast_origin="live"))
    return next((v for v in report.verdicts if v.rule_id == rule_id), None)


# ── first-commit tier (ERROR standard, any impact) ────────────────────────────
def test_first_commit_any_impact_requires_anchor():
    for impact in ("low", "medium", "high", None):
        v = _verdict(_ctx(impact=impact, has_prior=False, linked_reference_class_count=0), "require_outside_view_anchor")
        assert v is not None and v.passed is False and v.severity.value == "error", impact


def test_first_commit_with_linked_anchor_passes():
    v = _verdict(_ctx(impact="low", has_prior=False, linked_reference_class_count=1), "require_outside_view_anchor")
    assert v is not None and v.passed is True


# ── the has_prior split: re-commits are NOT hard-blocked ──────────────────────
def test_low_impact_recommit_without_anchor_does_not_block():
    v = _verdict(_ctx(impact="low", has_prior=True, linked_reference_class_count=0, reference_class_count=0),
                 "require_outside_view_anchor")
    assert v is not None and v.passed is True  # re-commit self-passes the ERROR tier


def test_high_impact_recommit_still_blocks_on_anchor():
    v = _verdict(_ctx(impact="high", has_prior=True, linked_reference_class_count=0), "require_outside_view_anchor")
    assert v is not None and v.passed is False and v.severity.value == "error"


# ── refresh tier (WARN) applies matrix ────────────────────────────────────────
def test_refresh_warns_on_anchorless_recommit():
    v = _verdict(_ctx(impact="low", has_prior=True, reference_class_count=0), "outside_view_refresh")
    assert v is not None and v.passed is False and v.severity.value == "warn"


def test_refresh_passes_when_question_has_any_reference_class():
    # QUESTION-level check (not snapshot-linked) so a routine re-commit need not re-link.
    v = _verdict(_ctx(impact="low", has_prior=True, reference_class_count=1, linked_reference_class_count=0),
                 "outside_view_refresh")
    assert v is not None and v.passed is True


def test_refresh_does_not_apply_to_first_commit():
    v = _verdict(_ctx(impact="low", has_prior=False, reference_class_count=0), "outside_view_refresh")
    assert v is None  # applies requires has_prior


def test_refresh_does_not_apply_to_high_impact():
    # high-impact is ERROR-gated by require_outside_view_anchor; refresh scopes OUT to
    # avoid a double verdict.
    v = _verdict(_ctx(impact="high", has_prior=True, reference_class_count=0), "outside_view_refresh")
    assert v is None


def test_neither_tier_applies_to_thesis():
    ctx = _ctx(impact="high", has_prior=False, is_thesis_or_factor=True, linked_reference_class_count=0)
    assert _verdict(ctx, "require_outside_view_anchor") is None
    assert _verdict(ctx, "outside_view_refresh") is None


# ── behavioral: a first agent commit blocks without a linked anchor ────────────
def test_ledger_first_commit_blocks_without_anchor(tmp_path, monkeypatch):
    monkeypatch.setenv("FORECAST_GATE_DIRECT_WRITES", "off")
    from forecasting.hooks import SaturationBlocked
    from forecasting.ledger import ForecastLedger
    import pytest

    lg = ForecastLedger(db_path=str(tmp_path / "g3.db"))
    lg.initialize_schema()
    q = lg.create_question(title="Will the indicator cross by close?",
                           resolution_criteria="Resolves yes if it crosses by close; otherwise no.", impact="low")
    lg.add_evidence(question_id=q.id, source_or_note="s", claim="c")
    with pytest.raises(SaturationBlocked) as ei:
        lg.create_snapshot(question_id=q.id, probability_or_distribution=0.42, rationale="p",
                           method="m", require_panel=False, enforce_resolved_hooks=True)
    assert ei.value.report.blocking_failures()[0].rule_id == "require_outside_view_anchor"

    rc = lg.add_reference_class(question_id=q.id, name="hist", inclusion_criteria="prior cases", base_rate=0.4)
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution=0.42, rationale="p",
                              method="m", require_panel=False, reference_class_refs=[rc["id"]],
                              enforce_resolved_hooks=True)
    assert snap is not None
