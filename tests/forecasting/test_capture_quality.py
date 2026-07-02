"""Capture-time quality + near-dup collapse (S6.4 / S6.5)."""

from __future__ import annotations

import pytest

from forecasting.ledger import ForecastLedger
from forecasting.source_search import (
    WatchedTextSourceCandidate,
    capture_watched_text_candidates,
    collapse_near_duplicates,
    source_type_reliability_prior,
)


@pytest.fixture
def ledger(tmp_path):
    return ForecastLedger(db_path=str(tmp_path / "cap.db"))


def _question(ledger):
    return ledger.create_question(
        title="Will the policy rate be cut in Q3?",
        resolution_criteria="Resolves yes if the official rate is cut before Q3 ends; otherwise no.",
    )


def _candidate(title, url, *, source="rss:https://a.example/feed", stype="rss", published="2026-06-30T00:00:00Z", score=10, entry=None):
    return WatchedTextSourceCandidate(
        watched_source_id="w1",
        source_type=stype,
        source=source,
        source_label="A",
        title=title,
        summary="summary",
        url=url,
        published_at=published,
        entry_id=entry,
        relevance_score=score,
    )


# ── reliability prior table (S6.4) ────────────────────────────────────────────


def test_reliability_prior_tiers():
    assert source_type_reliability_prior("bls") >= 0.85
    assert source_type_reliability_prior("fred") >= 0.85
    assert source_type_reliability_prior("federalregister") >= 0.85
    assert source_type_reliability_prior("courtlistener") >= 0.85
    # low-trust firehoses
    assert source_type_reliability_prior("gdelt") <= 0.4
    assert source_type_reliability_prior("reddit") <= 0.4
    assert source_type_reliability_prior("hackernews") <= 0.4
    # decoration stripped
    assert source_type_reliability_prior("adapter:fred") == source_type_reliability_prior("fred")
    assert source_type_reliability_prior("rss:https://x/feed") == source_type_reliability_prior("rss")
    # unknown -> neutral default
    assert source_type_reliability_prior("mystery") == 0.5


# ── capture-time quality fields (S6.4) ─────────────────────────────────────────


def test_capture_stamps_quality_fields(ledger, monkeypatch):
    q = _question(ledger)
    now = "2026-07-14T00:00:00Z"  # 14 days after published -> recency weight ~0.5
    import forecasting.source_search as ss

    monkeypatch.setattr(ss, "utc_now_iso", lambda: now)
    captured = capture_watched_text_candidates(
        ledger,
        q.id,
        [_candidate("Rate cut odds rise on soft CPI", "https://a.example/1", stype="fred")],
    )
    assert len(captured) == 1
    ev = captured[0].evidence
    # reliability prior attached to the row
    assert ev.reliability_rating == source_type_reliability_prior("fred")
    quality = ev.metadata["capture_quality"]
    assert quality["reliability_prior"] == source_type_reliability_prior("fred")
    assert quality["independent"] is True
    assert 0.45 <= quality["recency_weight"] <= 0.55  # ~half-life at 14 days
    assert quality["recency_halflife_days"] == 14.0


def test_capture_independence_flag_same_feed_in_batch(ledger):
    q = _question(ledger)
    captured = capture_watched_text_candidates(
        ledger,
        q.id,
        [
            _candidate("Story one about the rate", "https://a.example/1"),
            _candidate("A different rate story entirely", "https://a.example/2"),
        ],
    )
    # both from the same feed signature -> neither is an independent draw
    for cap in captured:
        assert cap.evidence.metadata["capture_quality"]["independent"] is False
        assert "batch" in " ".join(cap.evidence.metadata["capture_quality"]["independence_reasons"])


def test_capture_independence_flag_overlaps_existing(ledger):
    q = _question(ledger)
    capture_watched_text_candidates(ledger, q.id, [_candidate("First story", "https://a.example/1")])
    # a second capture from the SAME feed signature is now non-independent
    captured = capture_watched_text_candidates(
        ledger, q.id, [_candidate("Second story new", "https://a.example/2")]
    )
    quality = captured[0].evidence.metadata["capture_quality"]
    assert quality["independent"] is False
    assert any("already on file" in r for r in quality["independence_reasons"])


# ── near-dup collapse (S6.5) ───────────────────────────────────────────────────


def test_collapse_near_duplicates_folds_reworded_headlines():
    candidates = [
        _candidate("Fed pauses rate hikes amid cooling inflation", "https://a.example/1", source="rss:https://a/feed", score=12),
        _candidate("Fed pauses rate hikes", "https://b.example/2", source="rss:https://b/feed", score=8),
        _candidate("ECB signals further tightening ahead", "https://c.example/3", source="rss:https://c/feed", score=6),
    ]
    survivors = collapse_near_duplicates(candidates)
    # the two Fed headlines fold to one survivor; the ECB story stands alone
    assert len(survivors) == 2
    fed = [s for s in survivors if "Fed" in s.title][0]
    assert len(fed.folded_siblings) == 1
    assert fed.folded_siblings[0]["url"] == "https://b.example/2"
    # highest-relevance is the survivor
    assert fed.title == "Fed pauses rate hikes amid cooling inflation"


def test_collapse_no_false_positive_on_distinct_titles():
    candidates = [
        _candidate("Unemployment ticks up in June", "https://a.example/1"),
        _candidate("Housing starts fall sharply", "https://b.example/2"),
    ]
    survivors = collapse_near_duplicates(candidates)
    assert len(survivors) == 2
    assert all(not s.folded_siblings for s in survivors)


def test_capture_marks_folded_survivor_non_independent(ledger):
    q = _question(ledger)
    survivor = _candidate("Fed pauses rate hikes amid inflation", "https://a.example/1")
    from dataclasses import replace

    survivor = replace(
        survivor,
        folded_siblings=[{"title": "Fed pauses rate hikes", "url": "https://b.example/2", "source": "rss:https://b/feed", "source_type": "rss"}],
    )
    captured = capture_watched_text_candidates(ledger, q.id, [survivor])
    quality = captured[0].evidence.metadata["capture_quality"]
    assert quality["independent"] is False
    assert quality["folded_siblings"]
    assert any("near-duplicate" in r for r in quality["independence_reasons"])
