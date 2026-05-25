---
sidebar_position: 5
title: "Scheduled Self-Checks"
description: "Schedule forecast reviews, watched-source alerts, scoring, and learning jobs."
---

# Scheduled Self-Checks

Scheduling is part of the forecast feedback loop:

```text
forecast -> observe -> resolve -> score -> diagnose -> recalibrate -> forecast better
```

Use `forecast schedule` for forecast-native review jobs. The inherited `superforecasting-agent cron` command still exists for general scheduled tasks, but forecast work should prefer the ledger-aware scheduler because it can target questions, domains, topics, forecast horizons, alerts, scores, postmortems, and calibration memory.

## Forecast-Native Scheduling

```bash
forecast schedule add --question <id> \
  --cadence 1d

forecast schedule add --domain policy --topic elections \
  --cadence 12h \
  --stale-days 3 \
  --auto-score \
  --auto-postmortem

forecast schedule add --horizon 30 \
  --cadence 1d \
  --next-run-at 2026-05-22T09:00:00Z

forecast schedule list
forecast schedule run --due
```

`--next-run-at` is optional. When omitted, the first run is due immediately.

Scheduled checks can:

- flag stale forecasts and assumptions
- detect newly available evidence
- detect questions that may be resolved
- create review alerts
- score confirmed resolved questions when `--auto-score` is set
- create postmortems and calibration lessons when `--auto-postmortem` is set
- update domain/topic error profiles from eligible scores
- on global checks, create a benchmark evidence alert when live-score,
  agent-protocol replay, leakage-free run, positive generated-source edge, or
  dataset-coverage gaps still block any live-superiority claim

Use `--stale-days` to tune the evidence and last-update threshold per scheduled
review. Fast-moving domains can use shorter windows without changing the global
self-check default.

They should not silently change active forecast probabilities. If new evidence moves a belief, the desk should create an explicit `forecast update` with an as-of timestamp, evidence refs, and rationale.

## Watched Sources

Watched sources are alert inputs, not automatic updates.

```bash
forecast watch add --question <id> gdelt:"central bank rate cut"
forecast watch add --question <id> rss:https://example.com/feed.xml
forecast watch add --question <id> fred:UNRATE
forecast watch add --question <id> bls:LNS14000000
forecast watch add --question <id> worldbank:US/NY.GDP.MKTP.CD
forecast watch add --question <id> sec:0000320193
forecast watch add --question <id> arxiv:"cat:cs.AI AND forecasting"
forecast watch add --question <id> openalex:"forecasting calibration"
forecast watch add --question <id> wikipediapageviews:en.wikipedia.org/Topic
forecast watch add --question <id> manifold:<slug>
forecast watch add --question <id> metaculus:<id>
forecast watch add --question <id> polymarket:<slug>
forecast watch add --question <id> kalshi:<ticker>
```

When a watched source changes, the ledger records an alert tied to the question, domain, topic, or portfolio scope. The operator or agent can then inspect the source and decide whether to append a forecast update.

## Opt-In Learning Writes

Automatic learning writes are explicit because calibration memory can bias future forecasts.

```bash
forecast self-check --question <id> --auto-score --auto-postmortem
forecast schedule run --due --auto-score --auto-postmortem
forecast schedule add --domain macro --cadence 1d --auto-score --auto-postmortem
```

Use these flags only when the schedule is allowed to write scores, postmortems, lessons, and error-profile updates. Without them, checks create alerts and review state but leave learning artifacts untouched. Once an error profile exists, scheduled checks also create `domain_error_profile_applies:<id>` alerts on matching active forecasts so recurring misses are pulled back into the review queue without changing the standing probability.

## Review Cadence

Good defaults:

| Forecast type | Suggested cadence |
|---|---|
| Close to resolution | 6h to 1d |
| High-impact active forecast | 12h to 2d |
| Slow-moving macro forecast | 3d to 7d |
| Research watchlist | 1d to 7d |
| Backtest or calibration report | weekly |

Cadence should reflect evidence velocity and decision impact. A daily check on a low-evidence question can waste attention; a weekly check on a fast election market can miss important moves.

## Alerts

```bash
forecast alerts
forecast alerts --open
forecast alerts --ack <alert-id>
forecast review --stale
forecast review --domain policy
forecast review --topic elections
```

Alerts should explain:

- the question or scope affected
- the source or schedule that triggered the alert
- what changed
- recommended next action
- when the alert was created

## Backtest And Calibration Jobs

Recurring benchmark reports can run through the forecast CLI:

```bash
forecast backtest --benchmarks
forecast backtest --all-benchmarks --probability-source forecast-engine
forecast backtest builtin:manifold-public-120-binary --probability-source forecast-engine
forecast performance --last 5 --json
forecast readiness --require-evidence
forecast calibration --by-origin --all
```

Use these in scheduled jobs or local automation to track whether the forecast engine is improving. Keep live forecasts, imported baselines, and backtests separate when interpreting calibration. Readiness checks require external resolved-question corpus coverage and external source-family diversity, so synthetic, local fixture, or single-platform replays should not be treated as enough evidence for stronger performance claims.

## Inherited Cron Runtime

Install a no-agent bridge when you want the inherited cron daemon to run due
forecast-native schedules:

```bash
forecast schedule install-cron --schedule "every 1h" --auto-score --auto-postmortem
```

The installed job runs `forecast_self_check.py` without invoking the LLM. It
emits output only when the ledger produces review alerts, scores, postmortems,
lessons, or error-profile updates. The report includes explicit
`scores_created`, `postmortems_created`, and `learning_reviews` counts so
operators can see when a scheduled check changed learning state without
parsing every alert line.
If you install from an isolated ledger, pass the same `--db` you use for the
desk; the generated bridge script preserves that path:

```bash
forecast --db "$FORECAST_DB" schedule install-cron --schedule "every 1h"
```

General scheduling remains available through the inherited runtime:

```bash
superforecasting-agent cron create "every 2h" "Check server status"
superforecasting-agent cron list
superforecasting-agent cron pause <job_id>
superforecasting-agent cron resume <job_id>
superforecasting-agent cron run <job_id>
superforecasting-agent cron remove <job_id>
superforecasting-agent cron status
```

The inherited scheduler can run ordinary prompts, deliver messages, attach skills, and run script-only watchdogs. Use it for general automation. Use `forecast schedule` when the job should interact with the forecast ledger.

## No-Agent Mode: Script-Only Jobs

For recurring watchdogs that do not need model reasoning, use script-only jobs in the inherited cron runtime:

```bash
superforecasting-agent cron create "every 5m" \
  --no-agent \
  --script memory-watchdog.sh \
  --deliver telegram \
  --name "memory-watchdog"
```

Semantics:

- script stdout is delivered verbatim
- empty stdout is a silent tick
- non-zero exit or timeout creates an error alert
- no model call is made

This is useful for infrastructure heartbeats and hard threshold alerts. For forecast-specific evidence checks, prefer watched sources and ledger alerts.

## Gateway And Profiles

The inherited cron runtime is ticked by the gateway daemon. Forecast-native schedules are stored in the forecast ledger and can be run directly through the forecast CLI or from scheduler integration.

```bash
superforecasting-agent gateway install
superforecasting-agent gateway status
superforecasting-agent cron status
forecast schedule list
```

New installs prefer `~/.superforecasting-agent`; existing `~/.hermes` homes are reused during the compatibility transition. Profile-scoped jobs should use the profile that owns the relevant forecast ledger.

## Delivery

Forecast alerts stay in the ledger by default. General cron jobs can deliver to local files or configured messaging platforms. If you route forecast reviews to messaging, include links or IDs that make it easy to return to the ledger:

```text
Forecast 142 needs review: watched GDELT source changed.
Run: forecast show 142
Then: forecast research 142 ... or forecast update 142 ...
```

Do not treat a delivered message as the durable record. The durable record is the forecast ledger entry, alert, evidence item, score, or postmortem.
