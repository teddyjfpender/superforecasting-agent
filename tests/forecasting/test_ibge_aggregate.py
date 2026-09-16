"""The official aggregate endpoint retains SIDRA's exact measurement semantics."""

import copy
import json
from pathlib import Path

import pytest

from forecasting.marketdata.catalog import load_catalog
from forecasting.marketdata.model import SeriesRef
from forecasting.marketdata.provider import ProviderFailure
from forecasting.marketdata.providers.regional_statistics import parse_ibge_aggregate

FIXTURE = Path(__file__).parents[1] / "fixtures/data_desk/ibge.json"


def parse(payload):
    entry = next(e for e in load_catalog().series if e.id == "ibge:1737/63")
    return parse_ibge_aggregate(
        payload,
        SeriesRef(provider="ibge", symbol=entry.symbol, catalog_id=entry.id),
        entry.dimensions,
    )


def body():
    return json.loads(FIXTURE.read_text())["requests"][0]["body"]


def test_exact_monthly_ipca_and_periods():
    quote = parse(body())
    assert quote.value == -0.32
    assert len(quote.dated_history) == 24
    assert quote.dated_history[-1].period_start == "2026-08-01"
    assert quote.dated_history[-1].period_end == "2026-08-31"
    assert quote.published_at is None


@pytest.mark.parametrize(
    "path,value",
    [
        (["id"], "2266"),
        (["variavel"], "IPCA - Variação acumulada no ano"),
        (["unidade"], "Index"),
        (["resultados", 0, "classificacoes"], [{"id": "315"}]),
        (["resultados", 0, "series", 0, "localidade", "id"], "33"),
        (["resultados", 0, "series", 0, "localidade", "nivel", "id"], "N3"),
        (["resultados", 0, "series", 0, "serie"], {"202613": "1"}),
        (["resultados", 0, "series", 0, "serie"], {}),
    ],
)
def test_plausible_wrong_measurements_rejected(path, value):
    payload = copy.deepcopy(body())
    target = payload[0]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises((ProviderFailure, ValueError)):
        parse(payload)


def test_missing_observation_is_not_zero():
    payload = body()
    payload[0]["resultados"][0]["series"][0]["serie"]["202608"] = "..."
    quote = parse(payload)
    assert quote.dated_history[-1].value is None
