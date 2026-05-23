---
sidebar_position: 15
title: "Forecast Automation Templates"
description: "Ready-to-use templates for forecast review, source watching, backtesting, scoring, and calibration learning."
---

# Forecast Automation Templates

Copy-paste recipes for running Superforecasting Agent as a command-line forecasting desk. These templates are deliberately question-agnostic: use them for macro, politics, science, markets, policy, business, product, sports, legal, regulatory, or operational-risk questions.

The common pattern is:

1. Keep forecast state in the ledger.
2. Watch evidence sources and close dates.
3. Trigger review when a belief may be stale.
4. Score resolved forecasts.
5. Write postmortems and promote calibration lessons.
6. Reuse those lessons during future forecast updates.

:::tip Forecast-first automation
Prefer `superforecasting-agent schedule`, `watch`, `alerts`, `backtest`, and `performance` when the work should touch the forecast ledger. Use inherited `cron`, webhook, and `send` commands for delivery glue, external event triggers, or script output.
:::

## Trigger Types

| Trigger | Use it for | Command surface |
|---------|------------|-----------------|
| Scheduled self-check | Stale forecast review, scoring, postmortems, domain learning | `superforecasting-agent schedule` |
| Watched source | Source-change alerts for URLs, feeds, data series, markets, papers, filings | `superforecasting-agent watch` |
| Model cron | A scheduled model prompt that researches, summarizes, or routes work | `superforecasting-agent cron` |
| Script output | Deterministic shell or Python checks that notify humans | `superforecasting-agent send` |
| Webhook | External systems that POST events into the desk | `superforecasting-agent webhook` |

## Operating Rules

- Every probability update should be append-only via `superforecasting-agent update`.
- Every material source should be captured as evidence, a source snapshot, a model run, or a reference-class record.
- Scheduled jobs should create alerts or ledger records, not silently overwrite beliefs.
- Auto-scoring and auto-postmortem jobs are useful only when resolution criteria and resolver sources are explicit.
- Benchmark imports are useful calibration data, but the product should not revolve around any single tournament or platform.

## Standing Desk Loop

### Install the self-check bridge

Use this when you want scheduled ledger maintenance without writing a custom cron prompt.

```bash
superforecasting-agent schedule install-cron \
  --schedule "every 1h" \
  --name "Forecast self-check" \
  --deliver local \
  --auto-score \
  --auto-postmortem
```

This installs a cron bridge that runs due forecast schedules, creates alerts, scores resolved questions where possible, and creates postmortem work when configured.

### Add a portfolio review schedule

Use a portfolio when you want a single recurring review over a book of related questions.

```bash
superforecasting-agent schedule add \
  --portfolio active-desk \
  --cadence "every 6h" \
  --next-run-at "2026-05-22T14:00:00Z" \
  --trigger-reason "standing active forecast review" \
  --auto-score \
  --auto-postmortem
```

Check what will run:

```bash
superforecasting-agent schedule list
superforecasting-agent schedule run --auto-score --auto-postmortem
superforecasting-agent alerts
```

## Daily Review Templates

### Morning stale forecast review

Use this for human-readable daily triage. It should identify work, not manufacture ungrounded probability changes.

```bash
superforecasting-agent cron create "0 8 * * *" \
  "Run the morning forecast review.

1. Run: superforecasting-agent review --stale --last 1d
2. Run: superforecasting-agent alerts
3. For each forecast that needs work:
   - Explain why it is stale or alerted
   - List the next command to run
   - Do not update probability unless new cited evidence is captured
4. If no forecasts need work, respond with [SILENT]." \
  --name "Morning forecast review" \
  --deliver telegram
```

### End-of-day belief-change digest

Use this when you want a concise audit of what moved during the day.

```bash
superforecasting-agent cron create "0 18 * * 1-5" \
  "Create an end-of-day forecast desk digest.

1. Run: superforecasting-agent list --status active --limit 50
2. Run: superforecasting-agent scores --all
3. Identify questions updated today, alerts still open, and forecasts due before tomorrow.
4. For each updated forecast, include:
   - Question id
   - Current probability or value
   - Direction of movement if visible
   - Evidence or model references that justified the change
5. Keep the digest under 500 words. If nothing changed, respond with [SILENT]." \
  --name "Forecast desk digest" \
  --deliver slack
```

### Confidence audit

Use this to catch forecasts that are too vague or too confident for their evidence base.

```bash
superforecasting-agent cron create "0 11 * * 2,5" \
  "Run a confidence audit.

1. Run: superforecasting-agent review --confidence-above 0.85 --last 14d
2. Run: superforecasting-agent review --confidence-below 0.15 --last 14d
3. For each extreme forecast, check whether it has recent evidence, a reference class, and a clear resolution source.
4. Flag any forecast whose confidence appears unsupported.
5. Do not change probabilities. Recommend research or update commands only." \
  --name "Confidence audit" \
  --deliver telegram
```

## Watched Source Templates

### Watch a question-specific news stream

Use watched sources for external changes that should create an alert. The alert tells the desk what to research next.

```bash
superforecasting-agent watch add "gdelt:semiconductor export controls" \
  --question fq_123456789abc \
  --source-type gdelt

superforecasting-agent watch check --question fq_123456789abc
superforecasting-agent alerts
```

When the alert is meaningful, import the new evidence and update only if it moves the probability:

```bash
superforecasting-agent import gdelt "semiconductor export controls" \
  --question fq_123456789abc \
  --limit 10 \
  --claim-type fact

superforecasting-agent update fq_123456789abc \
  --probability 0.42 \
  --rationale "Updated after new export-control reporting changed the near-term policy odds." \
  --evidence-ref ev_123456789abc \
  --require-citations \
  --use-active-lessons
```

### Watch macroeconomic data releases

Use this for CPI, unemployment, rates, industrial production, or other time-series data.

```bash
superforecasting-agent watch add "fred:CPIAUCSL" \
  --domain macro \
  --topic inflation \
  --source-type fred

superforecasting-agent watch add "bls:CUUR0000SA0" \
  --domain macro \
  --topic inflation \
  --source-type bls
```

Run the checks from the scheduler or manually:

```bash
superforecasting-agent watch check --domain macro --topic inflation
superforecasting-agent self-check --domain macro --topic inflation --stale-days 3
```

### Watch papers, filings, or market pages

Use source prefixes to make the watch type explicit.

```bash
superforecasting-agent watch add "arxiv:AI safety evaluations" \
  --topic ai-safety \
  --source-type arxiv

superforecasting-agent watch add "sec:0000320193" \
  --domain equities \
  --topic apple \
  --source-type sec

superforecasting-agent watch add "polymarket:https://polymarket.com/event/example-market" \
  --question fq_abcdef123456 \
  --source-type polymarket
```

Review open alerts before changing any forecast:

```bash
superforecasting-agent alerts
superforecasting-agent show fq_abcdef123456
```

## Backtesting And Benchmark Templates

### Weekly backtest suite

Use this to measure the local probability engine and calibration memory on held-out cases.

```bash
superforecasting-agent cron create "0 7 * * 1" \
  "Run the weekly forecast backtest review.

1. Run: superforecasting-agent backtest --all-benchmarks --probability-source forecast-engine
2. Run: superforecasting-agent performance --last 10
3. Run: superforecasting-agent calibration --by-origin
4. Summarize:
   - Mean Brier and log score trend
   - Which domains or horizons underperformed
   - Whether active calibration lessons helped or hurt
   - One concrete change to test next week
5. Keep the report under 700 words." \
  --name "Weekly forecast backtest" \
  --deliver slack
```

### Import an external benchmark without making it the product center

Use this when a public platform has useful resolved questions. The imported data becomes one benchmark source among many.

```bash
superforecasting-agent import benchmark manifold:resolved \
  --name "Manifold resolved sample" \
  --description "Resolved binary public-market questions for calibration comparison" \
  --limit 200

superforecasting-agent import benchmark metaculus:resolved \
  --name "Metaculus resolved sample" \
  --description "Resolved binary public questions for benchmark comparison" \
  --limit 200

superforecasting-agent backtest --benchmarks
```

Run the imported dataset by id when the import command prints it:

```bash
superforecasting-agent backtest imported:bench_123456789abc \
  --probability-source forecast-engine

superforecasting-agent performance --dataset "Metaculus"
```

### Compare probability sources

Use this when you want to see whether the forecast engine is beating naive, stored dataset probabilities, or an explicit baseline ensemble.

```bash
superforecasting-agent backtest example:binary-calibration \
  --probability-source naive

superforecasting-agent backtest example:binary-calibration \
  --probability-source baseline-ensemble

superforecasting-agent backtest example:binary-calibration \
  --probability-source forecast-engine

superforecasting-agent performance --last 20
```

## Resolution And Learning Templates

### Resolve, score, and postmortem a question

Use this whenever a forecast resolves. The postmortem is the main path by which the desk learns from mistakes.

```bash
superforecasting-agent resolve fq_123456789abc \
  --outcome yes \
  --source "https://example.com/final-result" \
  --resolver-type source_adapter \
  --status confirmed \
  --confirmed-by "official result feed"

superforecasting-agent score fq_123456789abc

superforecasting-agent postmortem fq_123456789abc \
  --summary "The event occurred earlier than expected." \
  --what-happened "The regulator approved the rule before the close date." \
  --what-was-expected "The prior forecast expected a longer review cycle." \
  --missed-evidence "The agency calendar already had a vote window." \
  --overweighted-evidence "Overweighted historical delay rates from older administrations." \
  --base-rate-error "Reference class mixed high-salience and routine approvals." \
  --lesson "For this domain, separate routine approvals from controversial rulemakings before applying delay base rates." \
  --calibration-adjustment-json '{"scope_type":"domain","scope_ref":"policy","status":"candidate","confidence":0.7}'
```

Review and promote lessons:

```bash
superforecasting-agent lesson list
superforecasting-agent lesson status cl_123456789abc --status active --confidence 0.8
```

### Scheduled domain learning

Use this when a domain has enough resolved forecasts to justify recurring error-profile updates.

```bash
superforecasting-agent schedule add \
  --domain macro \
  --cadence "every 1d" \
  --next-run-at "2026-05-23T06:00:00Z" \
  --trigger-reason "domain calibration and learning refresh" \
  --auto-score \
  --auto-postmortem

superforecasting-agent cron create "0 6 * * *" \
  "Run the macro domain learning refresh.

1. Run: superforecasting-agent schedule run --auto-score --auto-postmortem
2. Run: superforecasting-agent errors --domain macro
3. Run: superforecasting-agent calibration --domain macro --by-origin
4. Run: superforecasting-agent lesson list --scope-type domain --scope-ref macro
5. Summarize recurring errors and list active lessons that should be applied to new macro updates.
6. If there is no new score, postmortem, or alert, respond with [SILENT]." \
  --name "Macro domain learning refresh" \
  --deliver local
```

### Apply active lessons during an update

Use this when a domain, topic, or question-type lesson should affect the next probability.

```bash
superforecasting-agent update fq_123456789abc \
  --probability 0.58 \
  --rationale "New labor-market evidence raises the probability, adjusted for active macro overconfidence lessons." \
  --evidence-ref ev_123456789abc \
  --reference-class-ref rc_123456789abc \
  --use-active-lessons \
  --require-citations
```

Preview first when the change is high-stakes:

```bash
superforecasting-agent update fq_123456789abc \
  --probability 0.58 \
  --rationale "Previewing the update before writing a snapshot." \
  --evidence-ref ev_123456789abc \
  --use-active-lessons \
  --require-citations \
  --preview
```

## Script And Delivery Templates

### Send source-monitor output to a channel

Use `send` when a script has already decided what to say.

```bash
superforecasting-agent alerts > /tmp/forecast-alerts.txt

if [ -s /tmp/forecast-alerts.txt ]; then
  superforecasting-agent send \
    --to slack:#forecast-desk \
    --subject "[Forecast alerts]" \
    --file /tmp/forecast-alerts.txt
fi
```

### Script-only data heartbeat

Use a deterministic script when you need a simple health check with no model call.

```python title="~/.superforecasting-agent/scripts/check-data-feed.py"
from pathlib import Path
from time import time

path = Path.home() / ".superforecasting-agent" / "data" / "macro-feed.json"
max_age_seconds = 36 * 60 * 60

if not path.exists():
    print("macro feed missing")
elif time() - path.stat().st_mtime > max_age_seconds:
    print("macro feed stale")
else:
    print("")
```

Run it from a shell cron entry or from the inherited cron script surface:

```bash
superforecasting-agent cron create "0 */6 * * *" \
  "If the script output is empty, respond with [SILENT]. Otherwise explain which forecast data feed is unhealthy and recommend a refresh." \
  --script ~/.superforecasting-agent/scripts/check-data-feed.py \
  --name "Macro feed heartbeat" \
  --deliver telegram
```

## Webhook Templates

### Resolver-source event

Use this when an external system knows that a resolution source changed, but the forecast desk still needs to inspect and record the result.

```bash
superforecasting-agent webhook subscribe forecast-resolver-event \
  --events "resolution_source_changed" \
  --prompt "Resolution source event received:
Question id: {question_id}
Resolution source: {resolution_source}
Observed value: {observed_value}
Timestamp: {timestamp}

1. Run: superforecasting-agent show {question_id}
2. Check whether the event satisfies the resolution criteria.
3. If it does, recommend the exact resolve, score, and postmortem commands.
4. If it does not, create a concise review note and do not resolve the forecast." \
  --deliver slack
```

### External data-pipeline event

Use this when a data pipeline updates a dataset that many forecasts depend on.

```bash
superforecasting-agent webhook subscribe forecast-data-refresh \
  --events "dataset_refreshed" \
  --prompt "Forecast dataset refresh event:
Dataset: {dataset}
Domain: {domain}
Topic: {topic}
Rows changed: {rows_changed}
Snapshot URL: {snapshot_url}

1. Run: superforecasting-agent self-check --domain {domain} --topic {topic} --stale-days 0
2. If rows_changed is 0, respond with [SILENT].
3. Otherwise identify which active forecasts need research and which watched source or evidence import should run next." \
  --deliver telegram
```

## Quick Reference

### Useful schedules

| Expression | Meaning |
|------------|---------|
| `every 30m` | Every 30 minutes |
| `every 2h` | Every 2 hours |
| `0 8 * * *` | Daily at 8:00 AM |
| `0 18 * * 1-5` | Weekday evenings |
| `0 7 * * 1` | Monday morning |
| `0 3 * * 0` | Sunday at 3:00 AM |

### Ledger commands

| Command | Purpose |
|---------|---------|
| `superforecasting-agent status` | Show operational desk status |
| `superforecasting-agent review --stale` | Find stale or due forecasts |
| `superforecasting-agent schedule list` | Show scheduled self-checks |
| `superforecasting-agent watch list` | Show watched evidence sources |
| `superforecasting-agent alerts` | Show open alerts |
| `superforecasting-agent backtest --benchmarks` | List benchmark datasets |
| `superforecasting-agent performance` | Summarize recent backtests |
| `superforecasting-agent calibration --by-origin` | Compare calibration by forecast origin |
| `superforecasting-agent lesson list --active` | Show active calibration lessons |

### The `[SILENT]` pattern

When a scheduled job response contains `[SILENT]`, delivery is suppressed:

```text
If no forecast needs attention, respond with [SILENT].
```

Use this for routine checks so the desk alerts only when evidence, scoring, postmortems, or calibration lessons need attention.
