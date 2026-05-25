---
sidebar_position: 3
title: "Tutorial: Daily Forecast Brief"
description: "Build a scheduled forecast evidence brief that reviews active questions, source changes, and stale beliefs."
---

# Tutorial: Build a Daily Forecast Brief

In this tutorial, you will build a scheduled briefing that checks the forecast desk each morning, gathers fresh evidence, and delivers a concise review to your configured alert channel.

The goal is not a generic news digest. The goal is a daily research note that helps maintain probabilistic beliefs: which forecasts are stale, which sources changed, which assumptions need review, and which questions should be updated.

By the end, you will have a workflow combining **forecast review**, **web/source research**, **cron scheduling**, and **delivery**.

## What We're Building

The flow:

1. **8:00 AM** - The scheduler triggers your job.
2. **Forecast review** - The desk lists stale questions, close dates, watched-source alerts, and calibration notes.
3. **Research** - The agent gathers recent evidence for the selected domains.
4. **Briefing** - The agent summarizes facts, uncertainty, and suggested forecast actions.
5. **Delivery** - The briefing goes to Telegram, Discord, Slack, local output, or another configured target.

Use the briefing to decide what to update in the ledger. Do not treat it as a forecast snapshot unless a `forecast update` command actually records the probability, rationale, evidence refs, and as-of timestamp.

## Prerequisites

Before starting, make sure you have:

- **Superforecasting Agent installed** - see the [Installation guide](/getting-started/installation).
- **A configured model/provider** - run `superforecasting-agent model` if needed.
- **Gateway running** - the gateway daemon handles general cron execution:

  ```bash
  superforecasting-agent gateway install
  sudo superforecasting-agent gateway install --system
  # or
  superforecasting-agent gateway
  ```

- **Source/research tools configured** - web search or source adapters for the domains you care about.
- **Messaging configured** - optional but useful; [Telegram](/user-guide/messaging/telegram), Discord, Slack, or another delivery target.

:::tip No messaging target yet
Use `deliver: "local"` while testing. Briefings are saved under `~/.superforecasting-agent/cron/output/`. The inherited `~/.hermes/cron/output/` path is still supported for migrated profiles.
:::

## Step 1: Create or Select Forecasts

The briefing works best when the ledger already has active questions:

```bash
forecast list
forecast review
forecast alerts
```

If you are starting from scratch, create one question:

```bash
forecast new \
  --title "Will the next CPI release exceed consensus expectations?" \
  --resolution-criteria "Resolve yes if the first official BLS CPI release is above the published consensus estimate." \
  --outcome binary \
  --close-time 2026-06-10T12:00:00Z \
  --domain macro \
  --topic inflation
```

Then add evidence or watched sources:

```bash
forecast import fred CPIAUCSL --question <id>
forecast watch add fred CPIAUCSL --question <id>
```

## Step 2: Test the Brief Manually

Before automating anything, start a forecast-scoped session:

```bash
superforecasting-agent
```

Then enter a prompt like this:

```text
Create a morning forecast brief for my macro questions.

Use the forecast ledger first:
- list active macro forecasts
- identify stale forecasts and upcoming close dates
- check open alerts and watched-source changes
- review recent calibration lessons for macro

Then gather only evidence that changed since the last review.
Separate facts, estimates, rumors, and model assumptions.
End with recommended ledger actions: research, base-rate, model, update, resolve, or no action.
Do not change probabilities unless you explicitly run a forecast update with cited evidence refs.
```

The output should look like:

```text
Daily Forecast Brief - Macro - 2026-05-22

Active questions: 7
Needs update: 2
Open source alerts: 3
Upcoming close dates: 1 within 14 days

1. CPI surprise question
   Current p(yes): 0.41 as of 2026-05-20
   New evidence:
   - FRED CPIAUCSL snapshot changed since last review.
   - Consensus estimate still unavailable from configured sources.
   Suggested action: import latest data, update base-rate model, hold probability until consensus source is available.

2. FOMC rate-hold question
   Current p(yes): 0.74 as of 2026-05-19
   New evidence:
   - No watched-source alert.
   - Last postmortem notes overconfidence in single-source Fed commentary.
   Suggested action: no probability update; add one additional market-implied baseline before next review.
```

If the output mixes generic news with forecast actions, tighten the prompt around active question IDs, domains, and ledger actions.

## Step 3: Schedule the Brief

You can schedule this through chat, slash command, or CLI.

### Option A: Natural Language

Tell the forecast desk what you want:

```text
Every weekday at 8am, create a macro forecast brief.
Review active macro questions, stale forecasts, open alerts, close dates,
recent calibration lessons, and source changes. Deliver to telegram.
Do not update probabilities automatically.
```

The agent should create a cron job using the inherited `cronjob` scheduler.

### Option B: Slash Command

```text
/cron add "0 8 * * 1-5" "Create a morning forecast brief for active macro forecasts. Start from the forecast ledger: active questions, stale forecasts, open alerts, watched-source changes, upcoming close dates, and recent macro calibration lessons. Gather only fresh evidence since the last review. Distinguish facts, estimates, rumors, and assumptions. End with recommended ledger actions. Do not change probabilities automatically."
```

### Option C: Ledger-Native Review

When you want the schedule to operate directly on forecast objects, prefer `forecast schedule`:

```bash
forecast schedule add \
  --domain macro \
  --cadence "0 8 * * 1-5" \
  --name "macro-morning-review"
```

For learning workflows, make writes explicit:

```bash
forecast schedule add \
  --domain macro \
  --cadence "0 8 * * 1-5" \
  --auto-score \
  --auto-postmortem \
  --name "macro-learning-refresh"
```

Use auto-learning flags only when the domain has clear resolver sources and you are comfortable with scheduled score/postmortem writes.

## The Rule: Make Prompts Self-Contained

Cron jobs run in fresh sessions. They do not remember what you said earlier. Put the domain, source policy, output format, and ledger-writing policy directly in the prompt.

**Bad prompt:**

```text
Do my usual morning forecast brief.
```

**Good prompt:**

```text
Create a morning forecast brief for active macro forecasts.
Use the forecast ledger first: active questions, stale probabilities,
open alerts, watched-source changes, upcoming close dates, and recent
macro calibration lessons. Gather only evidence published since the last
review. Separate facts, estimates, rumors, and assumptions. End with
recommended ledger actions. Do not update probabilities automatically.
```

The good prompt is specific about scope, evidence policy, output format, and ledger side effects.

## Step 4: Customize the Brief

### Multi-Domain Brief

```text
/cron add "0 8 * * *" "Create a morning forecast brief covering macro, elections, and AI capability forecasts. For each domain, list active questions needing review, fresh evidence, open assumptions, and recommended ledger actions. Keep domains separate. Do not update probabilities automatically."
```

### Backtest and Calibration Section

Add a performance block:

```text
Include a calibration section with:
- unresolved high-confidence questions
- recent Brier/log score changes
- domains with elevated error profiles
- active calibration lessons that should affect updates
```

### Watched-Source Focus

If you have source watches configured:

```text
Start from forecast alerts and watched-source changes.
Ignore general news unless it links directly to an active question,
reference class, resolver source, or explicit assumption.
```

### Delegation as an Opt-In Accelerator

Delegation can speed up broad research, but it should stay bounded:

```text
For each domain with more than five active forecasts, delegate one research task:
find fresh evidence since the last review, return source URLs, claim type,
publication time, and relevance. The main agent must reconcile the results
against the forecast ledger and avoid probability updates unless cited.
```

See [Delegation](/user-guide/features/delegation) for the inherited parallel-worker runtime.

### Personal Context

Runtime memory can store preferences, but the forecast ledger owns probabilities, evidence, scores, postmortems, and calibration lessons. For scheduled briefs, bake the relevant preferences into the prompt:

```text
Audience: a macro forecaster who cares about rate decisions, inflation
surprises, recession odds, and market-implied baselines. Skip broad market
commentary unless it changes a reference class, source reliability, or
probability update recommendation.
```

## Step 5: Manage Jobs

### List Scheduled Jobs

In chat:

```text
/cron list
```

From the terminal:

```bash
superforecasting-agent cron list
forecast schedule list
```

### Remove a Job

```text
/cron remove a1b2c3d4
```

Or ask:

```text
Remove my macro morning forecast brief.
```

The agent can call `cronjob(action="list")` and `cronjob(action="remove")` for general cron jobs. Use `forecast schedule remove <id>` for ledger-native schedules.

### Check Gateway Status

```bash
superforecasting-agent cron status
superforecasting-agent gateway status
```

If the gateway is not running, general cron jobs will not execute. Install it as a background service for reliability:

```bash
superforecasting-agent gateway install
sudo superforecasting-agent gateway install --system
```

## Going Further

- [Scheduled Tasks (Cron)](/user-guide/features/cron) - full schedule formats, repeat limits, and delivery options.
- [Automate Forecast Reviews with Cron](/guides/automate-with-cron) - ledger-aware scheduled review patterns.
- [Script-Only Scheduled Jobs](/guides/cron-script-only) - deterministic monitors that skip the model.
- [Messaging Platforms](/user-guide/messaging) - configure Telegram, Discord, Slack, or other delivery targets.
- [Memory](/user-guide/features/memory) - runtime recall; not the source of truth for forecast state.
- [Tips & Best Practices](/guides/tips) - prompt and ledger hygiene.

:::tip What else can you schedule?
The same pattern works for competitor monitoring, policy watches, earnings-cycle review, macro data releases, model artifact checks, or resolver-source monitoring. Keep the output tied to active forecast questions and ledger actions.
:::
