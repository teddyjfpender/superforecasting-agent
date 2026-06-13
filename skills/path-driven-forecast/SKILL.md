---
name: path-driven-forecast
description: "The path-driven reasoning rubric that turns a junior forecast (a number from a vibe) into a senior one (a number that falls out of a priced causal path). Use before committing any live forecast, especially binary and numeric questions: anchor on the status quo and horizon, trace and price the path to each outcome, reconcile against the market, stress the tails, then commit with conviction. Complements the forecasting-loop pipeline and the bayes-forecast-scratchpad."
version: 1.0.0
author: Superforecasting Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [forecasting, superforecasting, reasoning, base-rate, calibration, status-quo, path, scenarios]
    category: forecasting
    related_skills: [forecasting-loop, bayes-forecast-scratchpad]
---

# Path-Driven Forecasting

A junior forecast is a number pulled from a vibe — it reacts to the most salient
headline and calls that a probability. A senior forecast is a number that **falls
out of a priced causal path**: you can point at the chain of things that must
happen, say how likely each link is, and show why the mass lands where it does.

This skill is the reasoning rubric that gets you from the first to the second. It
sits *inside* the `update` stage of the [forecasting-loop](../forecasting-loop/),
after research and base rates, right before you commit. It changes how you
**reason**, not which commands you run.

## The rubric

Work these in order. Keep it in a scratchpad; the load-bearing pieces become the
snapshot's structured reasoning and rationale.

### 1. Anchor: status quo + horizon

Before any story, write the **status-quo outcome** — what happens if nothing
changes. The world changes slowly, so this outcome earns extra weight, and the
**shorter the time to resolution, the more it dominates**. A change off the
status quo requires a *cause*, and most of the time the cause does not arrive in
time.

- State the persistence outcome explicitly and the rough base rate it implies.
- State the horizon. "Resolves in 3 weeks" and "resolves in 3 years" are
  different questions even with identical wording — short horizons compress
  toward the status quo; long horizons widen the distribution.

### 2. Trace the path to each outcome

For a **binary**, name two paths and price their links:

- **Path to YES** — the chain that must occur, in order, each link with a rough
  probability: `A must happen (p≈?) → then B (p≈?|A) → then C (p≈?|A,B)`.
- **Path to NO** — the chain (often just "the status quo holds").

The probability is the **weight of the path that must actually occur**, not the
salience of the headline. A reason is not a path: *"the economy is weak"* is a
vibe; *"rates hold → demand softens → the print clears X by date D"* is a chain
you can price and check. **A path with one weak link cannot carry heavy mass** —
if any link is improbable, the whole outcome is improbable, however vivid the
story. Use `bayes_action='conditional_chain'` (with its mandatory
`unconditional_estimate` sanity-check) when the path is a genuine multi-step
chain.

For a **numeric / distribution**, trace four anchors instead of two paths:

- the value **if nothing changes** (status quo),
- the value **if the current trend continues**,
- what **experts and markets** expect,
- then a named **low-tail scenario** and a named **high-tail scenario**.

Set **wide 90/10 intervals** — humble tails account for the unknown unknowns the
four anchors miss.

### 3. Reconcile against the market, form your own view

Compare your path-derived number to crowd / market / model forecasts. They are
strong evidence — weigh them — but **state where and why you diverge**. A
forecast that only ever sits just inside the market adds no value and is
reliably less sharp than the market itself. If you cannot articulate a path that
justifies your divergence, you do not have one — move toward the market.

### 4. Forecast from the information frontier

Reason only from what was knowable at your **as-of cutoff** — that timestamp is
your information frontier. Guard against two leaks:

- **Hindsight** — an outcome that looks inevitable now was not certain at the
  frontier. Price the path as it looked then.
- **Recency / salience** — the loudest recent headline is rarely the most
  diagnostic evidence. Weight by diagnosticity, not vividness.

### 5. Tail check, then commit with conviction

Audit for **under-confidence** as hard as for overconfidence (it is scored the
same):

- **No-path tails (run the audit)**: for a *categorical* forecast, do not
  forecast from the answer choices — forecast from the causal paths. Run the
  probability-mass audit before you commit:

  ```
  forecast tail-audit --dist '{"Lasher":0.55,"Bores":0.35,"Conway":0.017,"Other":0.013}' \
      --outcome-path 'Lasher=leads polls + endorsements + field' \
      --outcome-path 'Bores=fundraising + establishment lane'
  ```

  (agent tool: `forecast_ledger` action `tail_audit` with `distribution` +
  `outcome_paths`.) It demands a named path for every outcome holding **≥0.5%**
  and flags **unearned tail mass** — a named-but-non-live option (a candidate
  with no poll, ballot line, or money) holding a tail purely because it appears
  in the outcome set. That is *outcome-space anchoring*, the classic junior
  error: a listed outcome is not a live one. Name the mechanism for each
  material outcome, or compress that mass onto the outcomes with a live path.
  Commit with `--require-outcome-paths` (tool: `require_outcome_paths=true`) to
  make the gate hard — the live snapshot is refused until the mass is earned.
  The audit table is recorded on the snapshot either way.
- **Sharper null model**: the same audit compares your distribution to a
  deliberately simple model — any outcome with no named path is floored near
  zero and the rest keep their proportions. If your no-path tail is several
  times fatter than the null's (`no-path tail X% vs simple-null Y%`), the richer
  model owes an explanation; if you can't give one, fall back to the simple one.
- **Don't let thin markets inflate the tail**: a price nobody is defending is
  not strong evidence. Stratify each market reading by liquidity + recency
  before you pool it:

  ```
  forecast market-quality --markets '[{"source":"polymarket:slug","volume":90000,"updated_at":"2026-06-01T00:00:00Z"},
                                       {"source":"manifold:x","volume":300,"age_days":1}]'
  ```

  (agent tool: `forecast_ledger` action `market_quality`.) It returns an
  advisory weight in [0,1] per market — liquid 1.0, thin ~0.35, stale ~0.25,
  placeholder ~0.05. **Multiply that weight into the market component's `weight`
  in `ensemble_components`** so a stale or thin market pools at a fraction of a
  liquid one. Never drop a market silently — record the discounted weight.
- **Leader suppression**: is your top outcome held *below* what the paths,
  polls, and fundamentals imply? Sharpen it.

When the paths earn a sharp, concentrated number, **commit to it** — chronic
hedging is a scored failure, not safety. If conviction is genuinely low because
the evidence is thin, the fix is to go back to **research** and get evidence, not
to flatten the distribution to feel safe.

## What lands in the snapshot

The path work is not throwaway scratch — it becomes the committed forecast's
structured reasoning, so the three fields are the **paths**, not loose pros/cons:

- `reasons_up` → the links on the path that drives the probability **higher**.
- `reasons_down` → the links on the path that drives it **lower**.
- `change_my_mind` → the **weakest load-bearing link** — the observation whose
  failure breaks the path and forces a material update. (This is also your best
  `update_trigger`: make it executable with a `source_ref` + `operator` +
  numeric `threshold` so it fires automatically.)

Commit with `forecast update <id> --reason-up ... --reason-down ...
--change-my-mind ...` (structured reasoning is enforced by default on live
forecasts). For a high-impact or first forecast, run the deliberative **panel**
(outside / inside / market / red-team / sanity) — the panel and this rubric are
complementary: the panel gives you independent framings, this rubric prices the
path within each.

## Where this fits

- Running a question end-to-end / unsure what is next → **forecasting-loop**.
- Moving or combining a probability with auditable math (log-odds pooling,
  likelihood ratios, conditional chains, market de-vig) →
  **bayes-forecast-scratchpad**.
- Reasoning *to* the number before you commit it → this skill.
