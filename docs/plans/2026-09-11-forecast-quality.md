# Forecast semantics, prospective operations and release verification

Branch: `codex/forecast-quality-release`; release candidate: 0.22.0.
This record distinguishes implementation, operational evidence and forecasting
performance. A working trial is not evidence that its lessons improve accuracy.

## Implemented boundaries

- Acquisition labels stay in provenance; source categories or explicit operator
  review determine semantic domains. `forecast domain` checks the expected old
  value and records history without rewriting snapshots or eligibility.
- `forecast trial preflight` records a bounded known-answer provider call. Live
  execution requires a matching receipt younger than 30 minutes. Incomplete,
  malformed, interrupted and failed arms remain visible and cannot be rerolled.
  Trial identity includes measurement, applicability and censoring policy files.
- `forecast facts bind-source` supports versioned NWS temperature and USGS
  magnitude contracts. Both verify entity and time window; NWS requires Celsius
  and verified QC, while USGS requires an explicit magnitude scale and preserves
  event time separately from revision time. Archive integrity and freshness remain
  mandatory. A station observation never asserts a completed daily maximum.
- `forecast new --outcome-type numeric --units days --censor-at 6` declares the
  threshold before forecasting. A resolution may be an exact value or JSON such
  as `{"kind":"right_censored","lower_bound":6,"inclusive":true,
  "observed_through":"2026-09-11T00:00:00Z","units":"days"}`.
  The ledger scores the declared threshold event with Brier loss for both exact
  and censored observations. This is a proper score of that identifiable event,
  not a full-distribution CRPS or an invented exact duration. Exports preserve
  the typed outcome; the desk states the scoring limitation. Existing questions
  without a declared contract cannot acquire censoring silently at settlement.
- Shared model configuration preserves raw environment references and unrelated
  settings, clears stale provider credentials and reports failed persistence.
  Gateway command hooks have separate ownership and rewritten targets receive
  a fresh access check. Compatibility imports and existing homes remain supported.

## Verified locally

- Forecasting plus targeted runtime/gateway regression run: 3,482 passed,
  3 skipped, 334.66 seconds. Subsequent trial/source contract run: 22 passed.
- Real PTY boot/stream/cancel/resume/resize and bridge run: 24 passed.
- Extended configured-chat run: 5 passed, including 18 Unicode turns across
  three process lifetimes with resizing and exact-once durable user messages.
- Built 0.22.0 wheel: isolated fresh installation and upgrade from 0.21.2 both
  complete create → research → update → resolve → score → postmortem through
  the installed CLI. Prior question, evidence and configuration survive upgrade.
- Live NWS and USGS responses captured through the installed CLI in a disposable
  profile satisfy the new contracts; receipts retain URLs, hashes and timestamps.
- TUI type-check, focused forecast-panel tests, Ruff, generated references and
  the bounded Impeccable detector pass. Detector findings: none.

Local operational artifacts are in `/tmp/forecast-quality-installed-022/`.
Durable live receipts are under the active home's
`reports/2026-09-11-forecast-quality/`. No credentials are committed.

## Live ledger and trial

An online SQLite backup preceded writes. Three reviewed election questions now
use `politics` while retaining `market_nightly` acquisition provenance. Four
political lessons now require their stated US-primary conditions; prior guidance
and the reason for narrowing are retained in their scope-review metadata.
Unknown conditions do not grant applicability.

Trial `lt_7714526e4158` enrolls eight existing questions. US midterms are one
cluster; AI infrastructure is another. Company and state variants do not inflate
independence. Four treatment arms receive a distribution-scoreability process
lesson. This limited library coverage cannot establish broad judgment improvement.
The frozen threshold remains 20 clusters. Response budget: 8,192 tokens per arm,
16 calls maximum (131,072 response tokens); provider: Gemini 3 Flash Preview.
The known-answer probe completed successfully and includes token usage.

## Release gates still pending

- Final CI receipts for the PR, including the new Windows/Linux/macOS installed
  lifecycle matrix. macOS evidence above is not evidence for other platforms.
- Android/Termux access and credential-dependent Daytona, Modal, web-search and
  Home Assistant integrations. Their credentials are absent; no fake success or
  substitute fixture is counted as a live integration.
- Formal tag/release workflow publication and artifact/image verification.
- Prospective outcomes and enough independent clusters for an accuracy estimate.

Schema authorities: [NWS API](https://www.weather.gov/documentation/services-web-api)
and [USGS detail format](https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson_detail.php).
