# Superforecasting Agent MVP Tester Handoff

Date: 2026-05-26

This is the handoff for a friendly tester MVP of the Superforecasting Agent
fork as a CLI-first forecasting desk. It is meant to get real users through the
system and collect workflow feedback. It is not evidence that the agent is
already better than Metaculus, markets, or human superforecasters.

## Install The Snapshot

Use the fork snapshot branch:

```bash
git clone --branch superforecasting-agent-snapshot \
  https://github.com/teddyjfpender/superforecasting-agent.git \
  superforecasting-agent
cd superforecasting-agent
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[all,dev]"
```

After editable install, testers should have these commands:

```bash
forecast
superforecasting-agent
python -m superforecasting_agent status
```

For this handoff, the verified implementation snapshot is:

```text
de7007089b20 Add Kalshi public benchmark corpus
```

Before inviting a new cohort, record the exact commit testers will use:

```bash
git rev-parse --short=12 HEAD
```

In a raw source checkout before installation, use the source-tree launchers:

```bash
./forecast status
./superforecast status
./superforecasting-agent status
python -m superforecasting_agent status
```

## Operator Gate

Run this before inviting testers:

```bash
python3 scripts/tester_handoff_check.py
```

For a quicker lifecycle-only check:

```bash
python3 scripts/forecast_smoke_test.py
```

The expected readiness verdict is still `insufficient_live_evidence`. That is
correct: the MVP verifies the forecast desk loop and guardrails, not live
forecasting superiority.

## Commands To Try

Give each tester a dedicated ledger:

```bash
export FORECAST_DB="$PWD/.pilot/forecasting-${USER}.db"
mkdir -p .pilot
```

Run the forecast lifecycle:

```bash
forecast --db "$FORECAST_DB" new "Will <event> happen by <date>?" \
  --resolution-criteria "Resolved yes if ..." \
  --close-time 2026-06-30T00:00:00Z \
  --domain <domain> \
  --topic <topic>
forecast --db "$FORECAST_DB" evidence add <id> "Observed evidence or source note." \
  --claim-type fact \
  --stance context \
  --reliability 0.7 \
  --relevance 0.8
forecast --db "$FORECAST_DB" base-rate <id> --name "Comparable cases" \
  --inclusion-criteria "Comparable cases before the forecast date" \
  --base-rate 0.45 \
  --uncertainty 0.12
forecast --db "$FORECAST_DB" model <id> --type bayesian_update \
  --prior 0.45 \
  --likelihood-if-true 0.65 \
  --likelihood-if-false 0.50
forecast --db "$FORECAST_DB" update <id> \
  --probability 0.55 \
  --confidence 0.6 \
  --method weighted_ensemble \
  --rationale "Base rate plus current evidence moves the probability modestly upward."
forecast --db "$FORECAST_DB" review
forecast --db "$FORECAST_DB" self-check --question <id>
forecast --db "$FORECAST_DB" schedule add --question <id> --cadence "every 1h" \
  --auto-score \
  --auto-postmortem
forecast --db "$FORECAST_DB" schedule run --due --auto-score --auto-postmortem
forecast --db "$FORECAST_DB" resolve <id> --outcome yes --source "<resolution source>"
forecast --db "$FORECAST_DB" score <id> --baselines
forecast --db "$FORECAST_DB" postmortem <id> \
  --what-happened "..." \
  --what-was-expected "..." \
  --lesson "What should change next time."
forecast --db "$FORECAST_DB" calibration --by-origin --all
forecast --db "$FORECAST_DB" backtest builtin:mini-binary --probability-source dataset
forecast --db "$FORECAST_DB" performance --last 5
forecast --db "$FORECAST_DB" readiness
forecast --db "$FORECAST_DB" pilot-report
forecast --db "$FORECAST_DB" export all --format json --output .pilot/tester-export.json
forecast --db "$FORECAST_DB" import packet .pilot/tester-export.json --conflict skip --json
```

The TUI and dashboard paths to check:

```bash
superforecasting-agent --tui
superforecasting-agent dashboard --no-open
```

In the dashboard, use `/desk` as the primary Forecast Desk route. `/chat`
remains a compatibility alias for older links and plugins.

In the TUI, `/forecast` opens the forecast desk panel and `/schedule`,
`/backtest`, `/calibration`, `/alerts`, `/doctor`, and `/readiness` jump to
common workflow checks.

## Smoke Evidence

Latest consolidated tester handoff evidence ran with a temporary clean ledger on
the implementation tree committed as `de7007089b20`.

It verified:

- `forecast new`, manual evidence, research/evidence capture, base-rate model,
  Bayesian model run, and forecast update.
- Review, resolve, score, postmortem, calibration, and performance reporting.
- Backtest replay on `builtin:mini-binary` with leakage checks passing.
- Suite-scale agent-protocol replay: 465 sanitized prompt packets exported
  across all packaged benchmark corpora and 465 captured protocol responses
  replayed without external model calls.
- External benchmark diversity: the packaged benchmark catalog now includes
  both public Manifold and public Kalshi resolved-market corpora, so smoke
  readiness observes two external source families.
- Scheduled self-check with `--cadence "every 1h"`, alert creation, learning
  review counts, and durable schedule history.
- Source-tree `./forecast`, source-tree `./superforecast`,
  source-tree `./superforecasting-agent`, `python -m superforecasting_agent`,
  and the package-defined `forecast` command path.
- Portfolio export/import packets, including forecast history, evidence,
  schedules, postmortems, calibration lessons, and domain/topic error profiles.
- Dashboard forecast API and TUI forecast panel test coverage.
- The consolidated `python3 scripts/tester_handoff_check.py` gate passed for the
  `de7007089b20` implementation tree with 176 focused tests, the clean smoke
  path, and `git diff --check`; the smoke output reported
  `agent_protocol_prompt_packets: 465`,
  `agent_protocol_suite_scored_cases: 465`, `performance_runs: 6`,
  `readiness_gaps: 1`, `readiness_agent_protocol_scores: 465`, and
  `doctor_status: benchmark_evidence_ready_live_claim_unproven`.
- The dashboard Forecast Desk route now uses forecast-native translation keys
  (`forecastDesk`, `resumeInDesk`) while preserving `/chat` as a compatibility
  route alias.
- The legacy `./hermes --help` source-tree launcher now routes through the
  forecast-first wrapper, prints a compatibility warning, and shows the forecast
  lifecycle help without requiring inherited optional runtime dependencies.

This finalization pass also ran a manual clean-ledger source-tree smoke at
`/private/tmp/sfa-smoke-20260526-0250.db` through `./forecast --db ...`:
`new`, `evidence add`, `research`, `base-rate`, `model`, `update`, `review`,
`resolve`, `score`, `postmortem`, `calibration --by-origin`, `backtest
builtin:mini-binary --probability-source forecast-engine`, `performance
--live`, `schedule add`, `schedule run --due --auto-score --auto-postmortem`,
`alerts`, and `status`.

## Feedback To Collect

Ask testers for:

- install and first-run failures
- commands that were hard to discover
- source adapters missing for their domain
- awkward evidence, timestamp, or resolution-criteria workflows
- forecast updates that could not cite the right evidence/model/assumption
- noisy, stale, or missing self-check alerts
- whether postmortems and calibration lessons changed their next forecast
- dashboard/TUI issues that slow down reviewing the book

Each report should include the tested commit, commands run, forecast id, domain
and topic, `forecast pilot-report --json`, `forecast readiness --json`, and any
export or bundle path.

## Known Limits

- The MVP is tester-ready for workflow feedback, not performance claims.
- Many inherited Hermes module names and compatibility entry points remain.
- `forecast` exists on `PATH` after package installation; raw source checkouts
  can use `./forecast`, `./superforecasting-agent`, or
  `python -m superforecasting_agent`.
- Raw source checkouts can run the forecast desk without installing every
  compatibility extra. Inherited runtime commands such as `tools`, `dashboard`,
  `setup`, `model`, `gateway`, and chat/TUI should be tested after the editable
  install command above.
- Scheduled checks create alerts, scores, postmortems, lessons, and error
  profiles where configured, but they do not silently change active forecast
  probabilities.
- Live superiority requires accumulated prospective forecasts, resolutions,
  baseline comparisons, and held-out replay evidence over time.
