"""Import smoke test for the forecasting.pm package facade."""

from __future__ import annotations


def test_facade_exports_are_importable():
    import forecasting.pm as pm

    for name in (
        "PMService",
        "PolymarketClient",
        "KalshiClient",
        "PMEvent",
        "PMMarket",
        "PMOrderBook",
        "PMDistribution",
        "build_distribution",
        "devig_yes_mids",
        "sign_kalshi_message",
        "kalshi_auth_headers",
        "KalshiSignerUnavailable",
    ):
        assert hasattr(pm, name), name

    svc = pm.PMService()  # constructs default clients without touching network
    assert svc is not None
