"""G4 · GRANULARITY DISCIPLINE (Tetlock's hallmark) — WARN-only round-number audit.

A binary commit sitting on a round-number anchor (a 0.10 multiple, or 0.25/0.5/0.75)
that NO pooled component produced, with no uncertainty_justified escape, WARNs. It
NEVER blocks (hard-gating precision teaches fabricated 0.43s). Legitimately-justified
rounds — a pool that genuinely lands on 0.60 — never fire."""

from __future__ import annotations

from forecasting.hooks import resolve_severities, run_hooks
from forecasting.hooks.distribution import is_round_number_anchored
from forecasting.hooks.spec import HookContext


def _ctx(**kw) -> HookContext:
    base = dict(question_id="fq", event="update", forecast_origin="live", outcome_type="binary",
                is_thesis_or_factor=False)
    base.update(kw)
    return HookContext(**base)


def _verdict(ctx):
    report = run_hooks(ctx, resolve_severities(None, forecast_origin="live"))
    return next((v for v in report.verdicts if v.rule_id == "granularity_disciplined"), None)


# ── the signal helper (pure arithmetic) ───────────────────────────────────────
def test_round_number_with_matching_pool_is_earned():
    comps = [{"source": "base_rate", "probability": 0.60}, {"source": "inside", "probability": 0.55}]
    assert is_round_number_anchored(0.60, comps) is False  # a component produced 0.60


def test_round_number_with_no_matching_pool_fires():
    comps = [{"source": "base_rate", "probability": 0.57}, {"source": "inside", "probability": 0.55}]
    assert is_round_number_anchored(0.60, comps) is True


def test_quarter_points_are_round():
    assert is_round_number_anchored(0.25, []) is True
    assert is_round_number_anchored(0.75, []) is True
    assert is_round_number_anchored(0.5, []) is True


def test_non_round_number_never_fires():
    assert is_round_number_anchored(0.63, []) is False
    assert is_round_number_anchored(0.575, []) is False


def test_uncertainty_justified_suppresses():
    assert is_round_number_anchored(0.5, [], uncertainty_justified=True) is False


def test_extreme_certainty_excluded():
    # 0.0 / 1.0 are degenerate certainty, not round-number hedging — not flagged.
    assert is_round_number_anchored(1.0, []) is False
    assert is_round_number_anchored(0.0, []) is False


def test_non_binary_payload_never_fires():
    assert is_round_number_anchored({"a": 0.5, "b": 0.5}, []) is False


# ── the rule (WARN, applies binary-only, never blocks) ────────────────────────
def test_rule_warns_on_bare_round_number():
    v = _verdict(_ctx(round_number_anchored=True, committed_winner_prob=0.6))
    assert v is not None and v.passed is False and v.severity.value == "warn"
    assert "0.6" in v.message and "round-number anchor" in v.message


def test_rule_passes_when_not_anchored():
    v = _verdict(_ctx(round_number_anchored=False, committed_winner_prob=0.63))
    assert v is not None and v.passed is True


def test_rule_never_error_even_in_strict():
    from forecasting.hooks.profiles import profile_severities
    from forecasting.hooks.spec import Severity
    assert profile_severities("strict")["granularity_disciplined"] is Severity.WARN


def test_rule_does_not_apply_to_distribution():
    v = _verdict(_ctx(outcome_type="distribution", is_distribution=True, round_number_anchored=True))
    assert v is None


def test_rule_does_not_apply_to_categorical():
    v = _verdict(_ctx(outcome_type="categorical", is_categorical=True, round_number_anchored=True))
    assert v is None
