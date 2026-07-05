"""Question curation — contested/horizon/liquidity filters, criteria drafting, purity."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from forecasting.curation import (
    CurationFilters,
    curate_market_candidates,
    draft_resolution_criteria,
)
from forecasting.pm.model import PMDistribution, PMEvent, PMOutcome

NOW = "2026-07-05T00:00:00+00:00"


def _iso(days_from_now: float) -> str:
    return (datetime(2026, 7, 5, tzinfo=timezone.utc) + timedelta(days=days_from_now)).isoformat()


def _binary_pair(
    *,
    prob: float,
    days: float,
    volume: float = 5000.0,
    liquid: bool = True,
    title: str = "Will the contested binary event resolve yes by its deadline?",
    event_id: str = "ev1",
) -> tuple[PMEvent, PMDistribution]:
    outcome = PMOutcome(
        label="Yes", prob=prob, raw_prob=prob, market_id="mkt1", volume=volume, liquid=liquid
    )
    dist = PMDistribution(
        venue="polymarket",
        event_id=event_id,
        title=title,
        outcomes=(outcome,),
        binary=True,
        total_volume=volume,
        close_time=_iso(days),
        url="https://polymarket.com/event/x",
    )
    event = PMEvent(venue="polymarket", event_id=event_id, title=title, close_time=_iso(days))
    return event, dist


def _multi_outcome_pair() -> tuple[PMEvent, PMDistribution]:
    outcomes = (
        PMOutcome(label="A", prob=0.4, raw_prob=0.4, market_id="a", liquid=True),
        PMOutcome(label="B", prob=0.6, raw_prob=0.6, market_id="b", liquid=True),
    )
    dist = PMDistribution(
        venue="kalshi", event_id="ev2", title="Which candidate wins?", outcomes=outcomes, binary=False,
        close_time=_iso(10),
    )
    return PMEvent(venue="kalshi", event_id="ev2", title="Which candidate wins?", close_time=_iso(10)), dist


# ── filters ──────────────────────────────────────────────────────────────────


def test_contested_binary_passes():
    report = curate_market_candidates([_binary_pair(prob=0.55, days=20)], now=NOW)
    assert report.screened == 1
    assert len(report.candidates) == 1
    assert report.candidates[0].market_probability == 0.55


def test_near_certain_rejected_as_not_contested():
    report = curate_market_candidates(
        [_binary_pair(prob=0.97, days=20), _binary_pair(prob=0.02, days=20, event_id="ev_low")], now=NOW
    )
    assert report.candidates == []
    assert report.rejected.get("not_contested") == 2


def test_long_horizon_rejected():
    report = curate_market_candidates([_binary_pair(prob=0.5, days=120)], now=NOW)
    assert report.candidates == []
    assert report.rejected.get("horizon_too_long") == 1


def test_already_closed_rejected():
    report = curate_market_candidates([_binary_pair(prob=0.5, days=-3)], now=NOW)
    assert report.candidates == []
    assert report.rejected.get("already_closed") == 1


def test_illiquid_rejected():
    report = curate_market_candidates(
        [_binary_pair(prob=0.5, days=20, volume=10.0)], now=NOW, filters=CurationFilters(min_volume=1000)
    )
    assert report.candidates == []
    assert report.rejected.get("illiquid") == 1


def test_no_live_quote_rejected():
    report = curate_market_candidates([_binary_pair(prob=0.5, days=20, liquid=False)], now=NOW)
    assert report.candidates == []
    assert report.rejected.get("no_live_quote") == 1


def test_multi_outcome_outcomes_mined_as_binaries():
    # Each contested, liquid outcome of a multi-outcome event is its own yes/no.
    report = curate_market_candidates([_multi_outcome_pair()], now=NOW)
    assert len(report.candidates) == 2
    titles = sorted(c.title for c in report.candidates)
    assert titles == [
        "In Which candidate wins, will the outcome be A?",
        "In Which candidate wins, will the outcome be B?",
    ]


def test_multi_outcome_rejected_when_outcome_mining_disabled():
    report = curate_market_candidates(
        [_multi_outcome_pair()], now=NOW, filters=CurationFilters(include_event_outcomes=False)
    )
    assert report.candidates == []
    assert report.rejected.get("not_binary") == 1


def test_candidates_sorted_most_contested_first():
    report = curate_market_candidates(
        [
            _binary_pair(prob=0.8, days=10, event_id="e80"),
            _binary_pair(prob=0.52, days=10, event_id="e52"),
            _binary_pair(prob=0.3, days=10, event_id="e30"),
        ],
        now=NOW,
    )
    probs = [c.market_probability for c in report.candidates]
    assert probs[0] == 0.52  # closest to 0.5 ranks first


# ── criteria drafting ────────────────────────────────────────────────────────


def test_draft_criteria_is_scoreable_and_cites_market():
    criteria = draft_resolution_criteria(
        title="Will inflation exceed 3% in August?",
        venue="kalshi",
        url="https://kalshi.com/x",
        close_time="2026-08-30T00:00:00+00:00",
        probability=0.42,
    )
    assert criteria.startswith("Resolves YES")
    assert "kalshi" in criteria
    assert "42 percent" in criteria
    assert "—" not in criteria  # desk style: no em-dashes
    assert len(criteria.split()) >= 5


def test_candidate_carries_drafted_criteria_and_metadata():
    report = curate_market_candidates([_binary_pair(prob=0.6, days=15)], now=NOW)
    candidate = report.candidates[0]
    assert candidate.resolution_criteria.startswith("Resolves YES")
    assert candidate.venue == "polymarket"
    assert candidate.market_id == "mkt1"
    assert candidate.horizon_days is not None and 14 < candidate.horizon_days < 16
    d = candidate.to_dict()
    assert d["market_probability"] == 0.6 and d["url"] == "https://polymarket.com/event/x"


# ── purity ───────────────────────────────────────────────────────────────────


def test_curation_is_pure_no_writes(tmp_path):
    """The pure module touches no ledger: run it, then confirm an untouched db."""
    from forecasting.ledger import ForecastLedger

    ledger = ForecastLedger(tmp_path / "pure.db")
    before = len(ledger.list_questions())
    curate_market_candidates([_binary_pair(prob=0.55, days=20)], now=NOW)
    assert len(ledger.list_questions()) == before == 0
