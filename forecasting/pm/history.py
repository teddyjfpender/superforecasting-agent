"""Normalise both venues' price history to ``[{ts, p}]`` + downsample.

Polymarket CLOB ``prices-history`` and Kalshi ``candlesticks`` land in the same
:class:`PMHistoryPoint` shape (delegated to the venue parsers). Downsampling
keeps sparklines cheap without distorting the endpoints.
"""

from __future__ import annotations

from forecasting.pm import kalshi as _kalshi
from forecasting.pm import polymarket as _polymarket
from forecasting.pm.model import PMHistoryPoint


def from_polymarket(raw: object) -> list[PMHistoryPoint]:
    return _polymarket.parse_prices_history(raw)


def from_kalshi(raw: object) -> list[PMHistoryPoint]:
    return _kalshi.parse_candlesticks(raw)


def downsample(points: list[PMHistoryPoint], max_points: int = 200) -> list[PMHistoryPoint]:
    """Uniform-stride downsample, always preserving the first and last point."""
    n = len(points)
    if max_points <= 0 or n <= max_points:
        return list(points)
    if max_points == 1:
        return [points[-1]]
    stride = (n - 1) / (max_points - 1)
    picked: list[PMHistoryPoint] = []
    seen: set[int] = set()
    for i in range(max_points):
        idx = round(i * stride)
        if idx >= n:
            idx = n - 1
        if idx not in seen:
            seen.add(idx)
            picked.append(points[idx])
    if picked and picked[-1] is not points[-1]:
        picked.append(points[-1])
    return picked


def to_dicts(points: list[PMHistoryPoint]) -> list[dict]:
    return [p.to_dict() for p in points]


__all__ = ["from_polymarket", "from_kalshi", "downsample", "to_dicts"]
