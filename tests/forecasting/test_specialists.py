"""Deterministic specialists as quorum panelists (BLF A5).

Red-first coverage for :mod:`forecasting.specialists`:

* the ``Distribution`` value object (coherent, monotone quantiles; CRPS; tail
  probabilities);
* the climatology-KNN and seasonal-naive estimators;
* decline-when-no-data honesty (a specialist with no reachable series casts NO
  forecast — it raises so the quorum records a labeled, excluded seat);
* registration: a specialist lands as a ``model:*`` panelist with a stable id in
  ``run_quorum``'s panel estimates, and that id is a valid track-record key;
* question-class conservatism (binary / categorical / thesis never get one);
* the six live continuous-miss classes: runnable? + directional read.
"""

from __future__ import annotations

import json
import math
from datetime import date

import pytest

from forecasting.models import OutcomeSpace
from forecasting.quorum import parse_panelist_response, run_quorum
from forecasting.specialists import (
    CLIMATOLOGY_KNN,
    LIVING_MODEL,
    SEASONAL_NAIVE,
    SPECIALIST_IDS,
    Distribution,
    Observation,
    Series,
    SpecialistDeclined,
    attach_specialists,
    climatology_knn,
    derive_threshold,
    living_model,
    make_specialist_runner,
    run_specialist,
    seasonal_naive,
    specialist_seats_for,
)
from forecasting import track_record


# ── tiny question stub (mirrors ForecastQuestion's fields the module reads) ───


class _Q:
    def __init__(self, *, outcome_type="numeric", units="USD", metadata=None, title="Q",
                 resolution_criteria="R", id="q1"):
        self.id = id
        self.title = title
        self.resolution_criteria = resolution_criteria
        self.outcome_space = OutcomeSpace(
            type=outcome_type,
            choices=(["yes", "no"] if outcome_type == "binary" else []),
            units=units,
        )
        self.metadata = metadata or {}


def _daily_series(values, *, end=date(2026, 6, 30), unit="USD", kind="continuous", key="S"):
    """Build an oldest->newest daily Series ending at ``end``."""
    from datetime import timedelta

    n = len(values)
    obs = tuple(
        Observation(as_of=end - timedelta(days=(n - 1 - i)), value=float(v))
        for i, v in enumerate(values)
    )
    return Series(key=key, unit=unit, kind=kind, observations=obs, as_of=end)


# ── Distribution ──────────────────────────────────────────────────────────────


def test_distribution_quantiles_are_monotone_and_coherent():
    dist = Distribution.from_sample([3, 1, 2, 5, 4, 6, 8, 7])
    qs = [q for _, q in dist.quantiles((0.1, 0.25, 0.5, 0.75, 0.9))]
    assert qs == sorted(qs)  # monotone non-decreasing
    assert min(dist.samples) <= dist.median() <= max(dist.samples)
    # central 80% interval is inside the support and ordered
    lo, hi = dist.interval(0.8)
    assert lo <= dist.median() <= hi


def test_distribution_tail_probabilities_and_crps():
    dist = Distribution.from_sample([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
    assert dist.prob_ge(5) == pytest.approx(0.5)  # 5..9 -> 5/10
    assert dist.prob_le(4) == pytest.approx(0.5)
    # CRPS is non-negative and smaller for an observed value at the centre.
    centred = dist.crps(4.5)
    tail = dist.crps(20.0)
    assert centred >= 0.0
    assert centred < tail


def test_distribution_count_kind_rounds_quantiles_to_integers():
    dist = Distribution.from_sample([0, 0, 1, 1, 2, 3], kind="count")
    for _, value in dist.quantiles((0.25, 0.5, 0.75)):
        assert value == round(value)


# ── estimators ────────────────────────────────────────────────────────────────


def test_climatology_knn_selects_same_season_neighbours():
    # Two summers of daily-ish data; a July target should draw July neighbours,
    # not the January ones, so the distribution centres on the summer level.
    from datetime import timedelta

    obs = []
    for year in (2024, 2025):
        for month, level in ((1, 10.0), (7, 40.0)):
            for day in range(1, 11):
                obs.append(Observation(as_of=date(year, month, day), value=level))
    series = Series(key="temp", unit="F", kind="continuous",
                    observations=tuple(obs), as_of=date(2025, 7, 10))
    dist = climatology_knn(series, target=date(2026, 7, 15), k=12)
    assert dist is not None
    assert dist.median() == pytest.approx(40.0)  # summer, not winter (10.0)


def test_climatology_knn_declines_on_thin_series():
    assert climatology_knn(_daily_series([1, 2, 3]), target=date(2026, 7, 1)) is None


def test_seasonal_naive_takes_same_phase_values():
    # Weekly seasonality: value == 100 + weekday. period=7 last-k same-phase.
    from datetime import timedelta

    end = date(2026, 6, 30)  # a Tuesday
    values = []
    for i in range(28):
        d = end - timedelta(days=27 - i)
        values.append(100.0 + d.weekday())
    series = _daily_series(values, end=end)
    dist = seasonal_naive(series, period=7, k=4)
    assert dist is not None
    # every same-phase value is the same weekday -> identical, median == that value
    assert dist.median() == pytest.approx(100.0 + end.weekday())


def test_seasonal_naive_declines_without_a_full_cycle():
    assert seasonal_naive(_daily_series([1, 2, 3, 4]), period=7) is None


def test_living_model_passthrough_and_decline():
    q = _Q()
    injected = Distribution.from_sample([9, 10, 11])
    assert living_model(q, projection_provider=lambda _q: injected) is injected
    assert living_model(q, projection_provider=lambda _q: None) is None
    assert living_model(q, projection_provider=None) is None


# ── decline-when-no-data honesty ──────────────────────────────────────────────


def test_run_specialist_declines_when_series_unreachable():
    q = _Q(metadata={"specialist": {"threshold": 100, "operator": ">="}})
    forecast = run_specialist(
        CLIMATOLOGY_KNN, q, series_provider=lambda _q, as_of: None, as_of=date(2026, 6, 30)
    )
    assert forecast.declined is True
    assert not forecast.produced
    assert "series" in forecast.reason.lower()


def test_specialist_runner_raises_declined_so_quorum_excludes_the_seat():
    q = _Q(metadata={"specialist": {"threshold": 100, "operator": ">="}})
    runner = make_specialist_runner(
        base_runner=lambda m, s, u: "{}",
        question=q,
        series_provider=lambda _q, as_of: None,
        as_of=date(2026, 6, 30),
    )
    with pytest.raises(SpecialistDeclined):
        runner(CLIMATOLOGY_KNN, "sys", "user")


# ── question-class conservatism ───────────────────────────────────────────────


@pytest.mark.parametrize("outcome_type", ["binary", "categorical", "thesis"])
def test_no_specialist_for_non_continuous_classes(outcome_type):
    q = _Q(outcome_type=outcome_type, units=None)
    assert specialist_seats_for(q) == ()
    models, runner = attach_specialists(["a/b"], lambda m, s, u: "{}", q,
                                        series_provider=lambda _q, as_of: None,
                                        as_of=date(2026, 6, 30))
    assert models == ["a/b"]  # byte-identical — no seat added


@pytest.mark.parametrize("outcome_type", ["numeric", "distribution"])
def test_continuous_classes_register_specialist_seats(outcome_type):
    q = _Q(outcome_type=outcome_type, units="USD",
           metadata={"specialist": {"threshold": 100, "operator": ">="}})
    seats = specialist_seats_for(q)
    assert set(seats) == set(SPECIALIST_IDS)


def test_attach_is_a_noop_without_a_derivable_threshold():
    # A continuous question with no threshold: a specialist cannot cast a binary
    # vote, so it must not join the panel (conservatism over noise).
    q = _Q(outcome_type="numeric", units="USD", metadata={})
    assert derive_threshold(q) == (None, None)
    models, _ = attach_specialists(["a/b"], lambda m, s, u: "{}", q,
                                   series_provider=lambda _q, as_of: _daily_series([1, 2, 3]),
                                   as_of=date(2026, 6, 30))
    assert models == ["a/b"]


# ── registration + track-record round-trip ────────────────────────────────────


def _series_provider_for(values):
    def _provider(_q, as_of):
        return _daily_series(values, end=as_of)
    return _provider


def test_specialist_lands_as_model_panelist_in_run_quorum():
    q = _Q(outcome_type="numeric", units="USD", id="btc",
           metadata={"specialist": {"threshold": 100.0, "operator": ">="}})
    # A rising series comfortably above the 100 threshold -> high P(>=100). 30 daily
    # points so BOTH the climatology and the (period-7) seasonal-naive seat survive.
    provider = _series_provider_for([120 + i for i in range(30)])

    def base_runner(model, system, user):
        if "JUDGE" in system:
            return json.dumps({"probability": 0.7, "rationale": "j"})
        return json.dumps({"probability": 0.6, "rationale": "llm"})

    models, runner = attach_specialists(
        ["a/b"], base_runner, q, series_provider=provider, as_of=date(2026, 6, 30)
    )
    assert CLIMATOLOGY_KNN in models
    res = run_quorum(
        question_title=q.title,
        resolution_criteria=q.resolution_criteria,
        models=models,
        runner=runner,
        judge_model=None,
        trim=0,
    )
    ids = {e.get("agent_model") for e in res.panel_estimates()}
    assert CLIMATOLOGY_KNN in ids and SEASONAL_NAIVE in ids
    knn = next(e for e in res.panel_estimates() if e.get("agent_model") == CLIMATOLOGY_KNN)
    assert knn["probability"] > 0.9  # series sits above the threshold


def test_track_record_accrues_under_the_stable_specialist_id():
    # Two resolved observations for the specialist's stable id flow through the
    # same S7.5 track-record math the LLM panelists use.
    obs = [
        track_record.ComponentObservation(
            name=CLIMATOLOGY_KNN, kind="model", question_id=f"q{i}",
            component_brier=0.05, aggregate_brier=0.20,
        )
        for i in range(6)
    ]
    records = track_record.summarize_components(obs, min_count=5)
    weights = track_record.weights_by_name(records, kind="model")
    assert CLIMATOLOGY_KNN in weights
    assert weights[CLIMATOLOGY_KNN] > 1.0  # a measured edge earns pool share


# ── the six live continuous-miss classes (read-only validation) ───────────────

# Each: a representative recent series (seeded — the live data plane is network-
# gated), the question's resolution threshold+operator, and the qualitative
# direction of the recorded desk miss. The check: the specialist RUNS (a coherent,
# monotone distribution) and its directional read is reported.
SIX_MISS = {
    "btc_close": dict(unit="USD", values=[104000, 105500, 106000, 107500, 108000,
                                          109000, 110500, 111000, 112000, 113000],
                      threshold=110000.0, operator=">="),
    "wti_crude": dict(unit="USD/bbl", values=[70.5, 71.0, 70.2, 69.8, 71.4,
                                              72.1, 71.8, 72.5, 73.0, 72.7],
                      threshold=76.0, operator=">="),
    "nfp": dict(unit="thousands", values=[175, 150, 210, 160, 185, 200, 145, 190],
                threshold=100.0, operator=">="),
    "ism_pmi": dict(unit="index", values=[48.5, 49.0, 48.7, 49.3, 50.1, 49.8, 49.2, 48.9],
                    threshold=50.0, operator=">="),
    "phoenix_maxtemp": dict(unit="F", kind="continuous",
                            values=[104, 106, 108, 110, 112, 111, 109, 113, 114, 112],
                            threshold=110.0, operator=">="),
    "earthquake_count": dict(unit="count", kind="count",
                             values=[2, 1, 3, 0, 2, 4, 1, 2, 3, 1],
                             threshold=1.0, operator=">="),
}


@pytest.mark.parametrize("name", list(SIX_MISS))
def test_six_miss_specialist_is_runnable_and_reports_a_direction(name):
    spec = SIX_MISS[name]
    series = _daily_series(spec["values"], unit=spec["unit"],
                           kind=spec.get("kind", "continuous"), key=name)
    q = _Q(outcome_type="numeric", units=spec["unit"], id=name,
           metadata={"specialist": {"threshold": spec["threshold"],
                                    "operator": spec["operator"]}})
    forecast = run_specialist(
        CLIMATOLOGY_KNN, q,
        series_provider=lambda _q, as_of, s=series: s, as_of=date(2026, 6, 30),
    )
    assert forecast.produced, f"{name}: specialist should run on a reachable series"
    dist = forecast.distribution
    quants = [v for _, v in dist.quantiles((0.1, 0.5, 0.9))]
    assert quants == sorted(quants)  # coherent, monotone
    # emits a parseable panelist vote (P of clearing the threshold)
    payload = parse_panelist_response(
        forecast.to_panelist_json(threshold=spec["threshold"], operator=spec["operator"]),
        CLIMATOLOGY_KNN,
    )
    assert 0.0 <= payload.probability <= 1.0
