"""History normalisation + downsampling tests."""

from __future__ import annotations

from forecasting.pm import history as hist
from forecasting.pm.model import PMHistoryPoint
from tests.forecasting.pm_helpers import load_fixture


def test_polymarket_history_normalises():
    points = hist.from_polymarket(load_fixture("polymarket_prices_history.json"))
    assert points and all(isinstance(p, PMHistoryPoint) for p in points)
    assert all(0.0 <= p.p <= 1.0 for p in points)


def test_kalshi_candlesticks_normalise():
    points = hist.from_kalshi(load_fixture("kalshi_candlesticks.json"))
    assert points and all(0.0 <= p.p <= 1.0 for p in points)


def test_downsample_preserves_endpoints_and_bounds_count():
    src = [PMHistoryPoint(ts=i, p=i / 1000.0) for i in range(1000)]
    ds = hist.downsample(src, max_points=50)
    assert len(ds) <= 51  # stride sampling, endpoint appended if needed
    assert ds[0] is src[0] and ds[-1] is src[-1]
    assert all(ds[i].ts < ds[i + 1].ts for i in range(len(ds) - 1))


def test_downsample_noop_when_small():
    src = [PMHistoryPoint(ts=i, p=0.5) for i in range(10)]
    assert hist.downsample(src, max_points=200) == src


def test_downsample_single_point_target():
    src = [PMHistoryPoint(ts=i, p=0.5) for i in range(10)]
    assert hist.downsample(src, max_points=1) == [src[-1]]
