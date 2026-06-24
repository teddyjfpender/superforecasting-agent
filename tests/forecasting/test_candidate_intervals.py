"""Per-candidate vote-share intervals: the dashboard normalizes the snapshot's
candidate_share_intervals_pp metadata into {candidate: {lo, mid, hi}} (p05/median/p95)
so the TUI can draw an error bar per candidate. Absent/malformed -> None (no bars)."""

from __future__ import annotations

from forecasting.dashboard import _candidate_intervals


class _Snap:
    def __init__(self, metadata):
        self.metadata = metadata


def test_normalizes_percentiles_to_lo_mid_hi():
    s = _Snap({"candidate_share_intervals_pp": {
        "Pappas": {"p05": 50, "median": 70, "p95": 85},
        "Jarvis": {"p05": 2, "median": 6, "p95": 14},
    }})
    assert _candidate_intervals(s) == {
        "Pappas": {"lo": 50.0, "mid": 70.0, "hi": 85.0},
        "Jarvis": {"lo": 2.0, "mid": 6.0, "hi": 14.0},
    }


def test_median_optional_p50_fallback():
    s = _Snap({"candidate_share_intervals_pp": {"A": {"p05": 40, "p50": 50, "p95": 60}}})
    assert _candidate_intervals(s)["A"] == {"lo": 40.0, "mid": 50.0, "hi": 60.0}


def test_none_when_absent_or_malformed():
    assert _candidate_intervals(_Snap(None)) is None
    assert _candidate_intervals(_Snap({})) is None
    assert _candidate_intervals(_Snap({"candidate_share_intervals_pp": "nope"})) is None
    # inverted lo > hi is dropped -> no usable entries -> None
    assert _candidate_intervals(_Snap({"candidate_share_intervals_pp": {"A": {"p05": 60, "p95": 40}}})) is None
    # missing hi -> dropped
    assert _candidate_intervals(_Snap({"candidate_share_intervals_pp": {"A": {"p05": 40}}})) is None
