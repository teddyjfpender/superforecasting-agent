# Scheduled Forecasting Routines

Superforecasting Agent uses scheduled routines to keep a live book of forecasts
fresh. The routine system is not a general automation showcase; it exists to
detect stale beliefs, watch evidence sources, find resolved questions, trigger
postmortems, and update calibration learning after outcomes are scored.

## Forecast-First Routine Types

### Scheduled Self-Checks

Use scheduled self-checks when a domain, topic, portfolio, or specific question
needs recurring review.

```bash
superforecasting-agent schedule add \
  --domain macro \
  --cadence "0 8 * * *" \
  --stale-days 7 \
  --trigger-reason "weekly macro review"
```

Run due reviews manually:

```bash
superforecasting-agent schedule run
```

Install the local cron bridge for no-agent self-checks (idempotent — a
re-install re-arms the job instead of stacking duplicates; the default schedule
is nightly at 08:00):

```bash
superforecasting-agent schedule install-cron
```

You usually do not need to run this by hand: the first committed question
auto-installs the nightly self-check routine (auto-score + auto-postmortem +
thesis aggregation + lesson synthesis + deterministic refresh + saturation
sweep + free-tier warning drain). Disable with
`forecasting.cron.auto_install: false` in config, or put a single question on its
own cadence with `forecast freshen <id> --cadence daily`.

The nightly routine ends with a **free-tier warning drain**: a zero-token-spend
sweep that resolves the "free" open-alert backlog through real gated work — score
a resolved question, write a due postmortem, re-check a changed watched source,
close a bookkeeping notice — so alerts that only capture data and write it to the
ledger drain themselves instead of accumulating as operator to-dos. It never
touches the paid (LLM reforecast/evidence) or manual (operator-judgment) alert
kinds. It is capped per sweep (`forecasting.warnings.free_tier_sweep_cap`,
default 500) so a large backlog drains over a few nights; when the cap is hit the
self-check report says how many remain and points you at
`forecast warnings automode` to drain the rest immediately. Turn the nightly drain
off with `forecasting.warnings.auto_free_tier: false`. `forecast doctor` shows the
last drain count and the remaining free backlog.

Scheduled checks create review alerts without changing active probabilities.
For a due question with active watched sources and structured ensemble
components, the routine re-pulls sources and re-pools components to persist an
update proposal for review. It does not commit a new active snapshot. The cadence
also escalates as a question's
close/resolution/decision deadline approaches (within 7 days → at most daily;
within 48h → twice daily). `forecast doctor` shows cron health (errored or
missed jobs).

### Watched Sources

Use watched sources to attach files, feeds, URLs, data adapters, or source
queries to a question, topic, domain, or portfolio.

```bash
superforecasting-agent watch add \
  --domain ai \
  --source-type rss \
  "https://example.com/releases.atom"
```

Check watched sources for changes:

```bash
superforecasting-agent watch check --domain ai
```

A changed source should create an alert tied to forecast review work. The user
or agent can then append evidence and record an explicit probability update.

### Resolution And Learning Checks

Use self-check filters to find questions that need scoring or postmortems.

```bash
superforecasting-agent self-check \
  --domain public-health \
  --stale-days 14 \
  --auto-score \
  --auto-postmortem
```

Automatic learning writes are opt-in. Even when scoring and postmortem creation
are enabled, the standing forecast is not rewritten in place.

## What Good Routines Produce

A useful forecasting routine should produce one of these artifacts:

- A review alert for a stale or high-impact forecast.
- New timestamped evidence linked to a source snapshot.
- A resolved outcome that can be scored against prior probability snapshots.
- A postmortem explaining a miss or reinforcing a calibrated hit.
- A calibration lesson with an explicit review state.
- A readiness report showing whether stronger performance claims are justified.

Routine output that cannot be tied to evidence quality, probability updates,
resolution, scoring, calibration, or learning belongs outside the core forecast
workflow.

## Readiness Accounting

Run readiness checks before making claims about forecast skill:

```bash
superforecasting-agent readiness --require-evidence
```

The readiness report separates live scored forecasts, historical replay cases,
agent-protocol runs, leakage-free benchmark coverage, and baseline comparisons.
Passing the local workflow smoke path is not the same thing as proving live
superforecasting performance.
