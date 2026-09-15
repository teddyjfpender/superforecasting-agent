"""Replay captured public responses through the same adapters as the data desk."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from forecasting.marketdata.catalog import load_catalog
from forecasting.marketdata.model import SeriesRef
from forecasting.marketdata.providers.bcb import BcbProvider
from forecasting.marketdata.providers.country_indicators import WorldBankProvider
from forecasting.marketdata.providers.europe import EcbProvider, EurostatProvider
from forecasting.marketdata.providers.regional_statistics import (
    IbgeProvider,
    SingStatProvider,
)
from forecasting.marketdata.providers.sdmx import SdmxProvider
from forecasting.marketdata.providers.weather import OpenMeteoProvider

FIXTURES = Path(__file__).parents[1] / "fixtures" / "data_desk"


@pytest.mark.parametrize(
    "provider",
    [
        "worldbank",
        "bcb",
        "eurostat",
        "ecb",
        "abs",
        "bis",
        "oecd",
        "singstat",
        "ibge",
        "openmeteo",
    ],
)
def test_captured_source_response_retains_meaning_and_history(provider):
    fixture = json.loads((FIXTURES / (provider + ".json")).read_text())
    entry = next(
        item for item in load_catalog().series if item.id == fixture["series_id"]
    )
    captured = datetime.fromisoformat(fixture["captured_at"])
    requests = iter(fixture["requests"])

    def read(url, **kwargs):
        request = next(requests)
        assert url == request["url"]
        return request["body"]

    if provider in {"abs", "bis", "oecd"}:
        adapter = SdmxProvider(provider, get_text=read)
    elif provider == "bcb":
        adapter = BcbProvider(get_json=read, clock=lambda: captured.date())
    elif provider == "openmeteo":
        adapter = OpenMeteoProvider(get_json=read, clock=lambda: captured)
    elif provider == "ecb":
        adapter = EcbProvider(get_text=read)
    else:
        adapter = {
            "worldbank": WorldBankProvider,
            "eurostat": EurostatProvider,
            "singstat": SingStatProvider,
            "ibge": IbgeProvider,
        }[provider](get_json=read)
    quote = adapter.fetch([
        SeriesRef(provider=provider, symbol=entry.symbol, catalog_id=entry.id)
    ])[0]
    assert quote.value == pytest.approx(fixture["expected_value"])
    assert len(quote.dated_history) == fixture["expected_points"]
    assert all(point.published_at is None for point in quote.dated_history)
    assert quote.published_at is None
    assert list(requests) == []
