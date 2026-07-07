"""The missing-observation rule — one honest way to age a lagged series.

Daily official series (FRED ``DCOILWTICO``, EIA spot prices) publish with a lag:
the value for a given business day appears a business day or two later, and
weekends / holidays carry NO row BY DESIGN. The honest reading of "what is the
latest?" is therefore the LATEST AVAILABLE observation carried WITH ITS OWN
observation date — never a value stamped with today's date (that fabricates a
row the source never published), and never a bare error for an ordinary
publication lag (that is over-refusal). "Last known: 71.87 as of 2026-06-29" is
truth; a conjured 2026-06-30 row is a lie, and a 403-style refusal over an
ordinary T-1 lag is the opposite failure.

This module draws the single line between the two cases:

* **ORDINARY lag** — the newest observation is ``<= max_business_days`` US
  business days behind the reference date. Serve it, stamped ``as_of`` = ITS OWN
  observation date. The note reports the lag so the reader sees it.
* **EXCESSIVE lag** — the newest observation is MORE than ``max_business_days``
  behind, i.e. the series has genuinely gone dark. This is the missing-data
  path: the value is ``None`` + a staleness note the watch machinery can alert
  on. A stale reading is never carried forward dressed as current.

Weekends and (optional) holidays between the observation and the reference date
are NOT counted as lag — a Friday print read on Monday is 0 business days stale,
not 3. The default threshold (5 business days = a full trading week) is generous
enough for any ordinary government-publication delay yet tight enough that a
truly dead daily feed trips the missing-data path. Slower cadences (weekly,
monthly) need a larger window; see :func:`resolve_max_business_days` and
:func:`cadence_aware_max_business_days`.

The rule is pure and deterministic (the caller injects the reference date), so
the estimator-honesty tests can pin it. It is imported by both the market-data
FRED provider (``forecasting/marketdata/providers/fred.py``) and the evidence /
source-adapter path (``forecasting/source_adapters.py``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# A full trading week: generous for ordinary publication lag, tight enough that
# a dead daily feed trips the missing-data path.
DEFAULT_MAX_BUSINESS_DAYS = 5

# Per-cadence defaults (business days). A daily series is stale within a week; a
# monthly series is only stale after a couple of months of silence.
_SERIES_CLASS_DEFAULTS = {
    "daily": 5,
    "weekly": 10,
    "monthly": 45,
    "quarterly": 130,
}

# Operator override (checked in order). One knob for every series class.
_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_OBS_MAX_LAG_BDAYS",
    "FORECAST_OBS_MAX_LAG_BDAYS",
    "HERMES_OBS_MAX_LAG_BDAYS",
)


def _coerce_date(value: object) -> date | None:
    """Best-effort coerce a ``date`` / ``datetime`` / ISO string to a ``date``."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    # Take the date part of a full ISO timestamp ("2026-06-29T00:00:00Z").
    head = text.replace("Z", "").split("T", 1)[0].split(" ", 1)[0]
    try:
        return date.fromisoformat(head)
    except ValueError:
        return None


def business_days_between(
    start: object, end: object, *, holidays: frozenset[date] = frozenset()
) -> int:
    """Count business days in the half-open interval ``(start, end]``.

    Weekends (Sat/Sun) and any date in ``holidays`` do not count. Returns ``0``
    when ``end <= start``. This is the LAG: how many business days the reference
    date sits ahead of the observation date. A Friday observation read the
    following Monday is ``1`` (only Monday counts; the weekend is skipped).
    """

    start_d = _coerce_date(start)
    end_d = _coerce_date(end)
    if start_d is None or end_d is None or end_d <= start_d:
        return 0
    count = 0
    day = start_d + timedelta(days=1)
    while day <= end_d:
        if day.weekday() < 5 and day not in holidays:
            count += 1
        day += timedelta(days=1)
    return count


def resolve_max_business_days(
    series_class: str = "daily", *, explicit: int | None = None
) -> int:
    """Resolve the ordinary-lag threshold (business days).

    Precedence: an ``explicit`` positive override → an operator env override
    (:data:`_ENV_NAMES`) → the per-``series_class`` default → the daily default.
    """

    if explicit is not None and explicit > 0:
        return explicit
    for name in _ENV_NAMES:
        raw = os.environ.get(name)
        if raw and raw.strip():
            try:
                value = int(raw.strip())
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
    return _SERIES_CLASS_DEFAULTS.get(series_class, DEFAULT_MAX_BUSINESS_DAYS)


def infer_cadence_business_days(dates: list[object]) -> int | None:
    """Median business-day gap between consecutive observations (``None`` < 2).

    Lets a frequency-agnostic consumer (the market-data tape mixes daily and
    monthly FRED series) tell a daily series from a monthly one without knowing
    the series id, so a monthly reading is not wrongly blanked as "stale".
    """

    parsed = [d for d in (_coerce_date(v) for v in dates) if d is not None]
    if len(parsed) < 2:
        return None
    parsed.sort()
    gaps = [
        business_days_between(parsed[i], parsed[i + 1])
        for i in range(len(parsed) - 1)
    ]
    gaps = sorted(g for g in gaps if g > 0)
    if not gaps:
        return None
    return gaps[len(gaps) // 2]


def cadence_aware_max_business_days(
    cadence_bdays: int | None,
    *,
    floor: int = DEFAULT_MAX_BUSINESS_DAYS,
    multiple: int = 3,
) -> int:
    """Excessive-lag threshold scaled to a series' own cadence.

    A daily series (cadence ~1) uses ``floor``; a monthly series (cadence ~21
    business days) tolerates ``multiple`` periods of silence before it is
    "stale", so an ordinary month-old monthly reading is not blanked.
    """

    if cadence_bdays is None or cadence_bdays <= 1:
        return floor
    return max(floor, multiple * cadence_bdays)


@dataclass(frozen=True)
class FreshnessAssessment:
    """The verdict of the missing-observation rule for one series.

    ``status`` is ``"ordinary"`` (use the lagged-latest), ``"excessive"`` (treat
    as missing → ``None`` + staleness note), or ``"unknown"`` (undated).
    """

    status: str
    lag_business_days: int
    as_of: date | None
    max_business_days: int
    note: str

    @property
    def is_missing(self) -> bool:
        """True when the reading must go down the missing-data path (``None``)."""

        return self.status == "excessive"

    @property
    def is_ordinary(self) -> bool:
        """True when the lagged-latest is honest to serve with its own as_of."""

        return self.status == "ordinary"

    @property
    def as_of_iso(self) -> str | None:
        return self.as_of.isoformat() if self.as_of else None


def assess_observation_freshness(
    observation_date: object,
    *,
    as_of_reference: object,
    max_business_days: int | None = None,
    holidays: frozenset[date] = frozenset(),
    label: str = "series",
) -> FreshnessAssessment:
    """Classify a series' newest observation as ordinary / excessive / unknown.

    The honest ``as_of`` is always the observation's OWN date, never
    ``as_of_reference`` ("today"). ``max_business_days`` defaults to
    :data:`DEFAULT_MAX_BUSINESS_DAYS`.
    """

    obs = _coerce_date(observation_date)
    ref = _coerce_date(as_of_reference)
    limit = max_business_days if max_business_days is not None else DEFAULT_MAX_BUSINESS_DAYS
    if obs is None or ref is None:
        return FreshnessAssessment(
            status="unknown",
            lag_business_days=-1,
            as_of=obs,
            max_business_days=limit,
            note=f"{label}: observation date unavailable — cannot age the reading honestly.",
        )
    lag = business_days_between(obs, ref, holidays=holidays)
    as_of_iso = obs.isoformat()
    if lag <= limit:
        note = (
            f"{label}: last known {as_of_iso} ({lag} business-day publication lag, "
            f"ordinary <= {limit}) — use this latest-available reading stamped "
            f"as_of {as_of_iso}; do not fabricate a today-dated row."
        )
        return FreshnessAssessment("ordinary", lag, obs, limit, note)
    note = (
        f"{label}: latest observation {as_of_iso} is {lag} business days stale "
        f"(> {limit} allowed) — treat as MISSING (value None) and flag staleness; "
        f"do not carry the stale reading forward as current."
    )
    return FreshnessAssessment("excessive", lag, obs, limit, note)


def describe_missing_observation_rule(
    max_business_days: int = DEFAULT_MAX_BUSINESS_DAYS,
) -> str:
    """One-paragraph statement of the rule for agent-facing prompts / notes."""

    return (
        "Missing-observation rule (daily official series — FRED DCOILWTICO crude, "
        "EIA spot prices): these publish with a T-1/T-2 lag and carry NO row on "
        "weekends/holidays BY DESIGN. The honest latest value is the newest "
        "AVAILABLE observation carried with ITS OWN observation date as as_of "
        f"(never today). A lag of <= {max_business_days} US business days is an "
        "ORDINARY publication lag: USE the lagged-latest (e.g. \"71.87 as of "
        "2026-06-29\"), do NOT fabricate a today-dated row, and do NOT refuse. A "
        "lag beyond that is EXCESSIVE: treat the series as missing (value None) "
        "and flag staleness."
    )


__all__ = [
    "DEFAULT_MAX_BUSINESS_DAYS",
    "FreshnessAssessment",
    "assess_observation_freshness",
    "business_days_between",
    "cadence_aware_max_business_days",
    "describe_missing_observation_rule",
    "infer_cadence_business_days",
    "resolve_max_business_days",
]
