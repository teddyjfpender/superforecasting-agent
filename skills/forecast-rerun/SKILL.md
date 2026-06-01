---
name: forecast-rerun
description: "Re-run an existing forecast the proper way: pull the latest watched-source readings, collect genuinely new evidence, re-pool with STRUCTURED components, and commit a fresh live snapshot — instead of redoing imports by hand. Invoke as /forecast-rerun <question id or title>."
version: 1.0.0
author: Superforecasting Agent
license: MIT
platforms: [linux, macos, windows]
aliases: [rerun, refresh-forecast]
metadata:
  hermes:
    tags: [forecasting, refresh, re-run, update, pooling, triggers, superforecasting]
    category: forecasting
    related_skills: [forecasting-loop, bayes-forecast-scratchpad]
---

# Re-run a forecast (the proper way)

The user invoked this to **re-run one or more existing forecasts**. Do it through
the structured ledger path below, not as an ad-hoc "collect evidence and update"
freestyle. The whole point is that what you produce is re-poolable and
auto-refreshable next time.

## 0. Identify the question(s)

If the user named a question (id `fq_…` or a title), resolve it with the
`forecast_ledger` `search`/`show_question` action. If they said "the forecasts"
with no id, `list_questions` and re-run each active one. Read the CURRENT
snapshot first (`show_question`) so you know the prior probability, method, and
existing `ensemble_components`.

## 1. Fast path first — `forecast refresh`

If the question already has watched sources AND its latest snapshot carries
structured `ensemble_components`, just run:

```
forecast refresh <id>            # pull latest readings, re-pool, auto-commit
forecast refresh <id> --dry-run  # preview the move first
forecast refresh <id> --agent    # full LLM re-reasoning instead of the re-pool
```

That single command re-fetches every active watched source, imports the fresh
values (deduped), re-pools the market/crowd components, and commits a new live
snapshot. Report the diff and stop. Use the `--agent` mode (or the full path
below) when the change is driven by raw-data/qualitative shifts that a
deterministic re-pool can't reason about.

## 2. Full re-reasoning path (when refresh can't, or the user wants a fresh take)

Run the forecasting loop's tail end. Keep the discipline; keep it auditable.

1. **Pull latest readings.** Re-import each watched series with
   `import_source_evidence` (or `import_source_evidence_batch`). Imports are
   **deduped by default** — re-pulling an unchanged FRED/market reading is a
   no-op (`skipped_duplicates` in the response), so don't worry about bloating
   the evidence table. For a market/page with no structured adapter, read it in
   the browser, then record the number as evidence AND as a component (next
   step) — do not leave it only in prose.
2. **Re-pool with the Bayesian toolkit**, not a naive average:
   `bayes_action='combine'`, `method='log_odds_pool'`,
   `correlation_matrix='estimate'` when sources overlap. Decompose the move with
   `bayes_action='forecast_diff'` and stress-test with `bayes_action='sensitivity'`.
3. **Commit with STRUCTURED components.** On `update_forecast` (or
   `forecast update --component-json`), pass `ensemble_components` as the actual
   list you pooled: `{"components":[{name, probability, weight, source}]}`. Give
   each market/crowd component a stable `source` slug (e.g.
   `polymarket:<slug>`, `manifold:<slug>`) so the NEXT `forecast refresh` can
   match and update it. **Components left in a model_run or the rationale are not
   refreshable — this is the #1 thing to get right.** Also pass `reasons_up`,
   `reasons_down`, and `change_my_mind`.
4. **Make the triggers executable.** For any trigger that watches a numeric
   series or market, ensure it carries `source_ref` + `operator` (>, >=, <, <=,
   ==, !=) + a numeric `threshold` so it fires a `trigger_fired` alert
   automatically. Prose-only thresholds never fire. Verify with
   `forecast triggers <id>` / `check_update_triggers`.
5. **Size the move against the decision card.** State the delta vs the prior and
   whether any `action_threshold` / `update_trigger` was crossed. Small,
   threshold-checked moves are correct; don't chase noise.

## 3. Report back

For each re-run question: prior → new probability (+delta), what moved it
(top forecast_diff drivers), which thresholds were/weren't crossed, and the new
`forecast_id`. If you used the full path because refresh couldn't, say so and
note that the snapshot now carries structured components/triggers so future
re-runs can use `forecast refresh`.
