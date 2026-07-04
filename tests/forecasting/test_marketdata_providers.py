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
from forecasting.marketdata.providers.frankfurter import parse_frankfurter


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
