---
sidebar_position: 1
title: "Quickstart"
description: "Create a scoreable forecast, add evidence, update probability, review, resolve, score, and learn from the result."
---

# Quickstart

This guide gets you from a fresh checkout to a working forecast desk. The goal is not to start a generic chat. The goal is to create a scoreable question, preserve evidence, update an explicit probability, and leave an audit trail the system can score later.

## 1. Install From This Fork

```bash
git clone <this-fork-url> superforecasting-agent
cd superforecasting-agent
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[all,dev]"
```

For inherited installer details and platform notes, see [Installation](./installation.md).

Before handing a build to testers, run the local [Tester Smoke Test](./forecast-smoke-test.md):

```bash
python3 scripts/forecast_smoke_test.py
```

For a small alpha, use the [Tester Pilot Runbook](./tester-pilot.md) after the smoke test passes.

## 2. Open The Forecast Desk

```bash
forecast
```

Equivalent fork-native entrypoints:

```bash
superforecasting-agent
python -m superforecasting_agent status
```

The legacy `hermes` entrypoint remains available during the fork transition, but bare invocation opens the forecast desk.

## 3. Create A Scoreable Question

```bash
forecast new "Will the bill pass committee by 2026-06-15?" \
  --resolution-criteria "Resolved yes if the committee reports the bill by 2026-06-15." \
  --close-time 2026-06-15T00:00:00Z \
  --domain policy \
  --topic legislation
```

Good forecast questions need:

- a concrete title
- resolution criteria
- an outcome space
- an as-of timestamp for probability updates
- a close or resolution time when available
- a source or process that can resolve the outcome

## 4. Add Evidence

Manual note:

```bash
forecast evidence add <id> "Sponsor count increased from 4 to 9." \
  --available-at 2026-05-20T00:00:00Z \
  --claim-type fact \
  --stance increases
```

Import from public sources:

```bash
forecast import gdelt "committee bill sponsor count" --question <id> --limit 5
forecast import fred UNRATE --question <id>
forecast import yahoo AAPL --question <id>
forecast import sec 0000320193 --question <id>
forecast import arxiv "cat:cs.AI AND forecasting" --question <id>
forecast import openalex "forecasting calibration" --question <id>
```

Attach market or crowd baselines without treating them as the agent's forecast:

```bash
forecast import manifold <slug-or-url> --question <id>
forecast import polymarket <slug-or-url> --question <id>
forecast import kalshi <ticker-or-url> --question <id>
forecast import metaculus <id-or-url> --question <id>
```

## 5. Estimate Base Rates And Run Models

```bash
forecast base-rate <id> --name "committee passage for similar bills" \
  --inclusion-criteria "Comparable bills in the last 5 sessions" \
  --base-rate 0.52 \
  --uncertainty 0.08 \
  --notes "42 of 80 comparable bills passed committee."
```

```bash
forecast model <id> --type bayesian_update \
  --prior 0.52 \
  --likelihood-if-true 0.70 \
  --likelihood-if-false 0.50 \
  --model-version quickstart-v1
```

## 6. Save A Probability Update

```bash
forecast update <id> \
  --probability 0.63 \
  --confidence 0.68 \
  --method weighted_ensemble \
  --rationale "Base rate is moderate; new sponsors and calendar timing move probability upward." \
  --as-of 2026-05-21T00:00:00Z
```

Every update is append-only. Past forecasts are corrected with explicit correction records rather than silently edited.

## 7. Review And Watch Sources

Find stale or urgent work:

```bash
forecast review --stale
forecast review --domain policy
forecast alerts
```

Watch sources for future self-checks:

```bash
forecast watch add --question <id> gdelt:"committee bill sponsor count"
forecast watch add --question <id> openalex:"forecasting calibration"
forecast watch add --question <id> manifold:<slug>
```

Run a self-check:

```bash
forecast self-check --question <id>
```

Schedule recurring checks:

```bash
forecast schedule add --question <id> \
  --cadence 1d \
  --next-run-at 2026-05-22T09:00:00Z \
  --auto-score \
  --auto-postmortem
```

Automatic learning writes are opt-in. Scheduled checks may create alerts, scores, and postmortem learning records when configured, but they do not silently change active forecast probabilities.

## 8. Resolve, Score, And Postmortem

```bash
forecast resolve <id> \
  --outcome yes \
  --source "https://example.gov/committee/report"
```

```bash
forecast score <id>
```

```bash
forecast postmortem <id> \
  --what-happened "The committee reported the bill earlier than expected." \
  --what-was-expected "I expected calendar pressure to slow the vote." \
  --overweighted-evidence "Calendar congestion." \
  --missed-evidence "Leadership scheduling signal." \
  --lesson "For this committee, leadership scheduling hints deserve more weight than generic calendar congestion."
```

Postmortems can create tentative calibration lessons. Forecast updates cite only active, non-invalidated lessons.

## 9. Check Calibration And Backtests

```bash
forecast calibration --by-origin --all
forecast errors
forecast backtest --benchmarks
forecast backtest --all-benchmarks --probability-source forecast-engine
forecast performance --last 5 --json
```

Backtests are time-aware. Evidence after the simulated forecast time is excluded unless it is part of the resolution step.

## 10. Use The TUI

```bash
superforecasting-agent --tui
```

Useful TUI shortcuts:

```text
/forecast
/new-forecast
/base-rate
/update-forecast
/resolve
/score
/postmortem
/review
/alerts
/calibration
/lessons
/backtest
/schedule
/performance
```

`/forecast <subcommand>` still routes to the full forecast CLI for advanced workflows.

## 11. Configure Models And Tools

```bash
superforecasting-agent model
superforecasting-agent tools
superforecasting-agent setup
```

The forecast desk keeps inherited provider routing and tool execution, but the default tool exposure is narrowed for forecasting workflows.

## What Success Looks Like

- `forecast status` shows a forecast desk, not a generic assistant session.
- `forecast list` shows your active question.
- `forecast show <id>` includes evidence, assumptions, reference classes, model runs, forecast history, scores, and postmortems.
- `forecast review --stale` surfaces work that needs attention.
- `forecast calibration --by-origin --all` separates live forecasts, backtests, and imported baselines.
- `forecast backtest --benchmarks` runs local replay corpora without live APIs.
