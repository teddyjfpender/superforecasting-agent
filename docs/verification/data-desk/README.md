# Global data desk qualification

This directory records evidence for catalog admission. A successful sample request
is narrower than full provider or platform qualification. It does not establish
settlement authority.

## Current evidence

[Initial live probes](2026-09-14-initial-probes.json) exercised one catalog series
per new provider through `MarketDataService` on macOS, using an isolated worktree.
World Bank, Eurostat, ECB and Open-Meteo returned numeric values and dated history.
The BCB sample failed because SGS permits at most **20** values on the `ultimos`
endpoint. The adapter now requests 20; the subsequent sample passed and excludes future-effective dates from current observations.

Direct urllib probes initially failed certificate validation for Eurostat and ECB.
An explicit trusted CA bundle succeeded for ECB, and both endpoints succeeded
through the existing httpx dependency's default verified transport. No certificate
verification was disabled. This is unrelated to the historical native SSL crash.

IMF DataMapper returned HTTP 403 from this environment during discovery. Its
adapter is implemented using the existing parser, but is not included in the
starter manifest until access and measurement qualification are complete.

## Admission checklist

For each series family, retain a source response fixture and verify:

- Canonical source and series/entity identity, dimensions and units.
- Observation period, release/revision meaning, and unknown publication times.
- Missing, nonnumeric, conflicting duplicate and out-of-order measurements.
- Forecast versus observation versus estimate/reanalysis classification.
- Access requirements, documented quotas and useful dated history.
- Behavior on invalid queries, transport failures and authentication errors.

The current 163-series starter is a **candidate manifest**, not a declaration that
all series have passed qualification. Broader provider scope remains in the
[implementation plan](../../plans/2026-09-14-global-data-desk.md).


## Expanded live checks

[Provider samples](2026-09-14-provider-samples.json) cover World Bank, Eurostat,
ECB, BCB, ABS, BIS, OECD, SingStat, IBGE, all three Open-Meteo datasets, and NWS.
The NWS follow-up removed an unsupported `limit` query parameter; truncation is
now tracked locally. Each sample returned data after that fix.

[Full starter probe](2026-09-14-starter-probe.json) exercised every candidate row.
It exposed an obsolete Eurostat unemployment binding (age and euro-area codes)
and a World Bank timeout that discarded its whole batch. Those findings led to
corrected bindings and independently cached provider request groups. This receipt
records the failures before those fixes; it must not be presented as a passing
qualification run.

## Corrected follow-ups and setup

[World Bank follow-up](2026-09-14-starter-followup.json) returned all 50 country
series. [Current Eurostat bindings](2026-09-14-eurostat-current.json) returned all
12 European indicators after migrating the obsolete HICP dataset.
[CLI walkthrough](2026-09-14-cli-walkthrough.json) uses real subprocesses and a
temporary profile: empty survives restart, preview matches apply, and applying
the same starter twice leaves identical configuration. No live profile is used.

The [qualification scope](qualification.md) distinguishes usable display coverage
from conditional expansion and settlement authority.
