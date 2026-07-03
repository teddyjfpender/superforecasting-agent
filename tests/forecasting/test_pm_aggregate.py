"""De-vig + distribution synthesis tests (hand-checkable + fixtures)."""

from __future__ import annotations

import math

from forecasting.pm.aggregate import build_distribution, devig_yes_mids
from forecasting.pm.model import PMEvent, PMMarket
from forecasting.pm import kalshi as kal
from forecasting.pm import polymarket as poly
from tests.forecasting.pm_helpers import load_fixture


def _mkt(label, bid=None, ask=None, last=None, volume=None):
    return PMMarket(
        venue="x", market_id=label, label=label, question=label,
        yes_bid=bid, yes_ask=ask, last_price=last, volume=volume,
    )


def test_devig_removes_overround_and_sums_to_one():
    # Three outcomes whose mids sum to 1.20 (20 pts of vig).
    probs, overround = devig_yes_mids({"A": 0.6, "B": 0.4, "C": 0.2})
    assert math.isclose(sum(probs.values()), 1.0, abs_tol=1e-9)
    assert math.isclose(overround, 0.2, abs_tol=1e-9)
    assert math.isclose(probs["A"], 0.5, abs_tol=1e-9)  # 0.6/1.2
    assert math.isclose(probs["B"], 1 / 3, abs_tol=1e-9)


def test_devig_all_zero_is_safe():
    probs, overround = devig_yes_mids({"A": 0.0, "B": 0.0})
    assert probs == {"A": 0.0, "B": 0.0} and overround == 0.0


def test_binary_event_passthrough_no_devig():
    ev = PMEvent(venue="x", event_id="e", title="t", markets=(_mkt("Yes", bid=0.11, ask=0.13),))
    dist = build_distribution(ev)
    assert dist.binary is True and len(dist.outcomes) == 1
    assert dist.overround == 0.0
    assert math.isclose(dist.outcomes[0].prob, 0.12, abs_tol=1e-9)  # raw mid, untouched
    assert dist.outcomes[0].prob == dist.outcomes[0].raw_prob


def test_categorical_sum_to_one_and_ordered_desc():
    ev = PMEvent(
        venue="x", event_id="e", title="t",
        markets=(_mkt("A", 0.35, 0.37), _mkt("B", 0.55, 0.57), _mkt("C", 0.10, 0.12)),
    )
    dist = build_distribution(ev)
    assert not dist.binary
    assert math.isclose(sum(o.prob for o in dist.outcomes), 1.0, abs_tol=1e-9)
    probs = [o.prob for o in dist.outcomes]
    assert probs == sorted(probs, reverse=True)
    assert dist.outcomes[0].label == "B"  # highest mid
    # raw vs devig honesty: raw_prob is the pre-normalisation mid
    b = dist.outcomes[0]
    assert b.raw_prob > b.prob or math.isclose(b.raw_prob, 0.56, abs_tol=1e-9)


def test_zero_liquidity_outcomes_ranked_last_with_zero_prob():
    ev = PMEvent(
        venue="x", event_id="e", title="t",
        # book sum ~1.04 (inside the sane band) + mutually exclusive → normalises.
        markets=(_mkt("A", 0.60, 0.62), _mkt("Dead"), _mkt("B", 0.42, 0.44)),
    )
    dist = build_distribution(ev)
    assert dist.normalized is True
    assert dist.outcomes[-1].label == "Dead"
    assert dist.outcomes[-1].prob == 0.0 and dist.outcomes[-1].liquid is False
    # de-vig denominator excludes the dead outcome → live ones still sum to 1
    assert math.isclose(sum(o.prob for o in dist.outcomes), 1.0, abs_tol=1e-9)
    assert any("no live quote" in n for n in dist.notes)


def test_fixture_events_sum_to_one():
    for name, parser in (
        ("polymarket_event_categorical.json", poly.parse_event),
        ("kalshi_event_categorical.json", kal.parse_event),
    ):
        dist = build_distribution(parser(load_fixture(name)))
        live = [o for o in dist.outcomes if o.liquid]
        if dist.normalized:
            assert math.isclose(sum(o.prob for o in live), 1.0, abs_tol=1e-6)
        else:
            # Normalisation refused (no partition guarantee or the book sum fell
            # outside the sane band — the trimmed categorical fixture sums to
            # ~0.80): probs are the RAW mids and the honest note says so.
            for o in live:
                assert math.isclose(o.prob, o.raw_prob, abs_tol=1e-9)
            assert any("raw prices shown" in n for n in dist.notes)
        assert dist.headline["top_label"] == dist.outcomes[0].label


def test_normalization_is_earned_not_assumed():
    """The epistemic contract: sum-to-1 only over a guaranteed, sane partition."""
    open_ended = PMEvent(
        venue="x", event_id="e1", title="open", mutually_exclusive=False,
        markets=(_mkt("A", 0.50, 0.52), _mkt("B", 0.30, 0.32)),
    )
    d1 = build_distribution(open_ended)
    assert d1.normalized is False
    assert math.isclose(d1.outcomes[0].prob, d1.outcomes[0].raw_prob, abs_tol=1e-9)
    assert any("not a guaranteed partition" in n for n in d1.notes)

    truncated = PMEvent(
        venue="x", event_id="e2", title="trunc", mutually_exclusive=True,
        markets=(_mkt("A", 0.40, 0.42), _mkt("B", 0.20, 0.22)),
    )
    d2 = build_distribution(truncated)
    assert d2.normalized is False
    assert any("looks incomplete" in n for n in d2.notes)

    sane = PMEvent(
        venue="x", event_id="e3", title="sane", mutually_exclusive=True,
        markets=(_mkt("A", 0.60, 0.62), _mkt("B", 0.44, 0.46)),
    )
    d3 = build_distribution(sane)
    assert d3.normalized is True
    assert math.isclose(sum(o.prob for o in d3.outcomes), 1.0, abs_tol=1e-9)
