"""Measurement identity, dated history and safe failures at the data-desk boundary."""

from copy import deepcopy
from datetime import date

import pytest

from forecasting.marketdata.catalog import load_catalog
from forecasting.marketdata.model import DatedValue, SeriesRef
from forecasting.marketdata.parsing import observation_quote
from forecasting.marketdata.provider import ProviderFailure
from forecasting.marketdata.providers.bcb import parse_bcb
from forecasting.marketdata.providers.europe import parse_ecb, parse_eurostat
from forecasting.marketdata.providers.frankfurter import parse_frankfurter
from forecasting.marketdata.providers.regional_statistics import (
    parse_ibge,
    parse_singstat,
)
from forecasting.marketdata.providers.sdmx import parse_sdmx_csv
from forecasting.marketdata.providers.yahoo import parse_yahoo


def binding(provider):
    entry = next(item for item in load_catalog().series if item.provider == provider)
    return entry, SeriesRef(
        provider=provider, symbol=entry.symbol, catalog_id=entry.id, unit=entry.unit
    )


@pytest.mark.parametrize(
    "start,end,published",
    [
        ("2026-02-30", "2026-02-30", None),
        ("2026-02-02", "2026-02-01", None),
        ("2026-02-01T12:00:00", "2026-02-01T13:00:00", None),
        ("2026-02-01", "2026-02-01", "2026-02-02"),
        ("2026-02-01", "2026-02-01T00:00:00Z", None),
    ],
)
def test_ambiguous_periods_and_publication_times_are_rejected(start, end, published):
    with pytest.raises(ValueError):
        DatedValue(period_start=start, period_end=end, published_at=published, value=1)


@pytest.mark.parametrize("value", [True, float("nan"), float("inf")])
def test_boolean_and_nonfinite_measurements_are_rejected(value):
    with pytest.raises(ValueError):
        DatedValue(period_start="2026-01-01", period_end="2026-01-01", value=value)


def test_conflicting_revisions_require_an_explicit_source_policy():
    ref = SeriesRef(provider="example", symbol="example")
    first = DatedValue(period_start="2026-01-01", period_end="2026-01-31", value=1)
    assert len(observation_quote(ref, [first, first]).dated_history) == 1
    with pytest.raises(ProviderFailure, match="conflicting"):
        observation_quote(ref, [first, first.model_copy(update={"value": 2})])


def test_bcb_future_effective_rate_is_not_a_current_observation():
    _, ref = binding("bcb")
    quote = parse_bcb(
        [
            {"data": "14/09/2026", "valor": "14.0"},
            {"data": "16/09/2026", "valor": "13.5"},
        ],
        ref,
        as_of=date(2026, 9, 14),
    )
    assert quote.value == 14
    assert [point.period_start for point in quote.dated_history] == ["2026-09-14"]
    assert quote.published_at is None


def test_fx_missing_latest_currency_does_not_inherit_another_currencys_date():
    ref = SeriesRef(provider="frankfurter", symbol="EUR")
    quote = parse_frankfurter(
        {
            "base": "USD",
            "rates": {"2026-09-10": {"EUR": 0.86}, "2026-09-11": {"JPY": 146}},
        },
        [ref],
    )[0]
    assert quote.value == 0.86
    assert quote.dated_history[0].period_start == "2026-09-10"
    assert quote.asOf == 1788998400000


def test_yahoo_timestamps_stay_paired_when_a_close_is_missing():
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {"regularMarketPrice": 3},
                    "timestamp": [1788998400, 1789084800, 1789171200],
                    "indicators": {"quote": [{"close": [1, None, 3]}]},
                }
            ]
        }
    }
    quote = parse_yahoo(payload, SeriesRef(provider="yahoo", symbol="EXAMPLE"))
    assert [(p.period_start[:10], p.value) for p in quote.dated_history] == [
        ("2026-09-10", 1),
        ("2026-09-12", 3),
    ]


@pytest.mark.parametrize("provider", ["abs", "bis", "oecd"])
def test_sdmx_pins_every_measurement_dimension_including_rebasing(provider):
    entry, ref = binding(provider)
    dimensions = {
        key: value for key, value in entry.dimensions.items() if not key.startswith("_")
    }
    keys = [*dimensions, "TIME_PERIOD", "OBS_VALUE"]

    def csv(values):
        import csv, io

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=keys)
        writer.writeheader()
        writer.writerow({**values, "TIME_PERIOD": "2026-07", "OBS_VALUE": "103.07"})
        return output.getvalue()

    result = parse_sdmx_csv(csv(dimensions), ref, entry.dimensions)
    assert result.dated_history[0].period_end == "2026-07-31"
    assert result.published_at is None
    for key in dimensions:
        with pytest.raises(ProviderFailure, match="mismatch"):
            parse_sdmx_csv(
                csv({**dimensions, key: "plausible-but-wrong"}), ref, entry.dimensions
            )


def test_ecb_rejects_wrong_currency_and_multiplier():
    entry, ref = binding("ecb")
    header = "KEY,UNIT,UNIT_MULT,TIME_PERIOD,OBS_VALUE\n"
    row = f"{entry.dimensions['flow']}.{ref.symbol},{entry.dimensions['unit']},{entry.dimensions['unit_mult']},2026-09-10,1.15\n"
    assert parse_ecb(header + row, ref, entry.dimensions).value == 1.15
    with pytest.raises(ProviderFailure):
        parse_ecb(header + row.replace(",0,", ",3,"), ref, entry.dimensions)
    with pytest.raises(ProviderFailure):
        parse_ecb(
            header + row.replace(ref.symbol, "D.JPY.EUR.SP00.A"), ref, entry.dimensions
        )


def test_eurostat_requires_all_bound_dimensions_and_valid_flat_indices():
    entry, ref = binding("eurostat")
    dimensions = {
        key: value for key, value in entry.dimensions.items() if key != "dataset"
    }
    ids = [*dimensions, "time"]
    payload = {
        "class": "dataset",
        "id": ids,
        "size": [1] * len(dimensions) + [2],
        "dimension": {
            **{
                key: {"category": {"index": {value: 0}}}
                for key, value in dimensions.items()
            },
            "time": {"category": {"index": {"2026-07": 0, "2026-08": 1}}},
        },
        "value": {"0": 2.1, "1": 2.0},
        "updated": "2026-09-10T12:00:00Z",
    }
    quote = parse_eurostat(payload, ref, dimensions)
    assert quote.value == 2 and quote.published_at is None
    for key in dimensions:
        bad = deepcopy(payload)
        bad["id"].remove(key)
        bad["size"].pop(0)
        with pytest.raises(ProviderFailure):
            parse_eurostat(bad, ref, dimensions)
    bad = deepcopy(payload)
    bad["dimension"]["time"]["category"]["index"]["2026-08"] = -1
    with pytest.raises(ProviderFailure):
        parse_eurostat(bad, ref, dimensions)


def test_singstat_table_update_is_not_observation_publication():
    entry, ref = binding("singstat")
    d = entry.dimensions
    data = {key: d[key] for key in ("id", "title", "frequency")}
    data.update(
        dataLastUpdated="24/08/2026",
        dateGenerated="15/09/2026",
        row=[
            {
                **{key: d[key] for key in ("seriesNo", "rowText", "uoM")},
                "columns": [{"key": "2026 Jul", "value": "102.696"}],
            }
        ],
    )
    result = parse_singstat({"Data": data}, ref, d)
    assert result.published_at is None and result.dated_history[0].published_at is None
    bad = deepcopy(data)
    bad["row"][0]["uoM"] = "Percent"
    with pytest.raises(ProviderFailure):
        parse_singstat({"Data": bad}, ref, d)


def test_ibge_does_not_accept_a_different_territory_or_unit():
    entry, ref = binding("ibge")
    d = entry.dimensions
    row = {key: value for key, value in d.items() if key != "_table"}
    row.update(D3C="202608", V="-0.32")
    assert parse_ibge([{}, row], ref, d).value == -0.32
    for key in ("D1C", "MC"):
        with pytest.raises(ProviderFailure):
            parse_ibge([{}, {**row, key: "wrong"}], ref, d)


def test_bls_shared_parser_rejects_wrong_identity_and_excludes_annual_average():
    from forecasting.marketdata.providers.bls import parse_bls

    _, ref = binding("bls")
    payload = {
        "Results": {
            "series": [
                {
                    "seriesID": ref.symbol,
                    "data": [
                        {"year": "2025", "period": "M13", "value": "999"},
                        {"year": "2025", "period": "M12", "value": "320"},
                        {"year": "2025", "period": "M11", "value": "319"},
                    ],
                }
            ]
        }
    }
    quote = parse_bls(payload, ref)
    assert quote.value == 320
    assert len(quote.dated_history) == 2
    assert quote.dated_history[-1].period_end == "2025-12-31"
    payload["Results"]["series"][0]["seriesID"] = "WRONG"
    with pytest.raises(ProviderFailure):
        parse_bls(payload, ref)


def test_sparse_change_retains_previous_available_observation():
    from datetime import date, timedelta
    from forecasting.marketdata.model import DatedValue, SeriesRef
    start = date(2025, 1, 1)
    points = [DatedValue(period_start=(start + timedelta(days=i)).isoformat(), period_end=(start + timedelta(days=i)).isoformat(), value=10 if i == 0 else 12 if i == 50 else None) for i in range(51)]
    quote = observation_quote(SeriesRef(provider="test", symbol="sparse"), points)
    assert quote.value == 12
    assert quote.change == 2
    assert quote.changePct == 20
    assert len(quote.dated_history) <= 36
    assert quote.dated_history[0].value == 10
