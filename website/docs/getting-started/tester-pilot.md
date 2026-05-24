---
sidebar_position: 4
title: "Tester Pilot Runbook"
description: "Run a small forecast-desk pilot without overclaiming performance."
---

# Tester Pilot Runbook

Use this runbook for a friendly tester alpha. The goal is to verify that testers can install the fork, operate the CLI forecast desk, create auditable forecasts, run self-checks, and report where the workflow breaks. It is not a benchmark-superiority test.

## Pilot Scope

Run a 2-5 person pilot for one week. Each tester should maintain 3-10 scoreable questions in a domain they understand and should use the ledger as the source of truth for evidence, probabilities, resolutions, scores, and postmortems.

Good tester domains:

- macro, fiscal, energy, policy, software releases, security, weather, public attention, scientific milestones, company filings, or custom CSV/JSON datasets
- questions with clear resolution criteria and plausible evidence updates during the pilot
- at least one short-horizon question that can resolve during or shortly after the pilot

Avoid claiming the system is better than Metaculus, markets, or human superforecasters during the pilot. The readiness gate should keep reporting evidence gaps until enough live scored forecasts and held-out agent-protocol backtests exist.

## Operator Setup

For the current friendly alpha snapshot, give testers the pushed fork branch
directly:

```bash
git clone --branch superforecasting-agent-snapshot \
  https://github.com/teddyjfpender/superforecasting-agent.git \
  superforecasting-agent
cd superforecasting-agent
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[all,dev]"
```

For a future default-branch or release-candidate handoff, use the same setup
shape against the fork URL:

```bash
git clone https://github.com/teddyjfpender/superforecasting-agent.git superforecasting-agent
cd superforecasting-agent
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[all,dev]"
```

Run the acceptance smoke test:

```bash
python3 scripts/forecast_smoke_test.py
```

The smoke output must end with:

```text
[forecast-smoke] forecast smoke test passed
```

It should also report local source-adapter and benchmark counts, an agent-protocol replay run id, and:

```text
[forecast-smoke] readiness_verdict: insufficient_live_evidence
```

That verdict is expected. It means the product is correctly refusing to infer live forecasting superiority from smoke or replay evidence.

## Tester Workflow

Each tester should use a dedicated ledger path:

```bash
export FORECAST_DB="$PWD/.pilot/forecasting-${USER}.db"
mkdir -p .pilot
```

Create a question:

```bash
forecast --db "$FORECAST_DB" new "Will <event> happen by <date>?" \
  --resolution-criteria "Resolved yes if ..." \
  --close-time 2026-06-30T00:00:00Z \
  --domain <domain> \
  --topic <topic>
```

Add at least one manual evidence item:

```bash
forecast --db "$FORECAST_DB" evidence add <id> "Observed evidence or source note." \
  --available-at 2026-05-23T00:00:00Z \
  --claim-type fact \
  --stance context \
  --reliability 0.7 \
  --relevance 0.8
```

Import at least one structured source that fits the question:

```bash
forecast --db "$FORECAST_DB" sources
forecast --db "$FORECAST_DB" import gdelt "query terms" --question <id> --limit 5
forecast --db "$FORECAST_DB" import fred UNRATE --question <id>
forecast --db "$FORECAST_DB" import eia PET.RWTC.M --question <id>
forecast --db "$FORECAST_DB" import treasury v2/accounting/od/avg_interest_rates --question <id>
forecast --db "$FORECAST_DB" import census "2023/acs/acs5?get=NAME,B01003_001E&for=state:*" --question <id>
forecast --db "$FORECAST_DB" import socrata data.cdc.gov/abcd-1234 --question <id>
forecast --db "$FORECAST_DB" import yahoo AAPL --question <id>
forecast --db "$FORECAST_DB" import coingecko bitcoin --question <id>
forecast --db "$FORECAST_DB" import wikipediapageviews en.wikipedia.org/Topic --question <id>
forecast --db "$FORECAST_DB" import githubcommits owner/repo --question <id>
forecast --db "$FORECAST_DB" import githubactions owner/repo --question <id>
forecast --db "$FORECAST_DB" import hackernews "product query" --question <id>
forecast --db "$FORECAST_DB" import reddit "topic query" --question <id>
forecast --db "$FORECAST_DB" import bluesky "topic query" --question <id>
forecast --db "$FORECAST_DB" import mastodon mastodon.social/forecasting --question <id>
forecast --db "$FORECAST_DB" import courtlistener "case or legal query" --question <id>
forecast --db "$FORECAST_DB" import cisakev CVE-2026-0001 --question <id>
forecast --db "$FORECAST_DB" import whogho WHOSIS_000001 --country USA --question <id>
```

Add a base rate and a model run:

```bash
forecast --db "$FORECAST_DB" base-rate <id> \
  --name "Comparable historical cases" \
  --inclusion-criteria "Comparable cases before the forecast date" \
  --base-rate 0.45 \
  --uncertainty 0.12

forecast --db "$FORECAST_DB" model <id> --type bayesian_update \
  --prior 0.45 \
  --likelihood-if-true 0.65 \
  --likelihood-if-false 0.50 \
  --model-version pilot-v1
```

Save a probability update:

```bash
forecast --db "$FORECAST_DB" update <id> \
  --probability 0.55 \
  --confidence 0.6 \
  --method weighted_ensemble \
  --rationale "Base rate plus current evidence moves the probability modestly upward." \
  --as-of 2026-05-23T00:00:00Z
```

Add a watched source and scheduled review:

```bash
forecast --db "$FORECAST_DB" watch add --question <id> gdelt:"query terms"
forecast --db "$FORECAST_DB" schedule add --question <id> \
  --cadence 1d \
  --next-run-at 2026-05-24T09:00:00Z \
  --stale-days 3 \
  --auto-score \
  --auto-postmortem
forecast --db "$FORECAST_DB" self-check --question <id>
forecast --db "$FORECAST_DB" schedule install-cron --schedule "every 1h"
```

For domain/topic learning checks, add one scoped schedule per tester domain:

```bash
forecast --db "$FORECAST_DB" schedule add --domain <domain> --topic <topic> \
  --cadence 1d \
  --next-run-at 2026-05-24T09:00:00Z \
  --stale-days 3 \
  --auto-score \
  --auto-postmortem
forecast --db "$FORECAST_DB" schedule run --due --auto-score --auto-postmortem
forecast --db "$FORECAST_DB" errors --domain <domain> --topic <topic>
forecast --db "$FORECAST_DB" lesson list --scope-type domain --scope-ref <domain>
```

`schedule run` should report `scores_created`, `postmortems_created`, and
`learning_reviews` counts. Those counts tell the operator when a scheduled
self-check changed calibration memory or domain/topic error profiles.

Review the book:

```bash
forecast --db "$FORECAST_DB" list
forecast --db "$FORECAST_DB" review --stale
forecast --db "$FORECAST_DB" alerts
forecast --db "$FORECAST_DB" calibration --by-origin --all
forecast --db "$FORECAST_DB" readiness
forecast --db "$FORECAST_DB" pilot-report
```

When a question resolves:

```bash
forecast --db "$FORECAST_DB" resolve <id> --outcome yes --source "<resolution source>"
forecast --db "$FORECAST_DB" score <id>
forecast --db "$FORECAST_DB" postmortem <id> \
  --what-happened "..." \
  --what-was-expected "..." \
  --missed-evidence "..." \
  --overweighted-evidence "..." \
  --lesson "What should change next time."
forecast --db "$FORECAST_DB" update <id> \
  --probability 0.52 \
  --rationale "New forecast after reviewing active calibration lessons." \
  --use-active-lessons
```

## Tester Feedback

Ask testers to report:

- install and first-run failures
- commands that were hard to discover
- source imports that were missing for their domain
- cases where evidence timestamps or resolution criteria were awkward to represent
- forecast updates that could not cite the right evidence/model/assumption records
- self-check alerts that were noisy, stale, or missing
- calibration/postmortem output that did not help the next forecast

Use the repository's **Forecast Pilot Feedback** issue template for workflow
reports and the **Source Adapter Request** template for missing data feeds,
market priors, benchmark corpora, or resolution sources.

Each pilot issue should include the smoke/tested commit, commands run,
`forecast pilot-report --json`, `forecast readiness --json`, live evidence
counts, and any `forecast pilot-aggregate .pilot/*-export.json --json` output
from shared exports.

Each issue should include enough detail to reproduce the failing workflow:

```text
command:
expected:
actual:
forecast id:
db path or export:
domain/topic:
source adapter involved:
```

Use `forecast export <id>` or `forecast export all` for shareable artifacts when the data is safe to disclose.
Use `forecast pilot-report --json` for a compact machine-readable summary of whether the tester ledger has enough questions, forecast updates, evidence, structured-source imports, scheduled self-checks, scores, and postmortems for the pilot exit criteria.
Use `forecast pilot-bundle --include-export --output .pilot/${USER}-bundle.json` when the tester can safely share a single JSON artifact containing pilot-report, readiness, and export data.
If testers should start from the same unresolved live question book, seed it from a CSV or JSON manifest:

```bash
cp examples/forecasting/live-cohort.example.csv live-cohort.csv
$EDITOR live-cohort.csv
forecast pilot-cohort live-cohort.csv --dry-run --json
forecast pilot-cohort live-cohort.csv --schedule-cadence 1d --schedule-next-run-at 2026-05-25T09:00:00Z
```

Useful manifest columns are `title`, `resolution_criteria`, `probability`,
`rationale`, `domain`, `topics`, `close_time`, `resolution_time`, `as_of`,
`confidence`, and `watch_source`. The example manifest is a template: edit the
questions, dates, probabilities, and watched sources before using it for real
pilot evidence. The command creates prospective live questions and optional
initial live snapshots; it does not import resolved outcomes or prove
forecasting skill.
Operators can aggregate safe tester exports without merging ledgers:

```bash
forecast pilot-aggregate .pilot/*-export.json --json
```

The aggregate counts live scores, source types, domains, postmortems, and remaining collection gaps. It is a collection summary, not a performance-superiority claim.

## Exit Criteria

A pilot build is ready to widen when:

- the smoke test passes on a fresh checkout
- every tester can create, update, review, resolve, score, and postmortem at least one forecast
- every tester can import at least one structured source or explain the missing adapter
- scheduled self-checks create useful alerts without changing active probabilities silently
- `forecast pilot-report` passes, or every remaining gap has an attached issue
- `forecast readiness` still clearly separates smoke/backtest evidence from live superiority evidence
- pilot issues are triaged into source-adapter gaps, CLI ergonomics, ledger model gaps, or documentation gaps

Do not treat the pilot as proof of forecasting skill. The pilot proves that the desk can collect the artifacts needed to measure forecasting skill later.
