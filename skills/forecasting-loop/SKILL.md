---
name: forecasting-loop
description: "The guided superforecasting loop: parse -> research -> base_rate -> model -> update -> resolve -> postmortem, driven by `forecast pipeline`. Sequences a question through the stages, reports what is done from ledger artifacts, and refuses to advance to a committed forecast before an outside view (base rate) and source-backed evidence exist. Use when running a forecast end-to-end, or when unsure which stage comes next."
version: 1.0.0
author: Superforecasting Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [forecasting, superforecasting, pipeline, workflow, base-rate, calibration, panel, resolution, scoring]
    category: forecasting
    related_skills: [forecast-onboard, bayes-forecast-scratchpad]
---

# The Forecasting Loop

A forecast is not a number you blurt — it is a **process** that leaves an audit
trail. This skill drives a question through that process with one command,
`forecast pipeline`, and tells you what is done and what comes next. It is a
**guide, not a cage**: it enforces the few formalities that make forecasting
scoreable, and leaves the reasoning — decomposition, panels, scratchpads,
exploratory side-models — completely free.

## The stages

```
parse -> research -> base_rate -> [model] -> update -> resolve -> postmortem
```

1. **parse** — Is the question scoreable AND decision-relevant? Pin resolution
   criteria, outcome space, and the decision card (owner, action threshold,
   update triggers). A forecast that informs no decision is entertainment. If the
   question just arrived from onboarding (the [forecast-onboard] skill / a
   `commit_spec`, including the `accept_defaults` fast path), **parse is already
   done** — the spec committed it scoreable with a decision card and watched
   sources. Do not re-interrogate; pick up at **research** and drive straight to
   the first live `update`.
2. **research** — Collect *timestamped* evidence; separate facts, estimates,
   rumors, opinions, assumptions. Do not move the probability yet. For a market
   prior, pull it through the `forecast_ledger` `pm_query` action (`pm_mode`
   search/event/book/history) — structured, de-vigged Polymarket + Kalshi
   distributions and order-book depth — instead of scraping or a fuzzy import.
3. **base_rate** — Establish the outside view first: reference classes with
   inclusion/exclusion criteria and base rates. Blend competing classes; for
   rare events decompose into a conditional chain with an unconditional
   sanity-check.
4. **model** *(optional)* — Quantitative models / Bayesian building blocks that
   improve the estimate. Skippable; it never blocks progress. For a data-driven
   numeric question you can build a deterministic quant Market Model as a scoreable
   component (`forecast model build <id>`, or the `build_model` action): it computes
   every statistic via the shared market_compute engine and links back a model_run +
   reference class the panel/ensemble can pool like any other input.
5. **update** — Commit the forecast. Pool disagreeing sources in log-odds, not a
   naive average; decompose the change; stress-test it.
6. **resolve** — Once criteria are met, record the resolution. Scoring is
   automatic.
7. **postmortem** — Diagnose the resolved forecast and fold the lesson back into
   calibration.

## Drive it with `forecast pipeline`

```
forecast pipeline <id>                 # status: which stages are done, what is next
forecast pipeline <id> --stage research  # render that stage's protocol prompt
forecast pipeline <id> --json          # machine-readable status for the agent
```

The agent tool mirrors this: `forecast_ledger` with `action="pipeline"`,
`question_id`, optional `stage`, optional `force`.

Status markers: `[x]` done · `->` ready (next actionable) · `..` blocked
(prerequisite unmet) · `(o)` optional.

### The one sequencing gate

Advancing the pipeline to **update** is refused until **research** and
**base_rate** have produced ledger artifacts — you cannot commit a forecast
before an outside view and source-backed evidence exist. (Likewise `resolve`
needs a committed forecast, and `postmortem` needs a resolution.)

```
$ forecast pipeline <id> --stage update
forecast: pipeline will not advance to 'update' yet — its prerequisites are not
met. Missing: research: collect timestamped evidence ...; base_rate: establish a
reference class ... Run those stages, or pass --force to override ...
```

This gate lives **only in the pipeline driver**. The raw `forecast update`
command and every per-stage command stay free — use `--force` to render an
early stage, or run the underlying command directly when you are committing an
exploratory or out-of-band snapshot.

## The formalities a committed forecast carries

These bind a **live** (committed, scored) forecast. Each has an explicit escape
valve so the discipline never becomes a cage:

- **Structured reasoning** (default on): `reasons_up`, `reasons_down`, and
  `change_my_mind` — pass `--reason-up/--reason-down/--change-my-mind`, or opt a
  one-off out with `--no-require-structured-reasoning`.
- **Deliberative panel** for high-impact forecasts (default on): link a panel
  (`--panel-estimates-json` or `--panel-run-ref`) or record `--panel-skipped-reason`.
  Lower-impact first forecasts are only nudged.
- **Citations** (opt-in): `--require-citations` refuses a live update with no
  evidence/model/reference refs.
- **Auto-scoring**: a confirmed, criteria-satisfied resolution scores itself
  (Brier/log) automatically — no separate step.

## The researcher's escape: exploratory snapshots

You are also a quantitative researcher. Think out loud, keep scratchpads, run
side-models and lateral what-ifs as freely as the problem needs. When you are
**exploring rather than committing**, record the snapshot as
`forecast_origin="exploratory"` (CLI `--origin exploratory`): it is exempt from
every commit-time formality above and is never calibration-scored. Bring the
full discipline when you commit a live forecast.

## Where this fits

- Reasoning *to* the number before you commit it (status quo + horizon anchor,
  trace and price the path to each outcome, tail check) → **path-driven-forecast**.
  It lives inside the `update` stage and is how you avoid a junior forecast — a
  number pulled from a vibe.
- Moving or combining a probability → reach for **bayes-forecast-scratchpad**
  (log-odds pooling, likelihood ratios, market de-vig, conditional chains).
- Running a question end-to-end, or unsure what is next → this skill and
  `forecast pipeline`.
