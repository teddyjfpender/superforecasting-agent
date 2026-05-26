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
superforecasting-agent desk
python -m superforecasting_agent status
```

For this handoff, the latest full tester gate was verified on:

```text
4c58ac5ef10d Refresh tester handoff for required autopilot sources
```

The current moving `superforecasting-agent-snapshot` branch includes the
forecast question shortcut pass, the fork-native `superforecasting-agent desk`
support-session alias, required-source autopilot guardrails, and the
tester-handoff documentation refresh. Rerun the operator gate before pinning a
newer cohort hash.

A post-cleanup lifecycle smoke passed on `ad3a3052c92f` using
`python3 scripts/forecast_smoke_test.py`, including forecast creation,
evidence, base-rate/model/update, review, scoring/postmortem, schedule/autopilot
checks, packet import/export, backtest replay, and the expected
`insufficient_live_evidence` readiness guard.

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

If the default agent home is not writable in a restricted shell or sandbox, pass
an explicit ledger path instead:

```bash
mkdir -p .pilot
python -m superforecasting_agent --db "$PWD/.pilot/forecasting-smoke.db" status
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
forecast --db "$FORECAST_DB" autopilot enable <id> \
  --source "<adapter>:<source>" \
  --required-source "<critical-adapter>:<source>" \
  --cadence "1d" \
  --mode propose \
  --quiet-if-unchanged
forecast --db "$FORECAST_DB" autopilot run <id>
forecast --db "$FORECAST_DB" autopilot proposals <id>
forecast --db "$FORECAST_DB" autopilot approve <proposal-id>
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

In the TUI, `/questions` is the fastest current-question view. It shows numbered
forecast rows with headline probability, delta, close date, evidence count, and
freshness; selecting a numbered row or running `/questions 1` opens the first
row's full forecast details without requiring the tester to copy a forecast id.
`/questions <words>` and `/find <words>` search active forecasts and
review-queue items by title, topic, or domain, while `/open <row|id|words>`
opens one unambiguous match. For quick evidence and probability maintenance,
testers can run `/evidence-for <row|words> -- <note>` or
`/update-for <row|words> -- --probability <p> --rationale <why>` without
copying the forecast id. `/book` and `/qbook` remain compatibility aliases.
`/forecast` opens the broader forecast desk panel; active rows, wide-rail
watchlist rows, the header primary action, and concrete `desk actions` entries
are selectable in mouse-enabled terminals. Placeholder command examples remain
display-only until filled in. `/schedule`, `/backtest`, `/calibration`,
`/alerts`, `/doctor`, and `/readiness` jump to common workflow checks.

In the dashboard Forecasts page, active forecast rows are selectable. Clicking
or pressing Enter/Space on a row opens a detail panel with the same headline
values, freshness, alert state, and copyable follow-up commands.

To test source breadth and RSS/news triage, use a question that should have
mixed quantitative and textual inputs:

```bash
forecast --db "$FORECAST_DB" new "Will CPI inflation exceed consensus next month?" \
  --resolution-criteria "Resolved by the next BLS CPI release." \
  --domain macro \
  --topic inflation \
  --source-plan
forecast --db "$FORECAST_DB" sources --question <id>
forecast --db "$FORECAST_DB" sources --question <id> --json
forecast --db "$FORECAST_DB" watch add \
  --question <id> \
  --source-type rss \
  rss:https://www.bls.gov/feed/news_release/cpi.rss \
  --keyword CPI \
  --keyword inflation \
  --keyword gasoline \
  --keyword shelter \
  --materiality high \
  --cadence "1h"
forecast --db "$FORECAST_DB" watch check --question <id>
forecast --db "$FORECAST_DB" sources --question <id> --search-watched
forecast --db "$FORECAST_DB" sources --question <id> --search-watched --capture-candidates
forecast --db "$FORECAST_DB" import news https://www.bls.gov/feed/news_release/cpi.rss \
  --question <id> \
  --keyword CPI \
  --keyword gasoline \
  --materiality high \
  --direction upward \
  --affected-component energy
```

RSS/news imports and watched-stream captures are evidence-candidate inputs.
They should not change a probability unless the tester runs an explicit
`forecast update`.

For a deterministic local autopilot check, use a file source rather than a live
external adapter:

```bash
mkdir -p .pilot
printf "initial release\n" > .pilot/source.txt
printf "initial critical release\n" > .pilot/critical-source.txt
forecast --db "$FORECAST_DB" autopilot enable <id> \
  --source "$PWD/.pilot/source.txt" \
  --required-source "$PWD/.pilot/critical-source.txt" \
  --cadence "1d" \
  --mode propose
forecast --db "$FORECAST_DB" autopilot run <id>
printf "revised release\n" > .pilot/source.txt
printf "revised critical release\n" > .pilot/critical-source.txt
forecast --db "$FORECAST_DB" autopilot run <id> \
  --proposed-probability 0.61 \
  --rationale "Source revision changes the forecast."
forecast --db "$FORECAST_DB" autopilot proposals <id>
```

Use `--required-source` for feeds that must be fresh before the agent proposes
a probability update. If a required source fails, autopilot records a
high-severity alert, marks the run failed, preserves source-snapshot diagnostics,
and blocks the refresh proposal instead of updating from partial evidence.

Agent-driven flows can call the same maintenance loop through the
`forecast_ledger` tool actions: `source_plan`, `import_source_evidence`,
`add_watched_source`, `enable_autopilot`, `autopilot_status`,
`run_autopilot`, `list_forecast_update_proposals`,
`approve_forecast_update_proposal`, and
`reject_forecast_update_proposal`.

## Smoke Evidence

Latest consolidated tester handoff evidence ran with a temporary clean ledger on
the implementation tree committed as `4c58ac5ef10d`.

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
- Autopilot maintenance with watched file sources, required-source guardrails,
  source snapshots, material-change detection, pending proposals, approval into
  append-only forecast snapshots, and the same actions exposed through the
  model-facing `forecast_ledger` tool.
- RSS/source breadth with source planning, watched-stream search, optional
  candidate capture, filtered imports, and no silent probability mutation.
- Source-tree `./forecast`, source-tree `./superforecast`,
  source-tree `./superforecasting-agent`, `python -m superforecasting_agent`,
  and the package-defined `forecast` command path.
- Portfolio export/import packets, including forecast history, evidence,
  schedules, postmortems, calibration lessons, and domain/topic error profiles.
- Dashboard forecast API and TUI forecast panel test coverage.
- Forecast question shortcut coverage for `/questions`, `/questions <row>`,
  `/questions <words>`, `/find`, `/open`, `/evidence-for`, `/update-for`,
  `/book`, numbered TUI drill-down, classic CLI drill-down/search/edit
  resolution, and dashboard row selection with a detail panel.
- The consolidated `python3 scripts/tester_handoff_check.py` gate passed for the
  implementation tree with 181 focused tests, the clean smoke path, and
  `git diff --check`; the smoke output reported 52 source adapters,
  5 benchmark datasets, `pilot_report_checks: 9/9`,
  `packet_import_questions: 3`, `pilot_aggregate_live_scores: 1`,
  `agent_protocol_prompt_packets: 465`,
  `agent_protocol_suite_scored_cases: 465`, `performance_runs: 6`,
  `readiness_gaps: 1`, `readiness_agent_protocol_scores: 465`,
  `live_baseline_comparisons: 1`, and
  `doctor_status: benchmark_evidence_ready_live_claim_unproven`.
- The dashboard Forecast Desk route now uses forecast-native translation keys
  (`forecastDesk`, `resumeInDesk`) while preserving `/chat` as a compatibility
  route alias.
- The legacy `./hermes --help` source-tree launcher now routes through the
  forecast-first wrapper, prints a compatibility warning, and shows the forecast
  lifecycle help without requiring inherited optional runtime dependencies.

This finalization pass also ran a manual clean-ledger source-tree smoke at
`/private/tmp/sfa-mvp-smoke.db` through `python -m superforecasting_agent --db
...` and `./forecast --db ...`: `new`, `research`, `base-rate`, `model`,
`update`, `review`, `list`, `autopilot enable` with `--required-source`,
`autopilot run`, `autopilot approve`, `schedule add`, `schedule run --due`,
`resolve`, `score`, `postmortem`, `calibration --all`, `backtest --benchmarks`,
`backtest builtin:mini-binary --probability-source naive`, `alerts`, and
`status`. The smoke emitted one live score with `mean_brier: 0.129600`, one
approved autopilot proposal, two watched sources with one required source, and
five scored benchmark replay cases with leakage checks passing.

## Feedback To Collect

Ask testers for:

- install and first-run failures
- commands that were hard to discover
- source adapters missing for their domain
- awkward evidence, timestamp, or resolution-criteria workflows
- forecast updates that could not cite the right evidence/model/assumption
- noisy, stale, or missing self-check alerts
- whether postmortems and calibration lessons changed their next forecast
- dashboard/TUI issues that slow down reviewing the question book

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
- Autopilot is now available as an autonomous maintenance harness around
  watched sources, scheduled reviews, materiality checks, proposals, and
  guardrails. Use `--mode propose` for tester runs; `auto-commit` is guarded but
  should not be treated as proven live forecasting skill.
- Live superiority requires accumulated prospective forecasts, resolutions,
  baseline comparisons, and held-out replay evidence over time.
