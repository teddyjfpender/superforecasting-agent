---
name: quorum-forecast
description: "Run a model-diverse forecast quorum (the superforecaster's 'Fusion'): dispatch one forecasting brief to a panel of independent models via OpenRouter, then a judge synthesizes a senior-desk verdict. Records a sibling panel run with a first-class disagreement signal, and feeds the senior process (reasons_up/down, change_my_mind, ensemble_components). Use for high-impact or first forecasts, when you want model-architecture diversity and an explicit disagreement reading — not just one model's view."
version: 1.0.0
author: Superforecasting Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [forecasting, superforecasting, quorum, fusion, ensemble, multi-model, panel, disagreement, judge, calibration]
    category: forecasting
    related_skills: [forecasting-loop, bayes-forecast-scratchpad, path-driven-forecast]
---

# The Quorum — model-diverse forecasting with a judge

A single model gives one estimate per pass. A **quorum** gives the same
forecasting brief to a panel of *independent models* (e.g. Opus 4.8 + GPT-5.5,
or a budget panel of Gemini Flash + Kimi + DeepSeek), lets each research and
answer on its own, then a **judge** model reads every response and writes the
final senior-desk synthesis. Two effects compound:

- **Model diversity** — different architectures miss different things, so the
  pooled answer beats any one frontier model.
- **The synthesis step itself** — even one model paired with *itself* gains,
  because the judge is forced to name consensus, contradictions, and blind
  spots. So a quorum is worth running even with a single provider key (the
  `self` preset).

The quorum is a **sibling of the perspective panel**, not a replacement. The
5-perspective panel diversifies by *role* (outside / inside / market / red-team
/ sanity); the quorum diversifies by *model*. Both flow through the same
aggregation and ledger plumbing, and both leave a recorded panel run with a
spread — so model-disagreement and role-disagreement stay separately
attributable.

## When a quorum is indicated

The quorum rides the existing deliberative-panel trigger:

- **high-impact** forecasts, and
- the **first** forecast for a question (the cheapest moment to set a baseline).

Turn it on as a standing default so you never pass flags:

```
forecast quorum default on                       # enable
forecast quorum default on --scope high_impact   # (default) only where a panel is indicated
forecast quorum default on --scope always        # every update (expensive)
forecast quorum default off
```

When `default_enabled` is on and a quorum is indicated, `forecast update` will
remind you to run one before committing.

## Running it

A quorum is several models each doing web research plus a judge pass — minutes
of wall-clock, well past the TUI's slash timeout. So it runs as a **background
job**: you get a run-id immediately and poll for the result.

```
forecast quorum <question-id>                    # start (background); prints a run-id
forecast quorum <question-id> --preset budget    # frontier | budget | self
forecast quorum <question-id> --models openai/gpt-5.5,google/gemini-3-flash
forecast quorum <question-id> --self --samples 3 # self-fusion with the active model
forecast quorum <question-id> --wait             # run synchronously (CLI / scripts)

forecast quorum status                           # list recent runs
forecast quorum status <run-id>                  # progress + result + judge verdict
```

Defaults (preset, judge, pooling, trim) come from config; flags override per
run. Inspect / change them with:

```
forecast quorum config
forecast quorum config set preset budget
forecast quorum config set judge anthropic/claude-opus-4-8
```

All models route through the **OpenRouter** provider, so you need one key:
`forecast api-key set openrouter <key>`.

## How it plugs into the senior process (do not bypass it)

The quorum does **not** commit a snapshot — it produces a recorded panel run.
The senior process stays intact:

1. Run the quorum: `forecast quorum <id>` → wait for `status` to show `done`.
   Note the `panel_run` id and read the judge's synthesis.
2. Commit the snapshot through the normal gate, attaching the quorum as the
   deliberative panel and carrying the judge's structured reasoning:

   ```
   forecast update <id> \
     --panel-run-ref <panel_run_id> \
     --reasons-up "<judge reasons_up>" \
     --reasons-down "<judge reasons_down>" \
     --change-my-mind "<judge change_my_mind>" \
     --rationale "<judge synthesis>"
   ```

The judge's `blind_spots` are evidence gaps — feed them back into the research
stage. The quorum's per-model probabilities are persisted as
`ensemble_components` (source slugs `quorum:<model>`), so `forecast refresh` and
the track-record weighting measure each model against the aggregate over time.

## Disagreement is a signal, not noise

Every quorum records a **disagreement scalar** (log-odds dispersion of the
panel) inside the panel spread, shown on the desk as a calm → severe meter. A
wide spread is epistemic uncertainty the aggregate hides: when the quorum
splits, investigate the crux — do not average it away.

Once forecasts resolve and score, learn from it:

```
forecast quorum calibration
```

This joins quorum disagreement to realised Brier error and reports the
relationship (correlation + mean error per band). A positive correlation means
high disagreement predicts larger error — encode that as a calibration lesson
(widen the band / shrink toward base rate when the quorum splits). The same
disagreement scalar can be produced at an information-frontier cutoff via the
agent-protocol backtest replay, so the relationship can be validated in
simulation before it is trusted live.

## Presets

| Preset    | Panel                                            | Notes |
|-----------|--------------------------------------------------|-------|
| `frontier`| Opus 4.8 + GPT-5.5 (judge: Opus 4.8)             | Highest quality, highest cost. |
| `budget`  | Gemini 3 Flash + Kimi K2.6 + DeepSeek V4 Pro     | Beats frontier solo at ~half the cost. |
| `self`    | the active model, sampled N times                | Single provider key; the lift is the judge synthesis. |
