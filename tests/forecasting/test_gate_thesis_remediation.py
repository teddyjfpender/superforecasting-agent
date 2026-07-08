"""Thesis-remediation gate family — the four gates that make three silent thesis
defects impossible going forward:

  * anchor_refs_attached — an RC exists on the question but is orphaned off the
    current snapshot (a MECHANICAL re-link, distinct from require_outside_view_anchor).
  * event_band_earned — a thesis with members but no event (name set-event), or an
    event band whose member-interval coverage is below the earned floor.
  * health_not_probability — a mean-index health value presented with no event band
    and no index label (the index-as-probability lie).
  * thesis_correlation_transparency — a low n_eff / member ratio (a co-directional
    cluster) — an honest label, never a block.
"""

from __future__ import annotations

from forecasting.hooks import resolve_severities, run_hooks
from forecasting.hooks.profiles import profile_severities
from forecasting.hooks.spec import HookContext, Severity


class _QProfile:
    def __init__(self, profile):
        self.metadata = {"forecast_hooks": {"profile": profile}}
        self.impact = "high"


def _verdict(ctx, rule_id, profile="standard"):
    report = run_hooks(ctx, resolve_severities(_QProfile(profile), forecast_origin="live"))
    return next((v for v in report.verdicts if v.rule_id == rule_id), None)


# ── anchor_refs_attached ──────────────────────────────────────────────────────
def _anchor_ctx(**kw):
    base = dict(question_id="fq", event="update", forecast_origin="live",
                is_thesis_or_factor=False, reference_class_count=1, snapshot_reference_class_count=0)
    base.update(kw)
    return HookContext(**base)


def test_anchor_orphan_fires_warn():
    v = _verdict(_anchor_ctx(), "anchor_refs_attached")
    assert v is not None and v.passed is False and v.severity.value == "warn"
    assert "ORPHANED" in v.message and "relink" in v.message


def test_anchor_linked_passes():
    v = _verdict(_anchor_ctx(snapshot_reference_class_count=1), "anchor_refs_attached")
    assert v is not None and v.passed is True


def test_anchor_no_class_does_not_apply():
    v = _verdict(_anchor_ctx(reference_class_count=0), "anchor_refs_attached")
    assert v is None  # no class at all -> require_outside_view_anchor's job, not this one


def test_anchor_does_not_apply_to_thesis():
    v = _verdict(_anchor_ctx(is_thesis_or_factor=True), "anchor_refs_attached")
    assert v is None


def test_anchor_strict_blocks():
    assert profile_severities("strict")["anchor_refs_attached"] is Severity.ERROR


# ── event_band_earned ─────────────────────────────────────────────────────────
def _thesis_ctx(**kw):
    base = dict(question_id="fq", event="lint", forecast_origin="live",
                is_thesis_or_factor=True, thesis_member_count=17, thesis_has_event=True,
                thesis_event_interval_coverage=1.0)
    base.update(kw)
    return HookContext(**base)


def test_event_missing_fires_and_names_set_event():
    v = _verdict(_thesis_ctx(thesis_has_event=False, thesis_event_interval_coverage=None), "event_band_earned")
    assert v is not None and v.passed is False and v.severity.value == "warn"
    assert "set-event" in v.message and v.facts.get("mode") == "thesis_event_missing"


def test_event_band_unearned_fires():
    v = _verdict(_thesis_ctx(thesis_has_event=True, thesis_event_interval_coverage=0.0), "event_band_earned")
    assert v is not None and v.passed is False
    assert "unearned" in v.message and v.facts.get("mode") == "event_band_unearned"


def test_event_band_earned_passes_above_floor():
    v = _verdict(_thesis_ctx(thesis_event_interval_coverage=0.31), "event_band_earned")
    assert v is not None and v.passed is True


def test_event_band_no_members_does_not_apply():
    v = _verdict(_thesis_ctx(thesis_member_count=0), "event_band_earned")
    assert v is None


def test_event_band_strict_blocks():
    assert profile_severities("strict")["event_band_earned"] is Severity.ERROR


# ── health_not_probability ────────────────────────────────────────────────────
def test_health_unlabeled_no_event_fires():
    v = _verdict(_thesis_ctx(thesis_health_present=True, thesis_has_event=False,
                             thesis_health_index_labeled=False, thesis_event_interval_coverage=None),
                 "health_not_probability")
    assert v is not None and v.passed is False and "index" in v.message


def test_health_labeled_passes():
    v = _verdict(_thesis_ctx(thesis_health_present=True, thesis_has_event=False,
                             thesis_health_index_labeled=True, thesis_event_interval_coverage=None),
                 "health_not_probability")
    assert v is not None and v.passed is True


def test_health_with_event_passes():
    v = _verdict(_thesis_ctx(thesis_health_present=True, thesis_has_event=True,
                             thesis_health_index_labeled=False), "health_not_probability")
    assert v is not None and v.passed is True


def test_health_absent_does_not_apply():
    v = _verdict(_thesis_ctx(thesis_health_present=False), "health_not_probability")
    assert v is None


# ── thesis_correlation_transparency ───────────────────────────────────────────
def test_low_neff_ratio_fires():
    v = _verdict(_thesis_ctx(thesis_n_eff=2.25, thesis_n_eff_ratio=2.25 / 17, thesis_member_count=17),
                 "thesis_correlation_transparency")
    assert v is not None and v.passed is False and "CO-DIRECTIONAL" in v.message


def test_high_neff_ratio_passes():
    v = _verdict(_thesis_ctx(thesis_n_eff=9.0, thesis_n_eff_ratio=0.9, thesis_member_count=10),
                 "thesis_correlation_transparency")
    assert v is not None and v.passed is True


def test_correlation_never_blocks_even_in_strict():
    assert profile_severities("strict")["thesis_correlation_transparency"] is Severity.WARN


def test_correlation_no_ratio_does_not_apply():
    v = _verdict(_thesis_ctx(thesis_n_eff_ratio=None), "thesis_correlation_transparency")
    assert v is None


# ── end-to-end ledger wiring + payload conformance (rule 6's label) ───────────
def _binary_member(lg, title, p):
    from forecasting.models import OutcomeSpace

    q = lg.create_question(title=title, resolution_criteria="Resolves yes if it happens; otherwise no.",
                           impact="high", outcome_space=OutcomeSpace(type="binary"))
    lg.add_evidence(question_id=q.id, source_or_note="s", claim="c")
    lg.create_snapshot(question_id=q.id, probability_or_distribution=p, rationale="r",
                       require_panel=False, enforce_resolved_hooks=False)
    return q


def test_thesis_headline_kind_label_and_gate_wiring(tmp_path, monkeypatch):
    monkeypatch.setenv("FORECAST_GATE_DIRECT_WRITES", "off")
    from forecasting.hooks import lint_forecast
    from forecasting.ledger import ForecastLedger
    from forecasting.models import OutcomeSpace

    lg = ForecastLedger(db_path=str(tmp_path / "e2e.db"))
    lg.initialize_schema()
    thesis = lg.create_question(title="Joint threshold thesis tracker",
                                resolution_criteria="Count of member forecasts resolving yes at close.",
                                outcome_space=OutcomeSpace(type="thesis"))
    for i in range(5):
        m = _binary_member(lg, f"Will condition {i} hold?", 0.6 + 0.02 * i)
        lg.add_thesis_member(thesis.id, m.id, weight=2.0)

    # No event yet -> aggregate stamps the INDEX label; health_not_probability passes
    # (labeled), event_band_earned FIRES (missing event).
    lg.aggregate_thesis(thesis.id, rho=0.4)
    snap = lg.get_current_snapshot(thesis.id)
    assert (snap.metadata or {}).get("thesis_headline_kind") == "index"
    fired = {v.rule_id: v.passed for v in lint_forecast(lg, thesis.id, event="lint").verdicts}
    assert fired["health_not_probability"] is True          # labeled index
    assert fired["event_band_earned"] is False              # no event configured

    # Configure the event + re-aggregate -> the label flips + a real P headline.
    lg.set_thesis_event(thesis.id, kind="count_threshold", threshold=3)
    lg.aggregate_thesis(thesis.id, rho=0.4)
    snap2 = lg.get_current_snapshot(thesis.id)
    assert (snap2.metadata or {}).get("thesis_headline_kind") == "event_probability"
    assert "event_probability" in snap2.probability_or_distribution
