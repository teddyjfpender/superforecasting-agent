"""AIA P1.3 — simplex-constrained market+LLM Brier-minimizing ensemble.

Covers:
  * simplex constraint (weights >= 0, sum to 1, one per source),
  * weight recovery (w=1 on the signal when the other source is pure noise),
  * the paper's complementarity finding: ensemble Brier <= min(per-source Brier)
    on a complementary fixture (the blend beats BOTH inputs),
  * LOO ensemble Brier is computed honestly (refit on n-1, score held-out),
  * bootstrap determinism (seeded => byte-identical CI),
  * small-n + degenerate guards,
  * a HARD GUARD that no committed forecast / live default changed (the static
    market_quality advisory weight + the un-gated path are byte-identical).
"""

from __future__ import annotations

import random

import pytest

from forecasting.market_ensemble import (
    BOOTSTRAP_SEED,
    DEFAULT_MIN_SAMPLE,
    LLM_SOURCE,
    MARKET_SOURCE,
    brier,
    collect_market_llm_triples,
    complementarity_report,
    fitted_market_advisory_weight,
    simplex_brier_weights,
)


# ── fixtures ──────────────────────────────────────────────────────────────────


def _signal_plus_noise(n: int = 200, seed: int = 7):
    """Market tracks the outcome; LLM is pure coin-flip noise."""
    rng = random.Random(seed)
    outcomes, market, llm = [], [], []
    for _ in range(n):
        y = 1.0 if rng.random() < 0.5 else 0.0
        outcomes.append(y)
        # Market: informative — close to the truth with small jitter.
        market.append(min(1.0, max(0.0, (0.85 if y else 0.15) + rng.uniform(-0.05, 0.05))))
        # LLM: pure noise around 0.5.
        llm.append(rng.uniform(0.3, 0.7))
    return outcomes, {MARKET_SOURCE: market, LLM_SOURCE: llm}


def _complementary(n: int = 300, seed: int = 11):
    """Two noisy-but-orthogonal estimators of the truth: the blend beats both.

    Each source = truth + its OWN independent noise. Averaging cancels noise, so
    the convex blend has lower Brier than either input (the paper's finding).
    """
    rng = random.Random(seed)
    outcomes, market, llm = [], [], []
    for _ in range(n):
        latent = rng.random()  # the true P(yes)-ish driver
        y = 1.0 if rng.random() < latent else 0.0
        outcomes.append(y)
        market.append(min(1.0, max(0.0, latent + rng.gauss(0.0, 0.22))))
        llm.append(min(1.0, max(0.0, latent + rng.gauss(0.0, 0.22))))
    return outcomes, {MARKET_SOURCE: market, LLM_SOURCE: llm}


# ── 1. simplex constraint ─────────────────────────────────────────────────────


def test_weights_are_a_valid_simplex_point():
    outcomes, sources = _complementary()
    res = simplex_brier_weights(outcomes, sources)
    weights = res["weights"]
    assert weights is not None
    assert set(weights) == {MARKET_SOURCE, LLM_SOURCE}
    for w in weights.values():
        assert w >= 0.0
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-9)


# ── 2. weight recovery on a pure-noise source ─────────────────────────────────


def test_recovers_full_weight_on_the_market_when_llm_is_noise():
    outcomes, sources = _signal_plus_noise()
    res = simplex_brier_weights(outcomes, sources)
    assert res["weights"][MARKET_SOURCE] > 0.9
    assert res["weights"][LLM_SOURCE] < 0.1


def test_recovers_full_weight_on_the_llm_when_market_is_noise():
    outcomes, sources = _signal_plus_noise()
    # Swap roles: now the "market" column is the noise, "llm" the signal.
    swapped = {MARKET_SOURCE: sources[LLM_SOURCE], LLM_SOURCE: sources[MARKET_SOURCE]}
    res = simplex_brier_weights(outcomes, swapped)
    assert res["weights"][LLM_SOURCE] > 0.9
    assert res["weights"][MARKET_SOURCE] < 0.1


# ── 3. the paper: blend beats BOTH inputs ─────────────────────────────────────


def test_ensemble_brier_beats_both_inputs_on_complementary_data():
    outcomes, sources = _complementary()
    res = simplex_brier_weights(outcomes, sources)
    per = res["per_source_brier"]
    # In-sample ensemble Brier <= min of the two sources.
    assert res["ensemble_brier"] <= min(per.values()) + 1e-9
    # And it strictly improves on the better of the two (orthogonal signal).
    assert res["ensemble_brier"] < min(per.values())
    # The honest LOO number also beats both => beats_both gate fires.
    assert res["loo_ensemble_brier"] < per[MARKET_SOURCE]
    assert res["loo_ensemble_brier"] < per[LLM_SOURCE]
    assert res["beats_both"] is True


# ── 4. LOO is computed correctly ──────────────────────────────────────────────


def test_loo_matches_a_hand_rolled_leave_one_out():
    from forecasting.market_ensemble import _best_w_market

    outcomes, sources = _complementary(n=40, seed=3)
    res = simplex_brier_weights(outcomes, sources, min_sample=10)
    market = sources[MARKET_SOURCE]
    llm = sources[LLM_SOURCE]
    n = len(outcomes)
    total = 0.0
    for k in range(n):
        m = [market[i] for i in range(n) if i != k]
        l = [llm[i] for i in range(n) if i != k]
        y = [outcomes[i] for i in range(n) if i != k]
        w = _best_w_market(m, l, y)
        pred = w * market[k] + (1.0 - w) * llm[k]
        total += (pred - outcomes[k]) ** 2
    expected = total / n
    assert res["loo_ensemble_brier"] == pytest.approx(expected, abs=1e-12)


def test_loo_is_not_more_optimistic_than_insample():
    outcomes, sources = _complementary()
    res = simplex_brier_weights(outcomes, sources)
    # LOO removes in-sample optimism, so it cannot be (much) below in-sample.
    assert res["loo_ensemble_brier"] >= res["ensemble_brier"] - 1e-9


# ── 5. bootstrap determinism ──────────────────────────────────────────────────


def test_bootstrap_ci_is_deterministic_under_seed():
    outcomes, sources = _complementary()
    a = simplex_brier_weights(outcomes, sources, seed=BOOTSTRAP_SEED)
    b = simplex_brier_weights(outcomes, sources, seed=BOOTSTRAP_SEED)
    assert a["bootstrap_ci_95"] == b["bootstrap_ci_95"]


def test_bootstrap_ci_brackets_the_point_estimate():
    outcomes, sources = _complementary()
    res = simplex_brier_weights(outcomes, sources)
    lo, hi = res["bootstrap_ci_95"][MARKET_SOURCE]
    assert lo <= res["weights"][MARKET_SOURCE] <= hi
    # market + llm CI are mirror images.
    llm_lo, llm_hi = res["bootstrap_ci_95"][LLM_SOURCE]
    assert llm_lo == pytest.approx(1.0 - hi, abs=1e-9)
    assert llm_hi == pytest.approx(1.0 - lo, abs=1e-9)


# ── 6. guards: small-n + degenerate ───────────────────────────────────────────


def test_small_sample_returns_no_weights():
    outcomes, sources = _complementary(n=5)
    res = simplex_brier_weights(outcomes, sources, min_sample=DEFAULT_MIN_SAMPLE)
    assert res["weights"] is None
    assert res["loo_ensemble_brier"] is None
    assert any("sample too small" in note for note in res["notes"])


def test_degenerate_single_source_falls_back_to_present_source():
    outcomes = [1.0, 0.0, 1.0, 0.0, 1.0]
    sources = {MARKET_SOURCE: [0.8, 0.2, 0.7, 0.3, 0.9], LLM_SOURCE: []}
    res = simplex_brier_weights(outcomes, sources, min_sample=2)
    assert res["weights"] == {MARKET_SOURCE: 1.0, LLM_SOURCE: 0.0}
    assert any("only one source" in note for note in res["notes"])


def test_outcomes_must_be_zero_or_one():
    # Non-{0,1} outcomes are dropped, shrinking n below min_sample.
    outcomes = [0.5] * 50
    sources = {MARKET_SOURCE: [0.5] * 50, LLM_SOURCE: [0.5] * 50}
    res = simplex_brier_weights(outcomes, sources)
    assert res["n"] == 0
    assert res["weights"] is None


# ── 7. HARD GUARD: no committed forecast / live default changed ───────────────


def test_static_market_quality_advisory_weight_unchanged():
    """The blend module must not perturb the STATIC advisory weight ladder."""
    from forecasting.market_quality import _TIER_WEIGHTS

    assert _TIER_WEIGHTS == {
        "liquid": 1.0,
        "moderate": 0.7,
        "thin": 0.35,
        "stale": 0.25,
        "placeholder": 0.05,
    }


def test_fitted_weight_does_not_ship_without_the_full_gate():
    """The fitted weight ships ONLY behind sample+LOO+CI; otherwise static stays."""
    # Small sample => no fit => static weight returned unchanged.
    outcomes, sources = _complementary(n=5)
    res = simplex_brier_weights(outcomes, sources, min_sample=DEFAULT_MIN_SAMPLE)
    decision = fitted_market_advisory_weight(res, static_weight=1.0)
    assert decision["fitted"] is False
    assert decision["weight"] == 1.0

    # A fit that does NOT beat both inputs (noise LLM): the LLM weight ~0, its CI
    # touches/includes 0, so the gate must refuse to ship.
    outcomes, sources = _signal_plus_noise()
    res = simplex_brier_weights(outcomes, sources)
    decision = fitted_market_advisory_weight(res, static_weight=1.0)
    assert decision["fitted"] is False
    assert decision["weight"] == 1.0


def test_fitted_weight_ships_only_when_complementary_and_significant():
    outcomes, sources = _complementary(n=400, seed=21)
    res = simplex_brier_weights(outcomes, sources, min_sample=DEFAULT_MIN_SAMPLE)
    decision = fitted_market_advisory_weight(res, static_weight=1.0)
    # Complementary data clears all three gate conditions.
    assert decision["fitted"] is True
    assert 0.0 < decision["weight"] < 1.0


# ── 8. ledger collector (round-trips through a real in-memory ledger) ─────────


_CRITERIA = "Resolves YES if the named event occurs by the close date; else NO."


def test_collector_pulls_market_llm_outcome_triples(tmp_path):
    pytest.importorskip("forecasting.ledger")
    from forecasting.ledger import ForecastLedger

    ledger = ForecastLedger(tmp_path / "ledger.db")
    # Build a couple of resolved binary questions with an agent forecast + a
    # market baseline, then confirm the collector aligns them.
    triples_built = 0
    for i, (llm_p, mkt_p, outcome) in enumerate(
        [(0.7, 0.6, "yes"), (0.3, 0.4, "no"), (0.8, 0.55, "yes")]
    ):
        q = ledger.create_question(
            title=f"Binary fixture {i} occurs?",
            resolution_criteria=_CRITERIA,
            domain="macro",
        )
        snap = ledger.create_snapshot(
            question_id=q.id,
            probability_or_distribution=llm_p,
            rationale="agent forecast",
        )
        ledger.add_baseline_comparison(
            question_id=q.id,
            source="polymarket",
            baseline_type="market_price",
            probability_or_distribution=mkt_p,
        )
        ledger.resolve_question(question_id=q.id, outcome=outcome, auto_score=True)
        ledger.score_baseline_comparisons(q.id)
        triples_built += 1

    collected = collect_market_llm_triples(ledger, forecast_origin="live")
    assert collected["n"] == triples_built
    assert len(collected["sources"][MARKET_SOURCE]) == triples_built
    assert len(collected["sources"][LLM_SOURCE]) == triples_built
    # And the end-to-end report runs without shipping a fitted weight (tiny n).
    report = complementarity_report(ledger, forecast_origin="live")
    assert report["n"] == triples_built
    assert report["advisory_weight_decision"]["fitted"] is False
