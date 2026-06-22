#!/usr/bin/env python3
"""Seed a continuous/distributional calibration battery into the forecast ledger.

Ten near-term, distribution-type questions chosen to stress every way a
predictive density can be mis-modeled (anchored-tight, fat-tailed, near-random
walk across asset classes, Poisson counts, skewed time-to-event). Each is wired
to the right source adapters as watched sources, given a daily review cadence so
it re-forecasts every day, and given event-driven update triggers.

Respects FORECAST_LEDGER_DB, so you can dry-run against a throwaway DB first:

    FORECAST_LEDGER_DB=/tmp/seed_test.db python3 scripts/seed_eval_questions.py

Idempotent by title: re-running skips questions that already exist.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow running as `python3 scripts/seed_eval_questions.py` from anywhere: the
# script's own dir shadows the repo root on sys.path[0], so add the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forecasting import ForecastLedger
from forecasting.models import OutcomeSpace

NOW = datetime(2026, 6, 1, 18, 0, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# A daily re-forecast kicks off tomorrow morning UTC.
NEXT_REVIEW = iso(NOW.replace(hour=12, minute=0, second=0) + timedelta(days=1))


def ws(source: str, source_type: str) -> dict:
    return {"source": source, "source_type": source_type}


# Each entry: the question definition + its watched sources + update triggers.
QUESTIONS: list[dict] = [
    {
        "title": "What will the May 2026 US CPI-U all-items month-over-month percent change be (first published, seasonally adjusted)?",
        "resolution_criteria": (
            "Resolves to the official first-published BLS CPI-U, U.S. city average, all items, "
            "1-month seasonally adjusted percent change for May 2026, from the first BLS CPI news "
            "release. Report to two decimals (e.g., 0.21)."
        ),
        "resolution_source": "https://www.bls.gov/cpi/",
        "domain": "macro",
        "topics": ["inflation", "cpi", "eval-battery", "anchored-tight"],
        "units": "percent month-over-month",
        "bounds": [-2.0, 3.0],
        "close": iso(datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)),
        "resolve": iso(datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)),
        "watched": [
            ws("CPIAUCSL", "fred"),
            ws("TRMMEANCPIM159SFRBCLE", "fred"),
            ws("MEDCPIM159SFRBCLE", "fred"),
            ws("GASREGW", "fred"),
            ws("DCOILWTICO", "fred"),
            ws("https://www.eia.gov/petroleum/gasdiesel/includes/gas_diesel_rss.xml", "rss"),
        ],
        "triggers": [
            {"action": "rerun forecast", "mechanism": "Cleveland Fed inflation nowcast update",
             "operator": ">=", "source_ref": "fred:MEDCPIM159SFRBCLE", "threshold": 0.0},
            {"action": "rerun energy component", "mechanism": "Weekly retail gasoline moves materially",
             "operator": ">=", "source_ref": "fred:GASREGW", "threshold": 4.5},
        ],
    },
    {
        "title": "What will the change in US total nonfarm payrolls for June 2026 be (first published, thousands)?",
        "resolution_criteria": (
            "Resolves to the change in total nonfarm payroll employment for June 2026 in thousands, "
            "from the first BLS Employment Situation release (the initial print, not later revisions)."
        ),
        "resolution_source": "https://www.bls.gov/ces/",
        "domain": "macro",
        "topics": ["labor", "payrolls", "eval-battery", "fat-tailed"],
        "units": "thousands of jobs (month-over-month change)",
        "bounds": [-800.0, 800.0],
        "close": iso(datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)),
        "resolve": iso(datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)),
        "watched": [
            ws("PAYEMS", "fred"),
            ws("ICSA", "fred"),
            ws("CCSA", "fred"),
            ws("UNRATE", "fred"),
        ],
        "triggers": [
            {"action": "reassess labor momentum", "mechanism": "Weekly initial jobless claims print",
             "operator": ">=", "source_ref": "fred:ICSA", "threshold": 260000.0},
        ],
    },
    {
        "title": "What will the US unemployment rate (U-3) for June 2026 be (first published, percent)?",
        "resolution_criteria": (
            "Resolves to the seasonally adjusted U-3 civilian unemployment rate for June 2026, in "
            "percent to one decimal, from the first BLS Employment Situation release."
        ),
        "resolution_source": "https://www.bls.gov/cps/",
        "domain": "macro",
        "topics": ["labor", "unemployment", "eval-battery", "bounded"],
        "units": "percent",
        "bounds": [2.5, 8.0],
        "close": iso(datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)),
        "resolve": iso(datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)),
        "watched": [
            ws("UNRATE", "fred"),
            ws("ICSA", "fred"),
            ws("CIVPART", "fred"),
        ],
        "triggers": [],
    },
    {
        "title": "What will the June 2026 ISM Manufacturing PMI headline index level be (first published)?",
        "resolution_criteria": (
            "Resolves to the headline ISM Manufacturing PMI (Purchasing Managers Index) level for "
            "June 2026 in index points to one decimal, from the first ISM Manufacturing report."
        ),
        "resolution_source": "https://www.ismworld.org/",
        "domain": "macro",
        "topics": ["manufacturing", "pmi", "eval-battery", "bounded-symmetric"],
        "units": "index points",
        "bounds": [40.0, 60.0],
        "close": iso(datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)),
        "resolve": iso(datetime(2026, 7, 1, 18, 0, tzinfo=timezone.utc)),
        # No free ISM series (NAPM was discontinued on FRED); nowcast off the
        # regional Fed manufacturing surveys that ARE free, plus news.
        "watched": [
            ws("GACDISA066MSFRBNY", "fred"),  # Empire State general business conditions
            ws("INDPRO", "fred"),             # industrial production
            ws("https://news.google.com/rss/search?q=%28%22ISM%20Manufacturing%22%20OR%20%22PMI%22%29%20when%3A14d&hl=en-US&gl=US&ceid=US%3Aen", "rss"),
        ],
        "triggers": [],
    },
    {
        "title": "What will the Bitcoin (BTC-USD) closing price be on 2026-06-30 (UTC)?",
        "resolution_criteria": (
            "Resolves to the BTC-USD price in US dollars as of 23:59 UTC on 2026-06-30, per CoinGecko's "
            "bitcoin market price. Model as a log-normal / heavy-tailed density, not a symmetric normal."
        ),
        "resolution_source": "https://www.coingecko.com/en/coins/bitcoin",
        "domain": "markets",
        "topics": ["crypto", "bitcoin", "eval-battery", "log-normal", "random-walk"],
        "units": "USD",
        "bounds": [0.0, 500000.0],
        "close": iso(datetime(2026, 6, 30, 23, 59, tzinfo=timezone.utc)),
        "resolve": iso(datetime(2026, 7, 1, 6, 0, tzinfo=timezone.utc)),
        "watched": [
            ws("bitcoin", "coingecko"),
            ws("https://news.google.com/rss/search?q=bitcoin%20price%20when%3A3d&hl=en-US&gl=US&ceid=US%3Aen", "rss"),
        ],
        "triggers": [],
    },
    {
        "title": "What will the US 10-year Treasury constant-maturity yield be on 2026-06-30 (percent)?",
        "resolution_criteria": (
            "Resolves to the US 10-year Treasury constant maturity yield (DGS10) for 2026-06-30 in "
            "percent to two decimals, per FRED/Treasury. Near-random-walk with mild mean reversion."
        ),
        "resolution_source": "https://fred.stlouisfed.org/series/DGS10",
        "domain": "macro",
        "topics": ["rates", "treasuries", "eval-battery", "near-random-walk"],
        "units": "percent",
        "bounds": [0.0, 10.0],
        "close": iso(datetime(2026, 6, 30, 21, 0, tzinfo=timezone.utc)),
        "resolve": iso(datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)),
        "watched": [
            ws("DGS10", "fred"),
            ws("T10YIE", "fred"),
            ws("DFF", "fred"),
        ],
        "triggers": [
            {"action": "rerun rates forecast", "mechanism": "10Y yield gaps from the last captured level",
             "operator": ">=", "source_ref": "fred:DGS10", "threshold": 0.0},
        ],
    },
    {
        "title": "What will the WTI crude oil front-month closing price be on 2026-06-30 (USD per barrel)?",
        "resolution_criteria": (
            "Resolves to the WTI crude oil spot/front-month price (DCOILWTICO) for 2026-06-30 in USD "
            "per barrel to two decimals, per FRED/EIA. Skewed with upside jump risk; do not force normality."
        ),
        "resolution_source": "https://fred.stlouisfed.org/series/DCOILWTICO",
        "domain": "markets",
        "topics": ["energy", "oil", "eval-battery", "skewed-jumps"],
        "units": "USD per barrel",
        "bounds": [0.0, 250.0],
        "close": iso(datetime(2026, 6, 30, 21, 0, tzinfo=timezone.utc)),
        "resolve": iso(datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)),
        "watched": [
            ws("DCOILWTICO", "fred"),
            ws("GASREGW", "fred"),
            ws("https://www.eia.gov/rss/todayinenergy.xml", "rss"),
        ],
        "triggers": [
            {"action": "rerun oil forecast", "mechanism": "WTI gaps from the last captured level",
             "operator": ">=", "source_ref": "fred:DCOILWTICO", "threshold": 0.0},
        ],
    },
    {
        "title": "How many named Atlantic tropical storms will have formed in the 2026 season by 2026-07-15?",
        "resolution_criteria": (
            "Resolves to the count of named storms (tropical storms and hurricanes that received a "
            "name) in the 2026 Atlantic hurricane season with formation on or before 2026-07-15 23:59 "
            "UTC, per the NHC. Integer count; model as a Poisson-like density over integers."
        ),
        "resolution_source": "https://www.nhc.noaa.gov/",
        "domain": "nature",
        "topics": ["weather", "hurricanes", "eval-battery", "poisson-count"],
        "units": "named storms",
        "bounds": [0.0, 12.0],
        "close": iso(datetime(2026, 7, 15, 23, 59, tzinfo=timezone.utc)),
        "resolve": iso(datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)),
        "watched": [
            ws("https://www.nhc.noaa.gov/index-at.xml", "rss"),
            ws("https://news.google.com/rss/search?q=%28%22tropical%20storm%22%20OR%20%22tropical%20depression%22%20OR%20hurricane%29%20Atlantic%20when%3A7d&hl=en-US&gl=US&ceid=US%3Aen", "rss"),
        ],
        "triggers": [],
    },
    {
        "title": "How many M5.0+ earthquakes will occur worldwide between 2026-06-15 and 2026-06-30 (inclusive, UTC)?",
        "resolution_criteria": (
            "Resolves to the count of earthquakes worldwide with magnitude >= 5.0 and origin time "
            "between 2026-06-15 00:00 and 2026-06-30 23:59 UTC, per the USGS earthquake catalog "
            "(final/reviewed). Integer count; strong known base rate (Poisson)."
        ),
        "resolution_source": "https://earthquake.usgs.gov/earthquakes/search/",
        "domain": "nature",
        "topics": ["geophysics", "earthquakes", "eval-battery", "poisson-rate"],
        "units": "earthquakes (M>=5.0)",
        "bounds": [0.0, 120.0],
        "close": iso(datetime(2026, 6, 30, 23, 59, tzinfo=timezone.utc)),
        "resolve": iso(datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)),
        "watched": [
            ws("usgs:minmagnitude=5", "usgs"),
            ws("https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.atom", "rss"),
        ],
        "triggers": [],
    },
    {
        "title": "How many days after 2026-06-01 until the next SpaceX Starship integrated flight test launches?",
        "resolution_criteria": (
            "Resolves to the integer number of days from 2026-06-01 (UTC) until the next SpaceX "
            "Starship integrated (Super Heavy + Ship) flight test lifts off, per SpaceX/FAA. If no "
            "such flight has launched by 2026-07-15, the observation is right-censored at >45 days "
            "(score as censored, not as a miss). Model the long right-skew of launch slips."
        ),
        "resolution_source": "https://www.spacex.com/launches/",
        "domain": "space",
        "topics": ["spaceflight", "starship", "eval-battery", "duration-skew", "censored"],
        "units": "days from 2026-06-01",
        "bounds": [0.0, 200.0],
        "close": iso(datetime(2026, 7, 15, 23, 59, tzinfo=timezone.utc)),
        "resolve": iso(datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)),
        "watched": [
            ws("https://news.google.com/rss/search?q=%28Starship%20OR%20%22Super%20Heavy%22%29%20SpaceX%20%28launch%20OR%20flight%29%20when%3A7d&hl=en-US&gl=US&ceid=US%3Aen", "rss"),
        ],
        "triggers": [],
    },
    {
        "title": "What will the highest daily maximum temperature in Phoenix, AZ during June 2026 be (degrees F)?",
        "resolution_criteria": (
            "Resolves to the maximum single-day high temperature recorded at Phoenix Sky Harbor (KPHX) "
            "during June 2026 in degrees Fahrenheit, per NWS/Open-Meteo. Heavy upper tail (records)."
        ),
        "resolution_source": "https://www.weather.gov/psr/",
        "domain": "nature",
        "topics": ["weather", "temperature", "eval-battery", "extreme-tail"],
        "units": "degrees Fahrenheit",
        "bounds": [80.0, 130.0],
        "close": iso(datetime(2026, 6, 30, 23, 59, tzinfo=timezone.utc)),
        "resolve": iso(datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)),
        "watched": [
            ws("33.4484,-112.0740", "openmeteo"),
        ],
        "triggers": [],
    },
]


def main() -> None:
    ledger = ForecastLedger()
    print(f"ledger db: {ledger.db_path}")
    existing = {q.title for q in ledger.list_questions(status=None)}
    created = 0
    for spec in QUESTIONS:
        if spec["title"] in existing:
            print(f"skip (exists): {spec['title'][:70]}")
            continue
        outcome = OutcomeSpace(type="distribution", units=spec["units"], bounds=spec["bounds"])
        question = ledger.create_question(
            title=spec["title"],
            resolution_criteria=spec["resolution_criteria"],
            outcome_space=outcome,
            resolution_source=spec["resolution_source"],
            close_time=spec["close"],
            resolution_time=spec["resolve"],
            domain=spec["domain"],
            topics=spec["topics"],
            review_cadence="daily",
            next_review_at=NEXT_REVIEW,
            update_triggers=spec["triggers"] or None,
        )
        for source in spec["watched"]:
            ledger.add_watched_source(
                scope_type="question",
                scope_ref=question.id,
                source=source["source"],
                source_type=source["source_type"],
                metadata={"auto_watch": True, "from_action": "seed_eval_questions"},
            )
        created += 1
        print(f"created {question.id}  [{spec['units']}]  {spec['title'][:64]}")
    print(f"\n{created} created, {len(QUESTIONS) - created} skipped. Daily review at {NEXT_REVIEW}.")


if __name__ == "__main__":
    main()
