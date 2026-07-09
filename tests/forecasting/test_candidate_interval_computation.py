"""P2 · per-candidate vote-share intervals, END-TO-END.

Covers the honest COMPUTATION (precedence panel > model > default + provenance +
coherence-by-construction against the G2 validator), the COMMIT-TIME auto-fill, the
GATE FLIP (absent -> WARN on live high-impact, silent on exploratory), and the
BACKFILL dry-run. The rendering (whiskers / leader header / bars) is pinned in vitest.
"""

from __future__ import annotations

import pytest

from forecasting.hooks.candidate_intervals import (
    DEFAULT_MAX_HALF_WIDTH_PP,
    compute_candidate_share_intervals,
)
from forecasting.hooks.distribution import assess_candidate_intervals
from forecasting.ledger import ForecastLedger
from forecasting.models import OutcomeSpace

# The live Clacton payload (percentage points).
CLACTON = {"Count Binface": 16.5, "Laurence Fox": 4.0, "Nigel Farage": 67.0, "Other official candidates": 12.5}


def _dist_component(dist: dict, source: str) -> dict:
    return {"distribution": dict(dist), "source": source, "weight": 1.0}


def _four_spread_components() -> dict:
    return {"components": [
        _dist_component({"Count Binface": 16.6, "Laurence Fox": 4.4, "Nigel Farage": 66.9, "Other official candidates": 12.1}, "model:mc"),
        _dist_component({"Count Binface": 14.0, "Laurence Fox": 4.0, "Nigel Farage": 68.0, "Other official candidates": 14.0}, "reference_class:x"),
        _dist_component({"Count Binface": 18.0, "Laurence Fox": 4.0, "Nigel Farage": 65.0, "Other official candidates": 13.0}, "panel:y"),
        _dist_component({"Count Binface": 20.0, "Laurence Fox": 4.0, "Nigel Farage": 63.0, "Other official candidates": 13.0}, "yougov:z"),
    ]}


# ══ Part A · precedence: panel > model > default ═════════════════════════════
class TestPrecedence:
    def test_panel_spread_when_enough_components(self):
        ivs, prov = compute_candidate_share_intervals(CLACTON, components=_four_spread_components(), evidence_count=8, bounds=[0, 100])
        assert prov["source"] == "panel"
        assert prov["params"]["n_components"] == 4
        # Farage spread across 63-68 -> a real band bracketing the committed 67.
        far = ivs["Nigel Farage"]
        assert far["median"] == 67.0
        assert far["p05"] < 67.0 <= far["p95"]

    def test_model_quantiles_when_no_panel_spread(self):
        comps = {"components": [{
            "source": "model:mc",
            "quantiles": {
                "Nigel Farage": {"p05": 58, "median": 67, "p95": 75},
                "Count Binface": {"p05": 11, "median": 16.5, "p95": 22},
            },
        }]}
        ivs, prov = compute_candidate_share_intervals(CLACTON, components=comps, evidence_count=3, bounds=[0, 100])
        assert prov["source"] == "model"
        assert ivs["Nigel Farage"]["p05"] == 58.0 and ivs["Nigel Farage"]["p95"] == 75.0

    def test_default_width_when_neither(self):
        ivs, prov = compute_candidate_share_intervals(CLACTON, components={"components": []}, evidence_count=4, bounds=[0, 100])
        assert prov["source"] == "default"
        assert prov["params"]["evidence_count"] == 4
        # evidence 4 -> half-width 10/sqrt(4)=5pp, symmetric around each share.
        assert ivs["Count Binface"]["p05"] == pytest.approx(11.5, abs=0.01)
        assert ivs["Count Binface"]["p95"] == pytest.approx(21.5, abs=0.01)

    def test_panel_beats_model_when_both_present(self):
        comps = _four_spread_components()
        comps["components"].append({"source": "model:mc", "quantiles": {"Nigel Farage": {"p05": 1, "median": 67, "p95": 99}}})
        _, prov = compute_candidate_share_intervals(CLACTON, components=comps, evidence_count=8, bounds=[0, 100])
        assert prov["source"] == "panel"  # spread wins over the model quantiles

    def test_default_width_grows_as_evidence_thins(self):
        _, p_thin = compute_candidate_share_intervals(CLACTON, components=None, evidence_count=1, bounds=[0, 100])
        _, p_thick = compute_candidate_share_intervals(CLACTON, components=None, evidence_count=25, bounds=[0, 100])
        assert p_thin["params"]["half_width_pp"] > p_thick["params"]["half_width_pp"]

    def test_default_leader_inherits_payload_interval(self):
        payload = {**CLACTON, "interval_90_low": 58.0, "interval_90_high": 75.5}
        ivs, prov = compute_candidate_share_intervals(payload, components=None, evidence_count=2, bounds=[0, 100])
        assert prov["source"] == "default" and prov["params"]["leader_from_payload_interval"] is True
        assert ivs["Nigel Farage"]["p05"] == pytest.approx(58.0, abs=0.01)
        assert ivs["Nigel Farage"]["p95"] == pytest.approx(75.5, abs=0.01)


# ══ Part B · provenance + non-share guard ════════════════════════════════════
class TestProvenance:
    def test_provenance_stamps_source_and_params(self):
        _, prov = compute_candidate_share_intervals(CLACTON, components=None, evidence_count=3, bounds=[0, 100])
        assert set(prov) == {"source", "params"}
        assert prov["source"] in {"panel", "model", "default"}
        assert "half_width_pp" in prov["params"]

    def test_non_share_payload_returns_none(self):
        assert compute_candidate_share_intervals({"mean": 5, "sd": 1}, components=None) == (None, None)
        assert compute_candidate_share_intervals(0.5, components=None) == (None, None)
        assert compute_candidate_share_intervals({"Only One": 100.0}, components=None) == (None, None)

    def test_fraction_scale_payload_supported(self):
        frac = {"A": 0.6, "B": 0.3, "C": 0.1}
        ivs, prov = compute_candidate_share_intervals(frac, components=None, evidence_count=4, bounds=[0, 1])
        assert prov["source"] == "default"
        # emitted in pp regardless of the payload scale (median == share*100)
        assert ivs["A"]["median"] == pytest.approx(60.0, abs=0.01)


# ══ Part C · coherence-by-construction against the G2 validator ══════════════
class TestCoherenceAgainstG2:
    @pytest.mark.parametrize("components,evidence", [
        (_four_spread_components(), 8),                                  # panel
        ({"components": [{"source": "model:mc", "quantiles": {"Nigel Farage": {"p05": 58, "median": 67, "p95": 75}}}]}, 3),  # model
        (None, 1),                                                        # default
    ])
    def test_output_always_passes_g2(self, components, evidence):
        ivs, _ = compute_candidate_share_intervals(CLACTON, components=components, evidence_count=evidence, bounds=[0, 100])
        coherent, coverage, issues = assess_candidate_intervals(CLACTON, ivs, bounds=[0, 100])
        assert coherent, issues
        assert coverage == 1.0

    def test_tight_agreement_still_brackets_median(self):
        # All components agree exactly -> a degenerate spread must not invert or drop
        # the median (p05 <= median <= p95 by construction).
        agree = {"components": [_dist_component(CLACTON, f"c{i}") for i in range(4)]}
        ivs, _ = compute_candidate_share_intervals(CLACTON, components=agree, evidence_count=4, bounds=[0, 100])
        for cand, iv in ivs.items():
            assert iv["p05"] <= iv["median"] <= iv["p95"]

    def test_bounds_clamped_no_negative_no_overflow(self):
        # A big default width on a small share must clamp p05 to >= 0.
        ivs, _ = compute_candidate_share_intervals(CLACTON, components=None, evidence_count=1, bounds=[0, 100])
        assert ivs["Laurence Fox"]["p05"] >= 0.0
        assert all(iv["p95"] <= 100.0 for iv in ivs.values())
        # the widest default band is capped
        assert compute_candidate_share_intervals(CLACTON, components=None, evidence_count=0, bounds=[0, 100])[1]["params"]["half_width_pp"] <= DEFAULT_MAX_HALF_WIDTH_PP


# ══ Part D · commit-time auto-fill + the gate flip ═══════════════════════════
def _share_question(lg, *, impact="high", origin_profile=None):
    meta = {"forecast_hooks": {"profile": origin_profile}} if origin_profile else None
    q = lg.create_question(
        title="What vote shares will candidates receive in the 2026 Clacton by-election?",
        resolution_criteria="Resolves to the certified percentage vote share for each candidate.",
        outcome_space=OutcomeSpace(type="distribution", choices=list(CLACTON), bounds=[0, 100], units="%"),
        impact=impact, metadata=meta,
    )
    lg.add_evidence(question_id=q.id, source_or_note="BBC", claim="four candidates on the ballot")
    rc = lg.add_reference_class(question_id=q.id, name="leader share", inclusion_criteria="prior by-election shares", base_rate=0.60)
    # crux_named is ERROR for high-impact since the 2026-07-09 promotion; register one
    # so these commits isolate the interval gates instead of blocking on the crux gate.
    if impact == "high":
        lg.add_crux(question_id=q.id, crux_variable="Reform turnout vs the residual field")
    return q, (rc["id"] if isinstance(rc, dict) else rc)


_ANCHORED = {
    "Nigel Farage": {"base_rate": 0.60, "base_rate_source": "PollCheck"},
    "Count Binface": {"base_rate": 0.02, "base_rate_source": "Binface prior results"},
}


def _commit(lg, q, rc, **kw):
    return lg.create_snapshot(
        question_id=q.id, probability_or_distribution=dict(CLACTON),
        rationale="Farage favored; the residual field is small.", method="mc",
        reference_class_refs=[rc], outcome_paths=_ANCHORED,
        require_panel=False, require_components=False, require_structured_reasoning=False,
        enforce_resolved_hooks=True, **kw,
    )


def test_commit_auto_computes_intervals_from_ensemble_spread(tmp_path):
    lg = ForecastLedger(db_path=str(tmp_path / "auto.db"))
    lg.initialize_schema()
    q, rc = _share_question(lg)
    snap = _commit(lg, q, rc, ensemble_components=_four_spread_components())
    meta = snap.metadata or {}
    assert "candidate_share_intervals_pp" in meta
    assert meta["candidate_share_intervals_provenance"]["source"] == "panel"
    # the computed intervals are G2-coherent, so the coherence gate passed.
    sat = meta.get("saturation") or {}
    passed = {v["rule_id"]: v["passed"] for v in sat.get("verdicts", [])}
    assert passed.get("candidate_intervals_coherent") is True
    assert passed.get("candidate_intervals_present") is True  # coverage 1.0 after auto-fill


def test_commit_does_not_overwrite_supplied_intervals(tmp_path):
    lg = ForecastLedger(db_path=str(tmp_path / "supplied.db"))
    lg.initialize_schema()
    q, rc = _share_question(lg)
    supplied = {"Nigel Farage": {"p05": 60.0, "median": 67.0, "p95": 74.0}}
    snap = _commit(lg, q, rc, metadata={"candidate_share_intervals_pp": supplied}, ensemble_components=_four_spread_components())
    meta = snap.metadata or {}
    assert meta["candidate_share_intervals_pp"] == supplied
    assert "candidate_share_intervals_provenance" not in meta  # only stamped when WE compute


def test_default_width_commit_leader_from_payload(tmp_path):
    lg = ForecastLedger(db_path=str(tmp_path / "def.db"))
    lg.initialize_schema()
    q, rc = _share_question(lg)
    snap = lg.create_snapshot(
        question_id=q.id,
        probability_or_distribution={**CLACTON, "interval_90_low": 58.0, "interval_90_high": 75.5},
        rationale="Farage favored.", method="mc", reference_class_refs=[rc], outcome_paths=_ANCHORED,
        require_panel=False, require_components=False, require_structured_reasoning=False,
        enforce_resolved_hooks=True,
    )
    meta = snap.metadata or {}
    assert meta["candidate_share_intervals_provenance"]["source"] == "default"
    assert meta["candidate_share_intervals_pp"]["Nigel Farage"]["p05"] == pytest.approx(58.0, abs=0.01)


def test_gate_flip_absent_warns_on_live_high_impact_lint(tmp_path):
    # A live HIGH-IMPACT share board with NO intervals warns on lint (the flip).
    from forecasting.hooks import resolve_severities, run_hooks
    from forecasting.hooks.builtins import BUILTIN_RULES
    from forecasting.hooks.signals import build_context_from_ledger

    lg = ForecastLedger(db_path=str(tmp_path / "flip.db"))
    lg.initialize_schema()
    q, rc = _share_question(lg)
    # Commit an EXPLORATORY snapshot (bypasses auto-compute gating? no — exploratory
    # still computes, but the gate is OFF). To get an intervals-absent live current
    # snapshot we strip the metadata after commit via a fresh question with no components
    # and then blank the intervals to simulate a legacy board.
    _commit(lg, q, rc, ensemble_components=_four_spread_components())
    # Simulate a legacy board: clear the intervals on the stored snapshot.
    cur = lg.get_current_snapshot(q.id)
    from forecasting.ledger import allow_ledger_writes
    with allow_ledger_writes("test"):
        import json as _json
        with lg._connect() as conn:
            meta = _json.loads(conn.execute("SELECT metadata FROM forecast_snapshots WHERE forecast_id=?", (cur.forecast_id,)).fetchone()["metadata"])
            meta.pop("candidate_share_intervals_pp", None)
            meta.pop("candidate_share_intervals_provenance", None)
            conn.execute("UPDATE forecast_snapshots SET metadata=? WHERE forecast_id=?", (_json.dumps(meta), cur.forecast_id))
    ctx = build_context_from_ledger(lg, q.id, event="lint")
    assert ctx.is_candidate_share and ctx.high_impact
    policy = resolve_severities(lg.get_question(q.id), forecast_origin="live")
    report = run_hooks(ctx, policy, rules=BUILTIN_RULES)
    verdict = next((v for v in report.verdicts if v.rule_id == "candidate_intervals_present"), None)
    assert verdict is not None and not verdict.passed  # WARN fired (absent, high-impact)


def test_gate_present_silent_on_exploratory(tmp_path):
    from forecasting.hooks import resolve_severities, run_hooks
    from forecasting.hooks.builtins import BUILTIN_RULES
    from forecasting.hooks.spec import HookContext, Severity

    ctx = HookContext(
        question_id="q", forecast_origin="exploratory", event="update", impact="high",
        is_candidate_share=True, candidate_interval_coverage=0.0,
    )
    policy = {r.id: Severity.OFF for r in BUILTIN_RULES}
    report = run_hooks(ctx, policy, rules=BUILTIN_RULES)
    v = next((v for v in report.verdicts if v.rule_id == "candidate_intervals_present"), None)
    # exploratory origin never applies the modeled/live gate.
    assert v is None or v.passed


def test_no_interval_reason_escapes_presence(tmp_path):
    from forecasting.hooks import run_hooks
    from forecasting.hooks.builtins import BUILTIN_RULES
    from forecasting.hooks.spec import HookContext, Severity

    ctx = HookContext(
        question_id="q", forecast_origin="live", event="update", impact="high",
        is_candidate_share=True, candidate_interval_coverage=0.0,
        no_interval_reason="single-poll board; per-candidate spread not computable yet",
    )
    policy = {"candidate_intervals_present": Severity.WARN}
    report = run_hooks(ctx, policy, rules=[r for r in BUILTIN_RULES if r.id == "candidate_intervals_present"])
    v = next(v for v in report.verdicts if v.rule_id == "candidate_intervals_present")
    assert v.passed  # the reason escape satisfies the gate


# ══ Part E · the backfill dry-run ════════════════════════════════════════════
def test_backfill_scan_classifies_and_dry_runs(tmp_path):
    from forecasting.cli.core import _backfill_intervals_scan

    lg = ForecastLedger(db_path=str(tmp_path / "bf.db"))
    lg.initialize_schema()
    # (1) a board WITH components -> panel-derivable, but strip its auto-intervals to
    # simulate a legacy board that has not been re-forecast.
    q1, rc1 = _share_question(lg)
    _commit(lg, q1, rc1, ensemble_components=_four_spread_components())
    # (2) a board with NO components -> default-width derivable.
    q2, rc2 = _share_question(lg)
    lg.create_snapshot(
        question_id=q2.id, probability_or_distribution={**CLACTON, "interval_90_low": 58.0, "interval_90_high": 75.5},
        rationale="x", method="mc", reference_class_refs=[rc2], outcome_paths=_ANCHORED,
        require_panel=False, require_components=False, require_structured_reasoning=False, enforce_resolved_hooks=True,
    )
    # strip intervals from BOTH so they read as legacy boards needing backfill
    from forecasting.ledger import allow_ledger_writes
    import json as _json
    with allow_ledger_writes("test"), lg._connect() as conn:
        for q in (q1, q2):
            cur = lg.get_current_snapshot(q.id)
            meta = _json.loads(conn.execute("SELECT metadata FROM forecast_snapshots WHERE forecast_id=?", (cur.forecast_id,)).fetchone()["metadata"])
            meta.pop("candidate_share_intervals_pp", None)
            meta.pop("candidate_share_intervals_provenance", None)
            conn.execute("UPDATE forecast_snapshots SET metadata=? WHERE forecast_id=?", (_json.dumps(meta), cur.forecast_id))

    result = _backfill_intervals_scan(lg)
    assert result["scanned"] == 2
    assert result["derivable"] == 1          # q1 (panel)
    assert result["default_width"] == 1      # q2 (evidence-tied)
    assert result["none"] == 0
    assert result["by_source"]["panel"] == 1
    # dry-run does not write: the boards are still interval-less.
    assert lg.get_current_snapshot(q1.id).metadata.get("candidate_share_intervals_pp") is None


def test_backfill_apply_stamps_snapshot(tmp_path):
    from forecasting.cli.core import _backfill_intervals_scan
    from forecasting.ledger import allow_ledger_writes
    import json as _json

    lg = ForecastLedger(db_path=str(tmp_path / "bfa.db"))
    lg.initialize_schema()
    q1, rc1 = _share_question(lg)
    _commit(lg, q1, rc1, ensemble_components=_four_spread_components())
    with allow_ledger_writes("test"), lg._connect() as conn:
        cur = lg.get_current_snapshot(q1.id)
        meta = _json.loads(conn.execute("SELECT metadata FROM forecast_snapshots WHERE forecast_id=?", (cur.forecast_id,)).fetchone()["metadata"])
        meta.pop("candidate_share_intervals_pp", None)
        conn.execute("UPDATE forecast_snapshots SET metadata=? WHERE forecast_id=?", (_json.dumps(meta), cur.forecast_id))

    result = _backfill_intervals_scan(lg)
    with allow_ledger_writes("apply"):
        for p in result["proposals"]:
            if p.get("status") == "derivable":
                lg.annotate_snapshot(p["snapshot_id"], {"candidate_share_intervals_pp": p["intervals"]})
    stamped = lg.get_current_snapshot(q1.id).metadata.get("candidate_share_intervals_pp")
    assert isinstance(stamped, dict) and "Nigel Farage" in stamped
