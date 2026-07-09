"""G1 (distribution-tail base rates — the Binface gate) + G2 (per-candidate
interval coherence) + G6 (share/quantile coherence) + the _sharpness pp-scale fix.

The anchor of this file is THE CLACTON CANARY: a fixture reproducing the live
snapshot fs_526baa283165 (Count Binface at 16.5pp, named, with no cited base
rate) that every gate passed at 100/100. Under the standard profile the G1 rule
must now WARN, naming Binface + the residual-bucket remediation; under strict it
must BLOCK. This is the pinned regression for the pass-when-it-shouldn't class.
"""

from __future__ import annotations

import pytest

from forecasting import ForecastLedger
from forecasting.hooks import (
    HookContext,
    SaturationBlocked,
    Severity,
    adherence_scorecard,
    assess_candidate_intervals,
    assess_distribution,
    candidate_shares,
    lint_forecast,
    run_hooks,
)
from forecasting.hooks.builtins import _RULE_BY_ID
from forecasting.models import OutcomeSpace
from forecasting.tail_audit import (
    DEFAULT_NAMED_ANCHOR_SHARE,
    OutcomePath,
    audit_named_anchors,
    outcome_paths_from_inputs,
)

# The EXACT live Clacton payload (percentage points), from the autopsy.
CLACTON_PP = {
    "Count Binface": 16.5,
    "Laurence Fox": 4.0,
    "Nigel Farage": 67.0,
    "Other official candidates": 12.5,
}
# Well-formed per-candidate intervals (the snapshot carried these for Binface — they
# were coherent; G2 passing while G1 blocks proves the two failures are independent).
CLACTON_INTERVALS = {
    "Nigel Farage": {"p05": 60.0, "median": 67.0, "p95": 74.0},
    "Count Binface": {"p05": 11.5, "median": 16.5, "p95": 22.5},
}


def _ctx(**over) -> HookContext:
    base = dict(question_id="q", forecast_origin="live", event="update")
    base.update(over)
    return HookContext(**base)


# ══ Part A · G1 anchor audit logic (tail_audit) ══════════════════════════════
class TestAnchorAuditLogic:
    def test_clacton_named_tails_are_unanchored(self):
        shares = candidate_shares(CLACTON_PP)
        offenders, mass = audit_named_anchors(outcome_paths_from_inputs(shares, None))
        # Both named outcomes above 10% with no base rate are flagged; the residual
        # "Other official candidates" is exempt; Fox (4%) is below threshold.
        assert "Count Binface" in offenders
        assert "Nigel Farage" in offenders
        assert "Laurence Fox" not in offenders
        assert "Other official candidates" not in offenders
        assert mass == pytest.approx(0.835, abs=1e-6)

    def test_base_rate_plus_source_anchors_the_outcome(self):
        shares = candidate_shares(CLACTON_PP)
        paths = {
            "Nigel Farage": {"base_rate": 0.60, "base_rate_source": "PollCheck 60.2% model"},
            "Count Binface": {"base_rate": 0.02, "base_rate_source": "Binface 2024 GE Richmond 0.9%"},
        }
        offenders, mass = audit_named_anchors(outcome_paths_from_inputs(shares, paths))
        assert offenders == ()
        assert mass == pytest.approx(0.0)

    def test_base_rate_without_source_is_not_anchored(self):
        # A number with no provenance is not an outside view.
        row = OutcomePath("X", 0.5, base_rate=0.3, base_rate_source="")
        assert row.is_anchored is False
        offenders, _ = audit_named_anchors([row])
        assert offenders == ("X",)

    def test_other_official_candidates_is_residual(self):
        # The exact prefix-match hole that let unanchored mass ride a named-looking
        # residual: "Other official candidates" now matches.
        assert OutcomePath("Other official candidates", 0.30).is_residual is True
        assert OutcomePath("Other parties", 0.30).is_residual is True
        offenders, mass = audit_named_anchors([OutcomePath("Other official candidates", 0.30)])
        assert offenders == () and mass == 0.0

    def test_threshold_is_honored(self):
        rows = [OutcomePath("A", 0.08), OutcomePath("B", 0.92)]
        # Default 10% -> only B flagged (A is 8%, below the floor).
        off_default, _ = audit_named_anchors(rows)
        assert off_default == ("B",)
        # A looser 50% threshold flags neither the 8% nor... only B (92%) exceeds it.
        off_loose, _ = audit_named_anchors(rows, threshold=0.5)
        assert off_loose == ("B",)
        assert DEFAULT_NAMED_ANCHOR_SHARE == 0.10


# ══ Part B · shares + interval coherence + G6 (distribution) ═════════════════
class TestShareExtraction:
    def test_pp_payload_normalizes_to_fraction(self):
        assert candidate_shares(CLACTON_PP)["Nigel Farage"] == pytest.approx(0.67)

    def test_fractional_payload_unchanged(self):
        assert candidate_shares({"A": 0.7, "B": 0.3}) == {"A": 0.7, "B": 0.3}

    def test_not_a_share_pmf(self):
        assert candidate_shares({"mean": 5, "q05": 2, "q95": 9}) is None  # all stat keys
        assert candidate_shares({"A": 0.7}) is None                        # only one named
        assert candidate_shares(0.6) is None                               # scalar


class TestCandidateIntervalCoherence:
    def test_coherent_clacton_intervals_pass(self):
        coherent, coverage, issues = assess_candidate_intervals(CLACTON_PP, CLACTON_INTERVALS)
        assert coherent is True and issues == []
        # 2 of the 3 named non-residual candidates carry an interval.
        assert coverage == pytest.approx(2 / 3)

    def test_absence_is_honest(self):
        coherent, coverage, issues = assess_candidate_intervals(CLACTON_PP, None)
        assert coherent is True and coverage == 0.0 and issues == []

    def test_inverted_band_is_incoherent(self):
        bad = {"Nigel Farage": {"p05": 74.0, "median": 67.0, "p95": 60.0}}
        coherent, _, issues = assess_candidate_intervals(CLACTON_PP, bad)
        assert coherent is False and any("p05" in i and "p95" in i for i in issues)

    def test_median_far_from_share_is_incoherent(self):
        # Farage share 67pp but median claims 20pp -> a band contradicting its point.
        bad = {"Nigel Farage": {"p05": 15.0, "median": 20.0, "p95": 25.0}}
        coherent, _, issues = assess_candidate_intervals(CLACTON_PP, bad)
        assert coherent is False and any("off the committed share" in i for i in issues)

    def test_non_share_payload_returns_none_coverage(self):
        coherent, coverage, issues = assess_candidate_intervals({"mean": 5, "q95": 9}, None)
        assert coherent is True and coverage is None


class TestG6Coherence:
    def _share_q_assessment(self, payload):
        return assess_distribution(payload, outcome_type="distribution", bounds=[0, 100])

    def test_share_sum_within_two_percent_is_coherent(self):
        assert self._share_q_assessment({"A": 60, "B": 40}).coherent is True   # 100
        assert self._share_q_assessment({"A": 49, "B": 49}).coherent is True   # 98 (edge)
        assert self._share_q_assessment({"A": 51, "B": 51}).coherent is True   # 102 (edge)

    def test_share_sum_off_by_more_blocks(self):
        a = self._share_q_assessment({"A": 60, "B": 48})  # 108
        assert a.coherent is False and a.well_formed is False
        assert any("sum to 108" in i for i in a.issues)

    def test_negative_share_blocks(self):
        a = self._share_q_assessment({"A": 104, "B": -4})  # sums 100 but B negative
        assert a.coherent is False
        assert any("negative" in i for i in a.issues)

    def test_non_monotone_quantiles_block(self):
        a = assess_distribution(
            {"mean": 5, "q05": 2, "q25": 8, "q75": 6, "q95": 9}, outcome_type="distribution"
        )
        assert a.ordered is False and a.well_formed is False
        assert any("not monotone" in i for i in a.issues)

    def test_well_formed_continuous_unaffected(self):
        a = assess_distribution(
            {"mean": 5, "q05": 2, "q25": 4, "q75": 6, "q95": 8}, outcome_type="distribution", bounds=[0, 10]
        )
        assert a.well_formed is True


# ══ Part C · the _sharpness pp-scale fix ═════════════════════════════════════
class TestSharpnessScale:
    def _lg(self, tmp_path):
        lg = ForecastLedger(db_path=str(tmp_path / "s.db"))
        lg.initialize_schema()
        return lg

    def test_clacton_pp_payload_pinned_to_067(self, tmp_path):
        # The bug: max({...67.0...}) returned 67.0, so confidence_committed (floor
        # 0.05) was vacuously satisfied for every share board. Now normalized to 0.67.
        assert self._lg(tmp_path)._sharpness(CLACTON_PP) == pytest.approx(0.67)

    def test_fractional_pmf_unchanged(self, tmp_path):
        assert self._lg(tmp_path)._sharpness({"A": 0.7, "B": 0.3}) == pytest.approx(0.7)

    def test_binary_unchanged(self, tmp_path):
        assert self._lg(tmp_path)._sharpness(0.6) == pytest.approx(0.2)

    def test_continuous_stats_dict_unchanged(self, tmp_path):
        # Not a share PMF (stat keys) -> legacy max-of-numeric behavior preserved.
        assert self._lg(tmp_path)._sharpness({"mean": 5, "q05": 2, "q95": 9}) == 9.0


# ══ Part D · rule applies matrix + WARN/ERROR profile split ═══════════════════
class TestAppliesMatrix:
    def _applies(self, rule_id, **over):
        return _RULE_BY_ID[rule_id].applies(_ctx(**over))

    def test_g1_applies_to_categorical_and_candidate_share_only(self):
        assert self._applies("require_tail_base_rates", is_categorical=True) is True
        assert self._applies("require_tail_base_rates", is_candidate_share=True) is True
        # binary: neither flag -> does not apply
        assert self._applies("require_tail_base_rates") is False
        # plain-continuous distribution (a band, not a share PMF) -> does not apply
        assert self._applies("require_tail_base_rates", is_distribution=True) is False
        # thesis/factor aggregate is never modeled-audited
        assert self._applies("require_tail_base_rates", is_candidate_share=True, is_thesis_or_factor=True) is False
        # non-live -> off
        assert _RULE_BY_ID["require_tail_base_rates"].applies(
            _ctx(forecast_origin="exploratory", is_candidate_share=True)
        ) is False

    def test_g2_applies_only_when_share_and_intervals_present(self):
        assert self._applies("candidate_intervals_coherent", is_candidate_share=True, candidate_intervals_present=True) is True
        assert self._applies("candidate_intervals_coherent", is_candidate_share=True, candidate_intervals_present=False) is False
        assert self._applies("candidate_intervals_coherent", is_categorical=True, candidate_intervals_present=True) is False

    def test_outcome_paths_and_tails_justified_now_cover_shares(self):
        # The applies_to gotcha the lessons arc documented: extend from is_categorical
        # to is_categorical OR is_candidate_share (regression-pin).
        for rid in ("require_outcome_paths", "tails_justified"):
            assert self._applies(rid, is_candidate_share=True) is True
            assert self._applies(rid, is_categorical=True) is True
            assert self._applies(rid) is False  # binary


class TestProfileSplit:
    def _clacton_ctx(self, **over):
        base = dict(
            is_candidate_share=True,
            share_named_unanchored=("Count Binface", "Nigel Farage"),
            share_named_unanchored_mass=0.835,
        )
        base.update(over)
        return _ctx(**base)

    def _g1_only(self, ctx, sev):
        # Evaluate ONLY the G1 rule so report.passed reflects G1 alone (a minimal
        # ctx trips many unrelated ERROR defaults otherwise).
        return run_hooks(ctx, {"require_tail_base_rates": sev}, rules=(_RULE_BY_ID["require_tail_base_rates"],))

    def test_standard_warn_names_binface_and_residual(self):
        report = self._g1_only(self._clacton_ctx(), Severity.WARN)
        v = next(x for x in report.verdicts if x.rule_id == "require_tail_base_rates")
        assert v.passed is False and v.severity is Severity.WARN
        assert report.passed is True  # a WARN never blocks
        assert "Count Binface" in v.message
        assert "residual" in v.message.lower()
        assert "Precision you cannot cite is not precision" in v.message

    def test_strict_error_blocks(self):
        report = self._g1_only(self._clacton_ctx(), Severity.ERROR)
        assert report.passed is False
        assert "require_tail_base_rates" in {v.rule_id for v in report.blocking_failures()}

    def test_anchored_context_passes_both_profiles(self):
        anchored = self._clacton_ctx(share_named_unanchored=(), share_named_unanchored_mass=0.0)
        for sev in (Severity.WARN, Severity.ERROR):
            report = self._g1_only(anchored, sev)
            v = next(x for x in report.verdicts if x.rule_id == "require_tail_base_rates")
            assert v.passed is True


# ══ Part E · THE CLACTON CANARY (integration through the commit gate) ═════════
def _clacton_question(lg, *, profile=None):
    meta = {"forecast_hooks": {"profile": profile}} if profile else None
    q = lg.create_question(
        title="What vote shares will candidates receive in the 2026 Clacton by-election?",
        resolution_criteria="Resolves to the certified percentage vote share for each candidate.",
        outcome_space=OutcomeSpace(type="distribution", choices=list(CLACTON_PP), bounds=[0, 100], units="%"),
        impact="high",
        metadata=meta,
    )
    # Provision so every OTHER standard gate passes: evidence floor + a linked
    # reference class (require_outside_view_anchor is ERROR for high-impact).
    lg.add_evidence(question_id=q.id, source_or_note="BBC ballot structure", claim="four candidates on the ballot")
    rc = lg.add_reference_class(
        question_id=q.id, name="incumbent-leader share",
        inclusion_criteria="prior Reform/UKIP by-election winner shares", base_rate=0.60,
    )
    return q, rc["id"] if isinstance(rc, dict) else rc


def _commit_clacton(lg, q, rc_id, *, outcome_paths=None, intervals=CLACTON_INTERVALS):
    return lg.create_snapshot(
        question_id=q.id,
        probability_or_distribution=dict(CLACTON_PP),
        rationale="Farage is the strong favorite; the residual field is small.",
        method="conditioned monte carlo",
        reference_class_refs=[rc_id],
        outcome_paths=outcome_paths,
        metadata={"candidate_share_intervals_pp": intervals} if intervals else None,
        require_panel=False, require_components=False, require_structured_reasoning=False,
        enforce_resolved_hooks=True,
    )


def test_canary_standard_commits_with_g1_warn_naming_binface(tmp_path):
    lg = ForecastLedger(db_path=str(tmp_path / "clacton.db"))
    lg.initialize_schema()
    q, rc = _clacton_question(lg)  # standard profile
    snap = _commit_clacton(lg, q, rc)
    assert snap is not None  # standard: G1 is WARN, so the commit is NOT blocked
    sat = (snap.metadata or {}).get("saturation") or {}
    assert "require_tail_base_rates" in sat.get("warnings", [])
    assert "require_tail_base_rates" not in sat.get("blocking", [])
    verdict = next(v for v in sat["verdicts"] if v["rule_id"] == "require_tail_base_rates")
    assert "Count Binface" in verdict["message"]
    assert "residual" in verdict["message"].lower()
    # G6 stamped the tail audit for the SHARE distribution (the scope hole is closed).
    assert "tail_audit" in (snap.metadata or {})


def test_canary_strict_blocks_on_g1_naming_binface(tmp_path):
    lg = ForecastLedger(db_path=str(tmp_path / "clacton_strict.db"))
    lg.initialize_schema()
    q, rc = _clacton_question(lg, profile="strict")
    with pytest.raises(SaturationBlocked) as ei:
        _commit_clacton(lg, q, rc)
    blocking = {v.rule_id for v in ei.value.report.blocking_failures()}
    assert "require_tail_base_rates" in blocking
    v = next(v for v in ei.value.report.blocking_failures() if v.rule_id == "require_tail_base_rates")
    assert "Count Binface" in v.message


def test_canary_green_when_named_tails_anchored(tmp_path):
    lg = ForecastLedger(db_path=str(tmp_path / "clacton_green.db"))
    lg.initialize_schema()
    q, rc = _clacton_question(lg)
    # Anchor BOTH named >10% outcomes with a base rate + source -> G1 clears.
    anchored = {
        "Nigel Farage": {"base_rate": 0.60, "base_rate_source": "PollCheck model + Davis 2008"},
        "Count Binface": {"base_rate": 0.02, "base_rate_source": "Binface 2024 GE Richmond 0.9%"},
    }
    snap = _commit_clacton(lg, q, rc, outcome_paths=anchored)
    assert (snap.metadata or {}).get("outcome_paths") == anchored
    sat = (snap.metadata or {}).get("saturation") or {}
    assert "require_tail_base_rates" not in sat.get("warnings", [])
    assert "require_tail_base_rates" not in sat.get("blocking", [])
    relint = lint_forecast(lg, q.id)
    assert relint is not None
    assert "require_tail_base_rates" not in {v.rule_id for v in relint.verdicts if not v.passed}


def test_canary_g2_coherence_blocks_garbage_intervals(tmp_path):
    # Independent from G1: a malformed interval blocks even in the standard profile
    # (candidate_intervals_coherent is ERROR immediately). Anchor G1 so the block is
    # unambiguously the coherence gate.
    lg = ForecastLedger(db_path=str(tmp_path / "clacton_g2.db"))
    lg.initialize_schema()
    q, rc = _clacton_question(lg)
    anchored = {
        "Nigel Farage": {"base_rate": 0.60, "base_rate_source": "model"},
        "Count Binface": {"base_rate": 0.02, "base_rate_source": "prior results"},
    }
    garbage = {"Nigel Farage": {"p05": 80.0, "median": 67.0, "p95": 60.0}}  # inverted band
    with pytest.raises(SaturationBlocked) as ei:
        _commit_clacton(lg, q, rc, outcome_paths=anchored, intervals=garbage)
    assert "candidate_intervals_coherent" in {v.rule_id for v in ei.value.report.blocking_failures()}


def test_cli_outcome_path_json_preserves_base_rate_anchor():
    from forecasting.cli.core import _parse_outcome_paths

    parsed = _parse_outcome_paths([
        'Count Binface={"base_rate":0.02,"base_rate_source":"Binface 2024 result"}',
        "Nigel Farage=incumbent Reform path",
    ])
    assert parsed == {
        "Count Binface": {"base_rate": 0.02, "base_rate_source": "Binface 2024 result"},
        "Nigel Farage": "incumbent Reform path",
    }


# ══ Part F · doctor adherence scorecard ══════════════════════════════════════
def test_adherence_scorecard_tallies_stored_verdicts(tmp_path):
    lg = ForecastLedger(db_path=str(tmp_path / "adh.db"))
    lg.initialize_schema()
    q, rc = _clacton_question(lg)  # standard
    _commit_clacton(lg, q, rc)     # commits with a stored saturation report (G1 WARN)

    card = adherence_scorecard(lg)
    assert card["questions_scored"] >= 1
    rules = card["rules"]
    assert "require_tail_base_rates" in rules
    g1 = rules["require_tail_base_rates"]
    # It was checked and failed as a WARN (not a block) on the Clacton board.
    assert g1["checked"] >= 1
    assert g1["failed_warn"] >= 1
    assert g1["failed_block"] == 0
    assert 0.0 <= g1["pass_rate"] <= 1.0
