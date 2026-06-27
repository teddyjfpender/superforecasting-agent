"""AIA P0.3 — confidence-gated supervisor override of the pool.

The judge's number was always recorded but historically IGNORED at commit time:
the desk always committed the pool. P0.3 lets a judge that self-declares HIGH
confidence in its revised probability override the pool — and nothing weaker.
The downside is bounded by construction: a low/medium-confidence judge can never
drag the committed number off a sound pool.

These tests pin:
  * the pure ``resolve_final_probability`` decision rule (truth table),
  * tolerant ``directional_confidence`` parsing,
  * that ``run_quorum`` carries ``final_probability`` + ``final_source`` and
    commits the pool when not high-confidence (back-compat) / the judge when
    high-confidence,
  * that the terminal Platt calibration lands on the WINNING number EXACTLY
    once (never twice, never zero times),
  * that the in-memory ``QuorumResult`` and the persisted ``panel_run`` agree on
    the committed number (the P0.1 divergence is closed).
"""

from __future__ import annotations

import json

import pytest

from forecasting.bayes_toolkit import platt_scale, prob_to_odds
from forecasting.ledger import ForecastLedger
from forecasting.models import OutcomeSpace
from forecasting.quorum import (
    JudgeSynthesis,
    parse_judge_response,
    resolve_final_probability,
    run_quorum,
)


# ── fixtures / helpers ────────────────────────────────────────────────────────


def _judge(prob, confidence="medium"):
    return JudgeSynthesis(
        probability=prob,
        rationale="r",
        directional_confidence=confidence,
        judge_model="opus",
    )


def _two_model_runner(p_by_model):
    """A panelist runner returning a fixed probability per model id, and a judge
    runner returning a fixed judge JSON when called with the judge model."""

    def runner(model, system, user):
        if model in p_by_model:
            p = p_by_model[model]
            return json.dumps(
                {
                    "probability": p,
                    "confidence_low": max(0.0, p - 0.1),
                    "confidence_high": min(1.0, p + 0.1),
                    "rationale": f"{model} says {p}",
                    "reasons_up": ["a"],
                    "reasons_down": ["b"],
                    "change_my_mind": ["c"],
                    "crux": "x",
                }
            )
        raise AssertionError(f"unexpected model {model}")

    return runner


def _judge_runner(prob, confidence):
    def runner(model, system, user):
        return json.dumps(
            {
                "probability": prob,
                "directional_confidence": confidence,
                "rationale": "judge synthesis",
                "consensus": ["c1"],
                "contradictions": [],
                "reasons_up": ["u"],
                "reasons_down": ["d"],
                "change_my_mind": ["m"],
                "blind_spots": ["bs"],
            }
        )

    return runner


def _ledger(tmp_path):
    return ForecastLedger(db_path=str(tmp_path / "q.db"))


def _question(lg, *, alpha=None):
    q = lg.create_question(
        title="Will the challenger flip the Ohio Senate seat in 2026?",
        resolution_criteria=(
            "Resolves YES if the challenger wins per the certified state result "
            "on election day."
        ),
        domain="politics",
        outcome_space=OutcomeSpace(type="binary"),
    )
    if alpha is not None:
        lg.update_question_config(q.id, hooks={"thresholds": {"alpha_extremize": alpha}})
        q = lg.get_question(q.id)
    return q


# ── 1. the pure decision rule (truth table) ───────────────────────────────────


def test_resolve_high_confidence_takes_judge():
    prob, src = resolve_final_probability(0.40, _judge(0.80, "high"))
    assert (prob, src) == (0.80, "judge_high")


@pytest.mark.parametrize("confidence", ["medium", "low"])
def test_resolve_non_high_confidence_keeps_pool(confidence):
    prob, src = resolve_final_probability(0.40, _judge(0.80, confidence))
    assert (prob, src) == (0.40, "pool")


def test_resolve_judge_prob_none_keeps_pool():
    # Even a HIGH-confidence judge with no usable number cannot override.
    prob, src = resolve_final_probability(0.40, _judge(None, "high"))
    assert (prob, src) == (0.40, "pool")


def test_resolve_judge_none_keeps_pool():
    prob, src = resolve_final_probability(0.40, None)
    assert (prob, src) == (0.40, "pool")


def test_resolve_is_pure_and_returns_floats():
    prob, src = resolve_final_probability(0.4, _judge(0.8, "high"))
    assert isinstance(prob, float) and isinstance(src, str)
    # Pure: calling twice with the same inputs yields identical output.
    assert resolve_final_probability(0.4, _judge(0.8, "high")) == (prob, src)


# ── 2. tolerant directional_confidence parsing ────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("high", "high"),
        ("medium", "medium"),
        ("low", "low"),
        ("HIGH", "high"),  # case-insensitive
        ("  Low  ", "low"),  # whitespace-tolerant
        ("garbage", "medium"),  # unknown -> medium
        ("", "medium"),
        (None, "medium"),  # missing -> medium
        (5, "medium"),  # wrong type -> medium
    ],
)
def test_parse_directional_confidence_is_tolerant(raw, expected):
    payload = {"probability": 0.7}
    if raw is not None or expected == "medium":
        payload["directional_confidence"] = raw
    judge = parse_judge_response(json.dumps(payload), "opus")
    assert judge.directional_confidence == expected


def test_parse_missing_key_defaults_to_medium():
    judge = parse_judge_response(json.dumps({"probability": 0.7}), "opus")
    assert judge.directional_confidence == "medium"


def test_judge_default_confidence_is_medium():
    # Back-compat: a JudgeSynthesis built without the field is non-overriding.
    assert JudgeSynthesis(probability=0.9, rationale="").directional_confidence == "medium"


# ── 3. run_quorum carries final_probability + final_source ─────────────────────


def _run(p_by_model, judge_prob, judge_conf, *, alpha=1.0):
    models = list(p_by_model)
    return run_quorum(
        question_title="Q",
        resolution_criteria="R",
        models=models,
        runner=_two_model_runner(p_by_model),
        judge_model="judge/model",
        judge_runner=_judge_runner(judge_prob, judge_conf),
        trim=0,
        alpha_extremize=alpha,
        max_concurrency=1,
    )


def test_run_quorum_carries_final_fields():
    res = _run({"m1": 0.6, "m2": 0.5}, judge_prob=0.9, judge_conf="medium")
    assert res.final_probability is not None
    assert res.final_source == "pool"
    assert res.to_dict()["final_source"] == "pool"
    assert "final_probability" in res.to_dict()


def test_committed_is_pool_when_not_high_confidence():
    res = _run({"m1": 0.6, "m2": 0.5}, judge_prob=0.9, judge_conf="low")
    # Judge wanted 0.9 but only at low confidence -> pool is committed.
    assert res.final_source == "pool"
    assert res.committed_probability == pytest.approx(res.aggregate_probability)


def test_committed_is_judge_when_high_confidence():
    res = _run({"m1": 0.6, "m2": 0.5}, judge_prob=0.9, judge_conf="high")
    assert res.final_source == "judge_high"
    # alpha == 1.0 -> committed equals the judge's raw number exactly.
    assert res.committed_probability == pytest.approx(0.9)
    assert res.committed_probability != pytest.approx(res.aggregate_probability)


# ── 4. back-compat: byte-identical at default ─────────────────────────────────


def test_backcompat_committed_is_byte_identical_to_pool_at_default():
    # No judge override (medium) AND alpha == 1.0 -> the committed number is the
    # bare pool, byte-for-byte (no Platt, no override).
    p_by_model = {"m1": 0.62, "m2": 0.48}
    res = _run(p_by_model, judge_prob=0.9, judge_conf="medium", alpha=1.0)
    # Reconstruct the bare geomean-of-odds pool independently.
    odds = [prob_to_odds(p) for p in p_by_model.values()]
    geo = (odds[0] * odds[1]) ** 0.5
    expected_pool = geo / (1.0 + geo)
    assert res.committed_probability == res.aggregate_probability
    assert res.committed_probability == pytest.approx(expected_pool, abs=1e-12)
    # pre_extremize stays None at the identity (mirrors P0.1's invariant).
    assert res.aggregation.pre_extremize_probability is None


# ── 5. terminal Platt applied EXACTLY ONCE to the winning number ──────────────


def test_platt_applied_once_to_pool_branch():
    # Pool wins (medium judge). The committed number must be Platt(pool, alpha)
    # applied exactly once — i.e. == aggregation.aggregate_probability, and ==
    # platt_scale(pre_extremize, alpha).
    res = _run({"m1": 0.6, "m2": 0.5}, judge_prob=0.95, judge_conf="medium", alpha=1.5)
    assert res.final_source == "pool"
    pre = res.aggregation.pre_extremize_probability
    assert pre is not None  # alpha != 1.0 recorded the pre-calibration scalar
    once = platt_scale(pre, alpha=1.5, d=1.0)
    assert res.committed_probability == pytest.approx(once, abs=1e-12)
    # Not applied twice: a double-apply would be platt_scale(once, 1.5).
    twice = platt_scale(once, alpha=1.5, d=1.0)
    assert res.committed_probability != pytest.approx(twice, abs=1e-9)


def test_platt_applied_once_to_judge_branch():
    # Judge wins (high). The committed number must be Platt(judge_raw, alpha)
    # applied exactly once — never the un-Platt'd raw, never double.
    judge_raw = 0.9
    res = _run({"m1": 0.6, "m2": 0.5}, judge_prob=judge_raw, judge_conf="high", alpha=1.5)
    assert res.final_source == "judge_high"
    once = platt_scale(judge_raw, alpha=1.5, d=1.0)
    assert res.committed_probability == pytest.approx(once, abs=1e-12)
    # Zero-times (raw judge) and twice are both wrong.
    assert res.committed_probability != pytest.approx(judge_raw, abs=1e-6)
    twice = platt_scale(once, alpha=1.5, d=1.0)
    assert res.committed_probability != pytest.approx(twice, abs=1e-9)


# ── 6. QuorumResult and the persisted panel_run agree ─────────────────────────


def _record(lg, q, res):
    return lg.record_panel_run(
        question_id=q.id,
        estimates=res.panel_estimates(),
        aggregation_method=res.pool_method,
        trim=res.trim,
        triggered_by="quorum",
        judge=res.judge.to_dict() if res.judge else None,
        final_probability=res.committed_probability,
        final_source=res.final_source,
    )


def test_panel_run_agrees_with_quorum_result_pool(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)  # alpha defaults to 1.0
    res = _run({"m1": 0.6, "m2": 0.5}, judge_prob=0.9, judge_conf="medium")
    pr = _record(lg, q, res)
    assert pr["aggregate_probability"] == pytest.approx(res.committed_probability)
    assert pr["final_source"] == "pool"


def test_panel_run_agrees_with_quorum_result_judge_override(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)
    res = _run({"m1": 0.6, "m2": 0.5}, judge_prob=0.9, judge_conf="high")
    pr = _record(lg, q, res)
    # The persisted aggregate is the committed (overridden) number, not the pool.
    assert pr["aggregate_probability"] == pytest.approx(res.committed_probability)
    assert pr["aggregate_probability"] == pytest.approx(0.9)
    assert pr["final_source"] == "judge_high"
    # The bare pool is still auditable in the spread for transparency.
    assert pr["spread_summary"]["pool_probability"] == pytest.approx(
        res.aggregate_probability, abs=1e-6
    )


def test_panel_run_no_double_platt_with_per_question_alpha(tmp_path):
    # The P0.1 divergence closed: with a per-question alpha, the QuorumResult
    # (which already applied alpha) and the persisted panel_run agree, and the
    # number is Platt'd EXACTLY ONCE end to end (record_panel_run must NOT
    # re-pool-with-alpha when a resolved number is passed).
    lg = _ledger(tmp_path)
    q = _question(lg, alpha=1.5)
    from forecasting.hooks.thresholds import resolve_alpha_extremize

    alpha = resolve_alpha_extremize(q.metadata)
    assert alpha == 1.5
    res = _run({"m1": 0.6, "m2": 0.5}, judge_prob=0.9, judge_conf="medium", alpha=alpha)
    pr = _record(lg, q, res)
    # Agreement is exact.
    assert pr["aggregate_probability"] == pytest.approx(res.committed_probability)
    # And it equals a single Platt of the bare pool — not a double application.
    pre = res.aggregation.pre_extremize_probability
    once = platt_scale(pre, alpha=1.5, d=1.0)
    assert pr["aggregate_probability"] == pytest.approx(once, abs=1e-9)


def test_panel_run_audit_markers_accurate_on_judge_override_with_alpha(tmp_path):
    # Audit integrity: a quorum commit where the JUDGE overrides AND a per-question
    # alpha is configured must persist ACCURATE calibration markers — applied_alpha,
    # terminal_calibration_applied, and the CALIBRATED pool the override beat — not
    # the identity/bare-pool values record_panel_run wrote on this path before.
    lg = _ledger(tmp_path)
    q = _question(lg, alpha=1.5)
    res = _run({"m1": 0.6, "m2": 0.5}, judge_prob=0.9, judge_conf="high", alpha=1.5)
    pr = _record(lg, q, res)
    spread = pr["spread_summary"]
    # Committed = the judge's number, Platt'd exactly once.
    assert pr["final_source"] == "judge_high"
    assert pr["aggregate_probability"] == pytest.approx(platt_scale(0.9, alpha=1.5), abs=1e-9)
    # The persisted markers describe the panel's REAL calibration, not the identity.
    assert spread["applied_alpha"] == pytest.approx(1.5)
    assert spread["terminal_calibration_applied"] is True
    # pool_probability is the CALIBRATED pool (what the override beat), and it is a
    # single Platt of the bare pool.
    assert spread["pool_probability"] == pytest.approx(res.aggregate_probability, abs=1e-6)
    assert res.aggregate_probability == pytest.approx(
        platt_scale(res.aggregation.pre_extremize_probability, alpha=1.5), abs=1e-9
    )


def test_record_panel_run_without_resolved_number_pools_with_alpha(tmp_path):
    # Non-quorum (perspective panel) callers pass no final_probability: the old
    # pool-with-alpha behaviour is preserved unchanged, and final_source is 'pool'.
    lg = _ledger(tmp_path)
    q = _question(lg, alpha=1.5)
    estimates = [
        {"perspective": "outside", "probability": 0.6, "agent_model": "m1"},
        {"perspective": "inside", "probability": 0.5, "agent_model": "m2"},
    ]
    pr = lg.record_panel_run(question_id=q.id, estimates=estimates, trim=0)
    assert pr["final_source"] == "pool"
    # The aggregate is the alpha-calibrated pool (not the bare one).
    odds = [prob_to_odds(0.6), prob_to_odds(0.5)]
    geo = (odds[0] * odds[1]) ** 0.5
    bare = geo / (1.0 + geo)
    assert pr["aggregate_probability"] == pytest.approx(
        platt_scale(bare, alpha=1.5, d=1.0), abs=1e-9
    )
