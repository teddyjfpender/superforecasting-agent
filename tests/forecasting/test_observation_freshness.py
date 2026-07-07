"""The missing-observation rule — ordinary lag vs. excessive staleness.

Pins the honest handling of a lagging daily official series (the operator's live
catch: FRED DCOILWTICO had no 2026-06-30 row; the latest real row was
2026-06-29 = 71.87). The honest answer is the latest-available observation
carried with ITS OWN date — never a fabricated today-dated row, and never a bare
refusal over an ordinary publication lag.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest

from forecasting import source_adapters
from forecasting.models import ValidationError
from forecasting.observation_freshness import (
    DEFAULT_MAX_BUSINESS_DAYS,
    assess_observation_freshness,
    business_days_between,
    cadence_aware_max_business_days,
    describe_missing_observation_rule,
    infer_cadence_business_days,
    resolve_max_business_days,
)
from forecasting.marketdata.model import SeriesRef
from forecasting.marketdata.providers.fred import FredProvider, parse_fred_csv
from forecasting.source_adapters import EiaObservation, FredObservation


# ── business_days_between: weekends + holidays don't count as lag ─────────────


def test_business_days_skip_weekends():
    # Fri 2026-06-26 → Mon 2026-06-29: only Monday counts (weekend skipped).
    assert business_days_between("2026-06-26", "2026-06-29") == 1
    # Mon 2026-06-29 → Tue 2026-06-30 (the operator's exact case): 1 bday.
    assert business_days_between("2026-06-29", "2026-06-30") == 1
    # Fri → next Fri is a full trading week.
    assert business_days_between("2026-06-26", "2026-07-03") == 5


def test_business_days_same_or_backwards_is_zero():
    assert business_days_between("2026-06-29", "2026-06-29") == 0
    assert business_days_between("2026-06-30", "2026-06-29") == 0


def test_business_days_skip_holidays():
    # Fri 2026-07-03 (observed Independence Day) between obs and ref → not counted.
    holidays = frozenset({date(2026, 7, 3)})
    # Wed 2026-07-01 → Mon 2026-07-06 with 7/3 holiday: 7/2(Th), 7/6(Mon) = 2.
    assert business_days_between("2026-07-01", "2026-07-06", holidays=holidays) == 2
    # Same window without the holiday: 7/2, 7/3, 7/6 = 3.
    assert business_days_between("2026-07-01", "2026-07-06") == 3


# ── the threshold: default, env override, per-series-class ────────────────────


def test_resolve_max_business_days_default_and_classes():
    assert resolve_max_business_days("daily") == 5
    assert resolve_max_business_days("weekly") == 10
    assert resolve_max_business_days("monthly") == 45
    assert DEFAULT_MAX_BUSINESS_DAYS == 5


def test_resolve_max_business_days_env_override(monkeypatch):
    monkeypatch.setenv("FORECAST_OBS_MAX_LAG_BDAYS", "8")
    assert resolve_max_business_days("daily") == 8
    # explicit positive beats env.
    assert resolve_max_business_days("daily", explicit=3) == 3
    # non-numeric / non-positive fall through to the class default.
    monkeypatch.setenv("FORECAST_OBS_MAX_LAG_BDAYS", "bogus")
    assert resolve_max_business_days("daily") == 5


# ── assess_observation_freshness: ordinary / excessive / unknown ──────────────


def test_ordinary_lag_serves_lagged_latest_with_its_own_as_of():
    # DCOILWTICO latest 2026-06-29 read on 2026-06-30 → 1 bday lag → ordinary.
    verdict = assess_observation_freshness(
        "2026-06-29", as_of_reference="2026-06-30", label="DCOILWTICO"
    )
    assert verdict.status == "ordinary"
    assert verdict.is_ordinary and not verdict.is_missing
    assert verdict.lag_business_days == 1
    # as_of is the observation's OWN date, never "today".
    assert verdict.as_of == date(2026, 6, 29)
    assert verdict.as_of_iso == "2026-06-29"
    assert "2026-06-29" in verdict.note


def test_weekend_read_of_friday_print_is_zero_lag_ordinary():
    # Friday 2026-06-26 print read on Sunday 2026-06-28 → 0 business days stale.
    verdict = assess_observation_freshness(
        "2026-06-26", as_of_reference="2026-06-28", label="DCOILWTICO"
    )
    assert verdict.status == "ordinary"
    assert verdict.lag_business_days == 0


def test_excessive_lag_goes_missing_with_staleness_note():
    # 2026-06-29 read a month later → far beyond 5 bdays → excessive/missing.
    verdict = assess_observation_freshness(
        "2026-06-29", as_of_reference="2026-07-31", label="DCOILWTICO"
    )
    assert verdict.status == "excessive"
    assert verdict.is_missing
    assert verdict.lag_business_days > DEFAULT_MAX_BUSINESS_DAYS
    assert "stale" in verdict.note.lower()


def test_boundary_lag_equal_to_threshold_is_ordinary():
    # Exactly N business days is still ordinary (<= N).
    verdict = assess_observation_freshness(
        "2026-06-26", as_of_reference="2026-07-03", max_business_days=5
    )
    assert verdict.lag_business_days == 5
    assert verdict.status == "ordinary"


def test_holiday_keeps_lag_ordinary_at_the_edge():
    # 2026-06-29 read on 2026-07-07 is 6 bdays raw, but 7/3 observed-holiday
    # pulls it to 5 → still ordinary. Proves holiday-awareness prevents a
    # spurious missing-data flip.
    holidays = frozenset({date(2026, 7, 3)})
    verdict = assess_observation_freshness(
        "2026-06-29", as_of_reference="2026-07-07", holidays=holidays, max_business_days=5
    )
    assert verdict.lag_business_days == 5
    assert verdict.status == "ordinary"
    # Without the holiday it would tip to excessive.
    hot = assess_observation_freshness(
        "2026-06-29", as_of_reference="2026-07-07", max_business_days=5
    )
    assert hot.lag_business_days == 6
    assert hot.status == "excessive"


def test_undated_observation_is_unknown_not_a_guess():
    verdict = assess_observation_freshness(
        None, as_of_reference="2026-06-30", label="DCOILWTICO"
    )
    assert verdict.status == "unknown"
    assert verdict.as_of is None


# ── cadence inference keeps a monthly series from being aged like a daily ─────


def test_cadence_inference_daily_vs_monthly():
    daily = ["2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"]
    assert infer_cadence_business_days(daily) == 1
    monthly = ["2026-03-01", "2026-04-01", "2026-05-01", "2026-06-01"]
    assert infer_cadence_business_days(monthly) >= 20  # ~a month of business days


def test_cadence_aware_threshold_scales_with_cadence():
    assert cadence_aware_max_business_days(1) == 5           # daily → floor
    assert cadence_aware_max_business_days(None) == 5        # unknown → floor
    assert cadence_aware_max_business_days(22) == 66         # monthly → 3 periods


# ── the FRED market-data provider ages at the fetch boundary ─────────────────


def _fred_series(symbol: str = "DCOILWTICO") -> SeriesRef:
    return SeriesRef(provider="fred", symbol=symbol, name=symbol, category="Commodities", unit="$/bbl")


def _daily_csv_ending(last: date, values: list[float]) -> str:
    """A fredgraph-style CSV of consecutive business days ending on ``last``."""

    days: list[date] = []
    cursor = last
    while len(days) < len(values):
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    days.reverse()
    rows = "\n".join(f"{d.isoformat()},{v}" for d, v in zip(days, values))
    return "DATE,DCOILWTICO\n" + rows + "\n"


def test_fred_parser_ordinary_lag_keeps_value():
    csv = _daily_csv_ending(date(2026, 6, 29), [70.30, 71.87])
    # Read the following day → ordinary → value 71.87 stays, asOf = 2026-06-29.
    q = parse_fred_csv(csv, _fred_series(), as_of_reference=date(2026, 6, 30))
    assert q.value == pytest.approx(71.87)


def test_fred_parser_excessive_lag_blanks_value_to_none():
    csv = _daily_csv_ending(date(2026, 6, 29), [70.30, 71.87])
    # Read a month later → daily feed gone dark → value None (THE LAW),
    # asOf preserved so the age stays visible.
    q = parse_fred_csv(csv, _fred_series(), as_of_reference=date(2026, 7, 31))
    assert q.value is None
    assert q.change is None
    assert q.asOf != 0  # the observation date is still carried


def test_fred_parser_monthly_series_not_blanked_as_stale():
    # A monthly series a few weeks past its print must NOT be treated as a dead
    # daily feed — cadence-awareness keeps it live.
    csv = (
        "DATE,UNRATE\n"
        "2026-03-01,4.1\n2026-04-01,4.2\n2026-05-01,4.0\n2026-06-01,4.3\n"
    )
    q = parse_fred_csv(csv, _fred_series("UNRATE"), as_of_reference=date(2026, 6, 25))
    assert q.value == pytest.approx(4.3)  # ~18 bdays lag, but monthly cadence


def test_fred_parser_without_reference_never_ages():
    # The pure-parser path (no reference) keeps prior behaviour: no aging.
    csv = _daily_csv_ending(date(2020, 1, 2), [10.0, 11.0])
    q = parse_fred_csv(csv, _fred_series())
    assert q.value == pytest.approx(11.0)


def test_fred_fetch_threads_today_and_blanks_a_dead_feed():
    # An old CSV fetched today (2026+) is far past a week → blanked to None.
    old_csv = _daily_csv_ending(date(2020, 1, 2), [10.0, 11.0])
    prov = FredProvider(get_text=lambda url: old_csv)
    [q] = prov.fetch([_fred_series()])
    assert q.value is None


def test_fred_fetch_recent_feed_keeps_value():
    today = date.today()
    recent = _daily_csv_ending(today, [70.0, 71.87])
    prov = FredProvider(get_text=lambda url: recent)
    [q] = prov.fetch([_fred_series()])
    assert q.value == pytest.approx(71.87)


# ── the evidence path: assess_series_freshness over loaded observations ──────


def _fred_obs(observation_date: str, value: float) -> FredObservation:
    return FredObservation(
        series_id="DCOILWTICO",
        observation_date=observation_date,
        value=value,
        published_at=f"{observation_date}T00:00:00Z",
        source_url="https://fred.stlouisfed.org/series/DCOILWTICO",
        source_name="FRED",
        entry_id=f"DCOILWTICO:{observation_date}",
        raw={},
    )


def test_assess_series_freshness_ordinary_on_recent_fred_rows():
    rows = [_fred_obs("2026-06-26", 70.30), _fred_obs("2026-06-29", 71.87)]
    verdict = source_adapters.assess_series_freshness(
        rows, as_of_reference=date(2026, 6, 30)
    )
    assert verdict.status == "ordinary"
    assert verdict.as_of == date(2026, 6, 29)
    assert "DCOILWTICO" in verdict.note


def test_assess_series_freshness_excessive_on_old_fred_rows():
    rows = [_fred_obs("2026-06-26", 70.30), _fred_obs("2026-06-29", 71.87)]
    verdict = source_adapters.assess_series_freshness(
        rows, as_of_reference=date(2026, 9, 1)
    )
    assert verdict.status == "excessive"
    assert verdict.is_missing


def test_assess_series_freshness_empty_is_unknown():
    verdict = source_adapters.assess_series_freshness([], label="DCOILWTICO")
    assert verdict.status == "unknown"


def test_assess_series_freshness_reads_eia_published_at():
    obs = EiaObservation(
        series_id="PET.RWTC.D",
        series_name="WTI crude",
        observation_period="2026-06-29",
        value=71.87,
        unit="$/bbl",
        published_at="2026-06-29T00:00:00Z",
        source_url="https://api.eia.gov/v2/...",
        source_name="EIA",
        entry_id="PET.RWTC.D:2026-06-29",
        raw={},
    )
    verdict = source_adapters.assess_series_freshness(
        [obs], as_of_reference=date(2026, 6, 30)
    )
    assert verdict.status == "ordinary"
    assert verdict.as_of == date(2026, 6, 29)


# ── EIA: missing key teaches, present key builds a keyed request ─────────────


def test_eia_missing_key_raises_teaching_error(monkeypatch):
    monkeypatch.delenv("EIA_API_KEY", raising=False)

    def _boom(*args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("keyless EIA must fail BEFORE any request")

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", _boom)
    with pytest.raises(ValidationError) as exc:
        source_adapters.load_eia_observations("PET.RWTC.D", limit=5)
    message = str(exc.value)
    assert "EIA_API_KEY" in message
    assert "403" in message
    assert "register" in message.lower()
    # names the keyless FRED alternative.
    assert "fred" in message.lower()


def test_eia_present_key_builds_keyed_request(monkeypatch):
    captured = {}

    def _fake_read_json(url, label, **kwargs):
        captured["url"] = url
        return {"series": []}

    monkeypatch.setenv("EIA_API_KEY", "test-eia-key")
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", _fake_read_json)
    source_adapters.load_eia_observations("eia:PET.RWTC.D", limit=5)
    assert "api_key=test-eia-key" in captured["url"]


# ── the rule is agent-facing (so the next run cites it, not agonizes) ─────────


def test_missing_observation_rule_is_documented_for_the_agent():
    from forecasting import protocol

    prompt = protocol.FORECAST_CHAT_SYSTEM_PROMPT
    assert "Missing-observation rule" in prompt
    assert "as_of" in prompt
    assert "71.87 as of 2026-06-29" in prompt
    rule = describe_missing_observation_rule()
    assert "latest-available".lower() in rule.lower() or "latest" in rule.lower()
    assert "as_of" in rule


# ── opt-in live probes (network) — skipped unless explicitly enabled ─────────


@pytest.mark.skipif(
    not os.environ.get("RUN_LIVE_SOURCE_PROBES"),
    reason="live network probe; set RUN_LIVE_SOURCE_PROBES=1 to run",
)
def test_live_probe_dcoilwtico_latest_with_honest_as_of():
    rows = source_adapters.load_fred_observations("DCOILWTICO", limit=5)
    assert rows, "DCOILWTICO returned no rows"
    verdict = source_adapters.assess_series_freshness(rows)
    # The latest real row carries its OWN observation date, never today.
    assert verdict.as_of is not None
    assert verdict.as_of < date.today()
    print(
        f"LIVE DCOILWTICO latest={rows[-1].value} as_of={rows[-1].observation_date} "
        f"lag={verdict.lag_business_days}bd status={verdict.status}"
    )


@pytest.mark.skipif(
    not os.environ.get("RUN_LIVE_SOURCE_PROBES"),
    reason="live network probe; set RUN_LIVE_SOURCE_PROBES=1 to run",
)
def test_live_probe_eia_without_key_teaches(monkeypatch):
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    with pytest.raises(ValidationError) as exc:
        source_adapters.load_eia_observations("PET.RWTC.D", limit=1)
    assert "EIA_API_KEY" in str(exc.value)
