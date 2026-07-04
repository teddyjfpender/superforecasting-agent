"""Provider contract tests for the server-side market-data plane (Arc C1).

Ported ONE-TO-ONE from ``ui-tui/src/lib/marketFetch.test.ts`` (the frankfurter +
bea cases), fixtures carried over verbatim. These are the estimator-honesty
tests that could NOT see the BEA quote math while it lived in client TypeScript —
now they do. THE LAW: absence is null, NEVER a fabricated 0.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from forecasting.marketdata.model import SeriesRef
from forecasting.marketdata.providers.bea import parse_bea
from forecasting.marketdata.providers.bls import parse_bls
from forecasting.marketdata.providers.coingecko import parse_coingecko
from forecasting.marketdata.providers.frankfurter import parse_frankfurter
from forecasting.marketdata.providers.fred import parse_fred, parse_fred_csv
from forecasting.marketdata.providers.stooq import parse_stooq


def _fx(symbol: str = "EUR", name: str = "X", unit: str = "") -> SeriesRef:
    return SeriesRef(provider="frankfurter", symbol=symbol, name=name, category="FX", unit=unit)


def _epoch_ms(y: int, m: int, d: int) -> int:
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)


# ── Frankfurter ───────────────────────────────────────────────────────────────


def test_frankfurter_latest_shaped_maps_each_rate_value_only():
    payload = {"base": "USD", "date": "2026-06-17", "rates": {"EUR": 0.86274, "JPY": 160.31}}
    out = parse_frankfurter(payload, [_fx("EUR"), _fx("JPY")])
    assert out[0].value == pytest.approx(0.86274)
    assert out[1].value == pytest.approx(160.31)
    assert out[0].asOf == _epoch_ms(2026, 6, 17)
    # /latest has no prior close → no fabricated change.
    assert out[0].change is None and out[0].changePct is None


def test_frankfurter_date_range_yields_value_day_change_and_history():
    payload = {
        "base": "USD",
        "rates": {
            "2026-06-02": {"EUR": 0.86},
            "2026-06-16": {"EUR": 0.865},
            "2026-07-02": {"EUR": 0.871},
            "2026-07-03": {"EUR": 0.8735},
        },
    }
    (q,) = parse_frankfurter(payload, [_fx("EUR")])
    assert q.value == pytest.approx(0.8735)
    assert q.prevClose == pytest.approx(0.871)
    assert q.change == pytest.approx(0.0025, abs=1e-6)
    assert q.changePct == pytest.approx(0.287, abs=0.01)
    assert q.history == [0.86, 0.865, 0.871, 0.8735]
    assert q.asOf == _epoch_ms(2026, 7, 3)


def test_frankfurter_latest_payload_backward_compatible():
    (q,) = parse_frankfurter({"date": "2026-07-03", "rates": {"EUR": 0.8735}}, [_fx("EUR")])
    assert q.value == pytest.approx(0.8735)
    assert q.change is None


def test_frankfurter_empty_rates_is_null_never_zero():
    (q,) = parse_frankfurter({"rates": {}}, [_fx("EUR")])
    assert q.value is None
    assert q.change is None and q.prevClose is None
    assert q.history == []


def test_frankfurter_missing_symbol_in_range_drops_to_null():
    # A degenerate range where the requested symbol never appears: value null.
    payload = {"rates": {"2026-07-02": {"JPY": 160.0}, "2026-07-03": {"JPY": 161.0}}}
    (q,) = parse_frankfurter(payload, [_fx("EUR")])
    assert q.value is None and q.history == []


# ── BEA (NIPA) ────────────────────────────────────────────────────────────────


def _bea(symbol: str = "T20305", name: str = "BEA", unit: str = "", line: str | None = None) -> SeriesRef:
    return SeriesRef(provider="bea", symbol=symbol, name=name, category="US Macro", unit=unit, line=line)


def test_bea_reads_last_datavalue_and_maps_quarter_to_date():
    payload = {
        "BEAAPI": {
            "Results": {
                "Data": [
                    {"DataValue": "1,000.0", "TimePeriod": "2026Q1"},
                    {"DataValue": "28,500.5", "TimePeriod": "2026Q2"},
                ]
            }
        }
    }
    q = parse_bea(payload, _bea("T10105", unit="$B"))
    assert q.value == pytest.approx(28500.5)
    # 2026Q2 → April 1 (no longer the hardcoded 0).
    assert q.asOf == _epoch_ms(2026, 4, 1)


def test_bea_reads_headline_line_computes_quarter_change_never_fabricates_zero():
    payload = {
        "BEAAPI": {
            "Results": {
                "Data": [
                    {"DataValue": "99", "LineNumber": "31", "TimePeriod": "2026Q1"},
                    {"DataValue": "21,363,352", "LineNumber": "1", "TimePeriod": "2025Q4"},
                    {"DataValue": "21,634,948", "LineNumber": "1", "TimePeriod": "2026Q1"},
                    {"DataValue": "88", "LineNumber": "31", "TimePeriod": "2025Q4"},
                ]
            }
        }
    }
    q = parse_bea(payload, _bea("T20305"))
    assert q.value == 21_634_948
    assert q.prevClose == 21_363_352
    assert q.change == 271_596
    assert q.changePct == pytest.approx(1.271, abs=0.01)


def test_bea_error_payload_is_null_never_zero():
    # An API-error payload (empty Data) must be NULL — absence renders '—', never
    # the fabricated 0.0000 the operator caught.
    err = parse_bea({"BEAAPI": {"Error": {"APIErrorCode": "201"}}}, _bea("T20305"))
    assert err.value is None
    assert err.change is None
    assert err.prevClose is None
    assert err.asOf == 0


def test_bea_per_series_line_override_selects_a_non_headline_line():
    payload = {
        "BEAAPI": {
            "Results": {
                "Data": [
                    {"DataValue": "1", "LineNumber": "1", "TimePeriod": "2026Q1"},
                    {"DataValue": "42", "LineNumber": "31", "TimePeriod": "2026Q1"},
                ]
            }
        }
    }
    q = parse_bea(payload, _bea("T20305", line="31"))
    assert q.value == 42


def test_bea_annual_period_maps_to_january_first():
    payload = {"BEAAPI": {"Results": {"Data": [{"DataValue": "100", "TimePeriod": "2025"}]}}}
    q = parse_bea(payload, _bea("T10101"))
    assert q.value == 100
    assert q.asOf == _epoch_ms(2025, 1, 1)


# ── CoinGecko ─────────────────────────────────────────────────────────────────


def _cg(symbol: str = "bitcoin", name: str = "X", unit: str = "") -> SeriesRef:
    return SeriesRef(provider="coingecko", symbol=symbol, name=name, category="Crypto", unit=unit)


def test_coingecko_reads_usd_price_and_derives_change_from_24h_pct():
    # Ported from marketFetch.test.ts parseCoingecko.
    payload = {"bitcoin": {"usd": 64239, "usd_24h_change": -1.05}}
    (q,) = parse_coingecko(payload, [_cg("bitcoin")], now_ms=1_700_000_000_000)
    assert q.value == pytest.approx(64239)
    assert q.changePct == pytest.approx(-1.05)
    # change is DERIVED (value * pct/100), NOT value - prevClose.
    assert q.change == pytest.approx(64239 * -0.0105, abs=0.5)
    assert q.prevClose is None and q.history == []
    assert q.asOf == 1_700_000_000_000  # the fetch instant, injected for determinism


def test_coingecko_batches_all_ids_and_maps_each():
    payload = {"bitcoin": {"usd": 64239, "usd_24h_change": -1.05}, "ethereum": {"usd": 3200, "usd_24h_change": 2.0}}
    out = parse_coingecko(payload, [_cg("bitcoin"), _cg("ethereum")], now_ms=0)
    assert [q.value for q in out] == [pytest.approx(64239), pytest.approx(3200)]


def test_coingecko_missing_coin_and_error_payload_are_null_never_zero():
    # A coin absent from the batch → null; an error/empty payload → null (THE LAW).
    (missing,) = parse_coingecko({"ethereum": {"usd": 3200}}, [_cg("bitcoin")], now_ms=0)
    assert missing.value is None and missing.change is None and missing.changePct is None
    (err,) = parse_coingecko({"status": {"error_code": 429}}, [_cg("bitcoin")], now_ms=0)
    assert err.value is None


# ── FRED (keyed JSON + keyless CSV) ───────────────────────────────────────────


def _fred(symbol: str = "UNRATE", name: str = "X", unit: str = "") -> SeriesRef:
    return SeriesRef(provider="fred", symbol=symbol, name=name, category="Employment", unit=unit)


def test_fred_json_takes_latest_observation_and_change_vs_prior():
    # Ported from marketFetch.test.ts parseFred.
    payload = {"observations": [{"date": "2026-05-01", "value": "4.2"}, {"date": "2026-04-01", "value": "4.0"}]}
    q = parse_fred(payload, _fred("UNRATE", unit="%"))
    assert q.value == pytest.approx(4.2)
    assert q.change == pytest.approx(0.2, abs=1e-5)
    assert q.asOf == _epoch_ms(2026, 5, 1)


def test_fred_json_missing_value_dot_is_null():
    payload = {"observations": [{"date": "2026-05-01", "value": "."}]}
    assert parse_fred(payload, _fred()).value is None


def test_fred_json_error_payload_is_null_never_zero():
    err = parse_fred({"error_code": 400, "error_message": "Bad Request"}, _fred())
    assert err.value is None and err.change is None


def test_fred_csv_takes_last_two_real_rows_skipping_dot():
    # Ported from marketFetch.test.ts parseFredCsv.
    csv = "DATE,FEDFUNDS\n2026-03-01,5.30\n2026-04-01,.\n2026-05-01,5.10\n2026-06-01,4.90\n"
    q = parse_fred_csv(csv, _fred("FEDFUNDS", unit="%"))
    assert q.value == pytest.approx(4.9)
    # prior real value is 5.10 (the "." row is skipped).
    assert q.change == pytest.approx(-0.2, abs=1e-5)
    assert q.asOf == _epoch_ms(2026, 6, 1)


def test_fred_csv_empty_or_headers_only_is_null_never_zero():
    assert parse_fred_csv("DATE,X\n", _fred()).value is None
    assert parse_fred_csv("", _fred()).value is None


# ── BLS ───────────────────────────────────────────────────────────────────────


def _bls(symbol: str = "CUUR0000SA0", name: str = "X", unit: str = "") -> SeriesRef:
    return SeriesRef(provider="bls", symbol=symbol, name=name, category="Inflation", unit=unit)


def test_bls_reads_latest_datapoint_change_and_maps_period_to_date():
    # Ported from marketFetch.test.ts parseBls.
    payload = {
        "Results": {
            "series": [
                {"data": [{"period": "M05", "value": "320.1", "year": "2026"}, {"period": "M04", "value": "319.0", "year": "2026"}]}
            ]
        }
    }
    q = parse_bls(payload, _bls("CUUR0000SA0"))
    assert q.value == pytest.approx(320.1)
    assert q.change == pytest.approx(1.1, abs=1e-5)
    # M05 → month 5 → 2026-05-01.
    assert q.asOf == _epoch_ms(2026, 5, 1)


def test_bls_error_payload_is_null_never_zero():
    err = parse_bls({"status": "REQUEST_NOT_PROCESSED", "Results": {}}, _bls())
    assert err.value is None and err.change is None and err.asOf == 0


# ── Stooq (daily OHLC CSV) ────────────────────────────────────────────────────


def _stq(symbol: str = "aapl.us", name: str = "Apple", unit: str = "") -> SeriesRef:
    return SeriesRef(provider="stooq", symbol=symbol, name=name, category="Stocks", unit=unit)


def test_stooq_daily_csv_yields_value_change_and_history_off_close():
    csv = (
        "Date,Open,High,Low,Close,Volume\n"
        "2026-06-30,10.0,10.5,9.9,10.2,1000\n"
        "2026-07-01,10.2,10.6,10.1,10.4,1100\n"
        "2026-07-02,10.4,10.9,10.3,10.8,1200\n"
    )
    q = parse_stooq(csv, _stq())
    assert q.value == pytest.approx(10.8)
    assert q.prevClose == pytest.approx(10.4)
    assert q.change == pytest.approx(0.4, abs=1e-6)
    assert q.history == [pytest.approx(10.2), pytest.approx(10.4), pytest.approx(10.8)]
    assert q.asOf == _epoch_ms(2026, 7, 2)


def test_stooq_skips_missing_close_values_nd():
    csv = "Date,Open,High,Low,Close,Volume\n2026-07-01,1,1,1,N/D,0\n2026-07-02,2,2,2,10.5,5\n"
    q = parse_stooq(csv, _stq())
    assert q.value == pytest.approx(10.5)
    assert q.prevClose is None  # only one real close → no prior
    assert q.change is None


def test_stooq_error_or_empty_is_null_never_zero():
    # Stooq returns a plain-text error ("Exceeded ...") for unknown symbols.
    assert parse_stooq("Exceeded the daily hits limit", _stq()).value is None
    assert parse_stooq("", _stq()).value is None
    # A header row with no data rows is honest-null.
    assert parse_stooq("Date,Open,High,Low,Close,Volume\n", _stq()).value is None
