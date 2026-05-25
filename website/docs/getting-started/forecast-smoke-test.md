---
sidebar_position: 3
title: "Tester Smoke Test"
description: "Run the local forecast lifecycle before external testing."
---

# Tester Smoke Test

Use this smoke test before handing a build to testers. It exercises the forecast ledger, evidence capture, base rates, model-run records, probability updates, resolution, scoring, postmortem learning, scheduled self-check alerts, pilot-cohort dry-run validation, pilot-report, pilot-bundle and pilot-export aggregation coverage, and a built-in backtest without calling external APIs or an LLM provider.

From the fork checkout:

```bash
source .venv/bin/activate
python3 scripts/forecast_smoke_test.py
```

For an operator handoff gate that also checks fork identity, Python compile
health, focused regression coverage, and whitespace safety, run:

```bash
python3 scripts/tester_handoff_check.py
```

Use `--include-website-build` when you want the handoff gate to also render the
docs site. The website build may still print inherited localized broken-link
warnings, but the handoff gate fails if the build exits nonzero.

The expected output includes a source snapshot line and ends with the pass line:

```text
[forecast-smoke] snapshot: <commit> (<branch>)
[forecast-smoke] forecast smoke test passed
```

A captured passing run from the fork snapshot is checked in at
`docs/plans/2026-05-24-forecast-cli-smoke-transcript.md`. Use it as a
reference for the markers a tester should see; generated ids and temporary
ledger paths will differ.

The smoke ledger should keep `readiness_verdict` at
`insufficient_live_evidence`. Current smoke runs intentionally report four
readiness gaps: live score volume, agent-protocol replay volume, external
resolved-question corpus coverage, and external source-family diversity. That
is the expected non-claim state for a local acceptance test.

## Keep The Smoke Ledger

By default the script uses a temporary ledger and removes it. Keep the database when you want to inspect the records:

```bash
python3 scripts/forecast_smoke_test.py --keep-db
```

Use an explicit ledger path for repeatable tester handoff:

```bash
python3 scripts/forecast_smoke_test.py --db /tmp/superforecasting-agent-smoke.db
```

Inspect it with normal forecast commands:

```bash
python -m superforecasting_agent --db /tmp/superforecasting-agent-smoke.db status
python -m superforecasting_agent --db /tmp/superforecasting-agent-smoke.db list
python -m superforecasting_agent --db /tmp/superforecasting-agent-smoke.db calibration --by-origin --all
python -m superforecasting_agent --db /tmp/superforecasting-agent-smoke.db doctor
python -m superforecasting_agent --db /tmp/superforecasting-agent-smoke.db pilot-report
python -m superforecasting_agent --db /tmp/superforecasting-agent-smoke.db pilot-bundle --include-export
python -m superforecasting_agent --db /tmp/superforecasting-agent-smoke.db performance --last 3
python -m superforecasting_agent --db /tmp/superforecasting-agent-smoke.db readiness
```

## What It Covers

- Creates a binary forecast question with resolution criteria.
- Verifies the forecast source-adapter catalog, including generic data, news, market/crowd, market-price, economic, energy, fiscal, research, weather, policy, security, health, regulatory, software, and public-indicator adapters.
- Verifies the packaged benchmark catalog, including the mini, synthetic, held-out, and public Manifold replay corpora.
- Adds timestamped evidence and stores source reliability and relevance ratings.
- Adds a reference-class base rate.
- Records a Bayesian update model run.
- Appends a cited forecast snapshot.
- Resolves, scores, and postmortems the forecast.
- Creates a calibration lesson from the postmortem.
- Creates a second stale active forecast and verifies self-check alerts.
- Adds and runs a scheduled self-check with learning flags enabled.
- Validates a prospective live `forecast pilot-cohort --dry-run --json` manifest.
- Verifies `forecast doctor --json --require-pilot-ready` reports tester handoff state while preserving live-superiority readiness gaps.
- Verifies `forecast pilot-report --json` reports complete pilot-exit artifacts and no unresolved learned-error review debt for the smoke ledger.
- Verifies `forecast pilot-bundle --include-export` emits one tester handoff packet with pilot-report, readiness, and export data.
- Exports the smoke ledger and verifies `forecast pilot-aggregate` counts the live score from the export packet.
- Runs `builtin:mini-binary` through the local forecast engine.
- Runs a local captured agent-protocol replay from JSONL responses without calling an LLM provider.
- Prints readiness status, evidence gaps, and next actions without making a live superforecasting claim.
- Fails if the smoke ledger incorrectly reports that live-superforecasting evidence is sufficient.

## Useful Options

```bash
python3 scripts/forecast_smoke_test.py --verbose
python3 scripts/forecast_smoke_test.py --skip-backtest
python3 scripts/forecast_smoke_test.py --db /tmp/smoke.db --verbose
```

`--skip-backtest` is useful when you only need to verify lifecycle writes. Keep the default for tester builds because backtesting and readiness reporting are part of the product promise.

## Tester-Ready Bar

A build is ready for friendly testers when:

- `python3 scripts/tester_handoff_check.py` passes on the exact snapshot being handed off
- this smoke test passes on a fresh checkout
- `forecast status --json` reports `Superforecasting Agent`; the smoke script checks this
- `forecast sources --json` lists the built-in adapter set; the smoke script checks this
- `forecast backtest --benchmarks` lists local benchmark datasets; the smoke script checks this
- `forecast pilot-report` can summarize tester workflow artifacts; the smoke script checks this
- `forecast pilot-bundle` can create one shareable handoff packet; the smoke script checks this
- `forecast pilot-aggregate` can count live-score evidence from tester exports; the smoke script checks this
- `examples/forecasting/live-cohort.example.csv` dry-runs through `forecast pilot-cohort --json` before it is edited for a real pilot
- `forecast readiness` clearly distinguishes smoke/backtest evidence from live superforecasting proof; the smoke script checks this
- the tester can create, update, resolve, score, and postmortem one manual question without editing code

This smoke test is not evidence that the agent beats superforecasters. It is a local acceptance check that the forecast desk can preserve the data needed to measure that claim later.
