---
sidebar_position: 3
title: "Forecast Memory"
description: "Use calibration lessons, error profiles, and postmortems as durable forecast memory."
---

# Forecast Memory

In this fork, durable learning should be tied to forecasts. Generic chat memory is still available for compatibility, but it is not the main learning surface. The forecast ledger is.

The core loop is:

```text
forecast -> resolve -> score -> postmortem -> lesson -> calibrated future update
```

## Forecast Learning Artifacts

| Artifact | Purpose |
|---|---|
| Forecast snapshots | Append-only probabilities, distributions, confidence, rationale, assumptions, evidence refs, model refs, and calibration refs. |
| Scores | Brier/log/proper scores with domain, horizon, origin, and calibration eligibility. |
| Postmortems | Structured miss diagnosis: what happened, what was expected, what evidence was overweighted or missed, and what should change. |
| Calibration lessons | Reviewable lessons created from eligible scores and postmortems. Only active lessons can influence future updates. |
| Domain error profiles | Recurring overconfidence, underconfidence, base-rate misses, resolution misunderstandings, and evidence weighting errors by domain/topic. |
| Corrections | Explicit records that invalidate affected scores, postmortems, and lessons when a prior artifact was wrong. |

## Core Commands

```bash
forecast calibration --by-origin --all
forecast errors
forecast lessons
forecast postmortem <id>
forecast update <id> --use-active-lessons --probability 0.61 --rationale "..."
forecast backtest --benchmarks
forecast performance --last 5 --json
```

Use `--by-origin` and `--all` to keep live forecasts, backtests, and imported baselines separate. A lesson from a noisy backtest should not silently bias live forecast updates unless it is explicitly eligible and reviewed.

## Postmortems

A useful postmortem answers:

- What happened?
- What did I think would happen?
- What evidence did I overweight?
- What evidence did I miss?
- Was the base rate wrong?
- Was the inside-view model wrong?
- Was the question or resolution criteria misunderstood?
- What update rule should change?

Example:

```bash
forecast postmortem <id> \
  --what-happened "The bill passed committee earlier than expected." \
  --what-i-thought "Calendar congestion would delay a vote." \
  --overweighted-evidence "Generic calendar congestion." \
  --missed-evidence "Leadership scheduling signal." \
  --base-rate-error "Used all committee bills instead of leadership-priority bills." \
  --lesson "For this committee, leadership scheduling hints should outweigh generic calendar congestion."
```

Postmortems can create tentative calibration lessons. Review them before they become active.

## Calibration Lessons

Lessons have review state. The important states are:

| State | Meaning |
|---|---|
| tentative | Created from a score or postmortem but not trusted yet. |
| active | Approved for use in future forecast updates. |
| invalidated | No longer trusted; future updates cannot cite it. |

Only active, non-invalidated lessons can be cited by `forecast update --use-active-lessons` or the forecast ledger tool. This prevents one bad postmortem from contaminating future probabilities.

## Error Profiles

Use error profiles to find repeated mistakes:

```bash
forecast errors
forecast calibration --domain macro --by-origin --all
forecast calibration --horizon 0-30 --by-origin --all
```

Typical patterns:

- overconfident in short-horizon political forecasts
- underweighting base rates in product launches
- overweighting market moves in thin prediction markets
- misunderstanding resolution criteria
- relying on stale evidence after a watched source changed

## Backtests And Memory Eligibility

Backtests are valuable, but they are not the same as live forecasts. A replay run can create scores and benchmark reports without making those scores eligible for live calibration memory.

Use:

```bash
forecast backtest --benchmarks
forecast backtest --all-benchmarks --probability-source forecast-engine
forecast performance --last 5
```

When a replay has leakage risk or is only a plumbing smoke test, keep its scores separate from live calibration memory.

## Scheduled Learning

Scheduled self-checks can update learning artifacts only when explicitly configured:

```bash
forecast schedule add --domain policy --cadence 1d --auto-score --auto-postmortem
forecast schedule run --due --auto-score --auto-postmortem
```

Without those flags, scheduled checks create alerts and review work but do not write scores, postmortems, or calibration lessons.

## Generic Runtime Memory

The inherited runtime still includes bounded `MEMORY.md` and `USER.md` stores plus session search. Use them for:

- user preferences
- stable environment facts
- project conventions
- tool quirks
- communication preferences

Do not use generic memory for:

- forecast probabilities
- evidence claims
- calibration lessons
- score summaries
- postmortem conclusions
- resolution details

Those belong in the forecast ledger, where they remain auditable and scoreable.

## Compatibility Commands

```bash
superforecasting-agent memory setup
superforecasting-agent memory status
superforecasting-agent sessions list
```

External memory providers can still help with user/project context, but forecast learning should remain provenance-aware. If an external memory system stores forecasting knowledge, it should reference ledger artifacts rather than replacing them.

## Storage

New installs prefer `~/.superforecasting-agent`. Existing `~/.hermes` homes are reused during the fork transition.

The important distinction is conceptual:

- Runtime memory helps the agent remember user and environment context.
- Forecast memory helps the desk improve probabilistic judgment over time.

When in doubt, store forecast-relevant learning in the ledger.
