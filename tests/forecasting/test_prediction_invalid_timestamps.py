"""Optional source timestamps must not abort prediction imports."""
import pytest
from forecasting import source_adapters


@pytest.fixture(params=["metaculus", "kalshi", "manifold", "polymarket"])
def market_loader(request, monkeypatch):
    venue = request.param
    def load(value):
        if venue == "metaculus":
            payload = {"title": "Fixture", "type": "binary", "close_time": value}
            loader = source_adapters.load_metaculus_question
        elif venue == "kalshi":
            payload = {"title": "Fixture", "ticker": "FIXTURE", "close_time": value}
            loader = source_adapters.load_kalshi_market
        elif venue == "manifold":
            payload = {"question": "Fixture", "closeTime": value}
            loader = source_adapters.load_manifold_market
        else:
            payload = {"question": "Fixture", "endDate": value}
            loader = source_adapters.load_polymarket_market
        monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *args, **kwargs: payload)
        return loader("123")
    return load


@pytest.mark.parametrize("value", [1e100, -1e100, float("inf"), float("-inf")])
def test_unrepresentable_time_keeps_import(market_loader, value):
    assert market_loader(value).close_time is None


def test_valid_millisecond_time_keeps_import(market_loader):
    assert market_loader(1700000000000).close_time == "2023-11-14T22:13:20Z"
