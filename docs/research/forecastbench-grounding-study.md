# ForecastBench Grounding Study: Closed-Book Calibration of the Superforecasting Agent

**Date:** 2026-06-28 · **System:** hermes-agent superforecasting fork (`superforecasting-agent-snapshot`)
· **Model:** gpt-5.5 (ChatGPT/Codex OAuth) · **Benchmark:** [ForecastBench](https://github.com/forecastingresearch/forecastbench-datasets) (Forecasting Research Institute; ICLR 2025, arXiv:2409.19839; CC BY-SA 4.0)

## Abstract

We grounded the agent's calibration on a held-out, foreknowledge-controlled benchmark to make
the activation of terminal Platt extremization (AIA P0.1 / P2.3) an **empirical** decision rather
than a theoretical default. Over **240** closed-book forecasts on resolved ForecastBench
market-probability questions, the agent achieves a mean Brier of **0.1668** versus the
de-vigged market freeze price's **0.1629** — i.e. the agent **matches but does not beat** the
market (Δ = −0.0039). A leave-one-out alpha sweep finds the Brier-minimizing extremization
slope is **α = 1.0 (identity)** on both the 240-case ForecastBench set and the full 480-case
backtest grounding; extremizing at the theory-grounded √3 *increases* Brier (0.167 → 0.182).
The hedging diagnostic reports **no center-ward hedging**. A simplex agent+market ensemble puts
**all weight on the market** (agent weight 0.0, 95% CI [0.0, 0.325]). **Decision: do not activate
√3 extremization.** All three results share one cause — the agent was shown the market price and
anchored on it. The follow-up **market-hidden arm** (§3.4) confirms it starkly: with the price
withheld, the agent's *own* Brier collapses to **0.279** (worse than a base rate) and it becomes
**over-confident** (SCE +0.20). The agent has **no intrinsic edge over the market**; its market-visible
skill was borrowed. The strategic consequence: the edge must be *manufactured* by the harness from
fresh information the market has not priced (Gate-2 / #181), and proven out-of-sample on
future-resolving markets — never from the model's parametric knowledge alone.

## 1. Background and objective

AIA P0.1 ships terminal Platt calibration but defaults to α = 1.0 (identity); P2.3 ships the
safe-activation guards (`PLATT_ALPHA_VARIANCE_MATCH = √3`, an under-confidence help/hurt gate, and
`sweep_platt_alpha`). Activating √3 blindly is unjustified: extremization only lowers Brier when a
forecaster systematically hedges toward 0.5. With only 17 scored *live* forecasts, we lacked the
resolved data to test this. ForecastBench — the benchmark the AIA Forecaster (arXiv:2511.07678)
itself used — supplies thousands of resolved questions with a market baseline, so it is the natural
grounding set.

## 2. Methodology

**Ingestion** (`forecasting/forecastbench.py`). We fetch dated question + resolution sets and keep
**only the four market-probability sources** (manifold, metaculus, polymarket, infer), whose
`freeze_datetime_value` is a genuine 0–1 YES probability and whose `resolved_to` is a clean binary
outcome. Dataset sources (acled/fred/etc., whose freeze value is a raw level and whose resolutions
are often fractional) are dropped to avoid fabricating ground truth. Only `resolved_to ∈ {0,1}`
(±1e-6) is kept; combination/conditional questions are excluded.

**Foreknowledge controls.**
- **Closed-book seal:** the agent forecasts with an *empty toolset* — no web search and no file
  access (the latter matters: the on-disk resolution-set cache holds the answer). The live source
  URL is withheld from the agent (`resolution_source=None`; URL only in metadata), since a market
  slug often reveals the outcome.
- **Model-cutoff gate (P2.4):** gpt-5.5's training cutoff (operator-confirmed **2025-12-01**) is
  registered in `MODEL_PRETRAINING_CUTOFF`. Every question in the batch resolves **April–June 2026**,
  strictly after the cutoff, so none is foreknowledge-tainted (0 `model_cutoff_too_fresh` flags).

**Configuration.** Forecaster: gpt-5.5, closed-book, **market-visible** (the freeze market price is
shown to the agent as a legitimate forecast-time baseline — a deliberate choice for this arm).
**Sample:** 4 recent question sets (2026-06-07, 05-24, 05-10, 04-26). **Yield: 240 scored / 245
attempted** (5 dropped to provider stream timeouts; the run is resilient — skip-and-continue — so a
flaky endpoint costs cases, not the run). Per set: 31 / 50 / 76 / 83.

**Data integrity.** All 240 agent snapshots are attributed `agent_model='gpt-5.5'`,
`method='agent_protocol_v0'`; the 480 imported baselines (market + naive per question) are stored
separately (`forecast_origin='imported_baseline'`). Backtest scores are `calibration_eligible=0` by
design (they do not feed the live calibration memory); the analyses below read the raw
(probability, outcome) pairs directly.

## 3. Results

### 3.1 Forecast quality and the agent-vs-market head-to-head

| Metric | Value |
|---|---|
| n (scored ForecastBench) | 240 |
| Outcome base rate (YES) | 0.442 |
| Agent forecast spread | [0.012, 0.987], median 0.43, 1 forecast at exactly 0.5 |
| **Agent mean Brier** | **0.1668** |
| **Market (freeze) mean Brier** | **0.1629** |
| Edge (market − agent) | **−0.0039** (market slightly better) |

The agent is genuinely skilled (Brier 0.167 vs a base-rate forecaster's ≈ 0.247) and its forecasts
are well-spread across the unit interval (not degenerate). It tracks the market closely, trailing it
by a small margin.

### 3.2 Gate-1: the extremization alpha sweep

`sweep_platt_alpha` (leave-one-out, α over [1.0, 2.5]):

| Set | n | Identity Brier (α=1) | Brier-min α | Brier @ √3 (1.732) | LOO Brier |
|---|---|---|---|---|---|
| ForecastBench | 240 | 0.1668 | **1.0** | 0.1824 (worse) | 0.1668 |
| All backtest | 480 | 0.1736 | **1.0** | 0.1915 (worse) | 0.1736 |

The Brier-minimizing extremization slope is **identity** on both sets; √3 makes the Brier
materially **worse**. `diagnose_hedging` returns `center_ward_hedge = False` on both — the agent is
**not under-confident / not hedging toward 0.5**.

### 3.3 Complementarity (the AIA ensemble claim)

`simplex_brier_weights` over {market, agent}, n = 240:

| | Brier | Fitted weight | 95% CI |
|---|---|---|---|
| Market | 0.1629 | **1.000** | [0.675, 1.000] |
| Agent | 0.1668 | **0.000** | [0.000, 0.325] |

`beats_both = False`; the LOO ensemble Brier (0.1629) just equals the market. The agent adds **no
statistically distinguishable orthogonal signal** beyond the market (its weight CI includes 0). This
does **not** replicate the AIA paper's LLM+market-beats-both finding — for our configuration.

### 3.4 The market-hidden arm — the agent has no intrinsic edge

We re-ran all four sets **closed-book and market-hidden** (the freeze price withheld from the agent's
prompt via the `hidden_from_agent` baseline marker, but still scored): 245 clean cases (~98% yield, 0
skips), the agent reasoning independently (~25–60 s/forecast vs ~15–20 s when it could echo the price).
The head-to-head against the market-visible arm:

| | Market-VISIBLE (n=240) | Market-HIDDEN (n=245) |
|---|---|---|
| **Agent Brier** | 0.1668 | **0.2790** |
| Market Brier | 0.1629 | 0.1642 |
| Edge (market − agent) | −0.0039 | **−0.1148** |
| Sweep best α | 1.0 | 1.0 |
| Brier @ √3 | 0.1824 | 0.3096 |
| Hedging (center_ward_hedge / SCE) | False / +0.049 | False / **+0.204** |
| Ensemble weight (market / agent) | 1.000 / 0.000 | 0.969 / **0.031** |
| `beats_both` (agent weight CI) | False ([0, 0.325]) | False ([0, 0.177]) |

**Stripped of the market, the agent's independent forecasts are far worse — Brier 0.279, worse even
than a constant base-rate forecaster (~0.247) — and the hedging diagnostic shows the *opposite* of
hedging: SCE +0.20 means the agent is OVER-confident**, confidently wrong on questions it has no real
information about. So the visible arm's market-matching was **entirely market-anchoring**; the agent's
own knowledge-only judgment carries little signal here. The simplex ensemble nudges the agent weight
from 0.000 → 0.031 (a *sliver* of orthogonal signal) but the CI still includes 0 and `beats_both`
stays False. Gate-1 holds on this arm too (best α = 1.0; √3 hurts *more*, 0.31) — an over-confident
forecaster must not be extremized further.

## 4. Interpretation: one cause behind all three results

The agent ≈ market, shows no hedging, and adds no orthogonal signal — and all three follow from a
single design choice: **the agent was shown the market price and anchored on it** (smoke example:
agent 0.986 vs market 0.989). Anchoring makes the agent (a) inherit the market's calibration → no
hedging to correct → extremization hurts, and (b) a noisy copy of the market → no independent signal
to contribute. The results are therefore **conditional on the market-visible configuration**, and are
internally consistent with it.

The market-hidden arm (§3.4) **confirms this diagnosis and sharpens it into a strategic fact**: the
agent's good market-visible numbers were borrowed from the market, and its *own* closed-book judgment
is worse than a base rate and over-confident. This is the AIA paper's "without-search" regime made
stark — gpt-5.5's parametric knowledge on these niche / recent market questions is near-zero, so **the
edge cannot come from the model's knowledge; it must come from fresh information the market has not yet
priced.** That is not a failure of the harness — it is the harness's reason to exist: the LLM alone is
a poor, over-confident forecaster; a *system* around it (fresh agentic search, a multi-perspective
panel, calibration measured on resolved data) is what can manufacture and *prove* real skill above the
market. The path to that skill runs through the supervisor fresh-search loop (Gate-2 / #181), and the
proof must be out-of-sample on future-resolving markets (MarketNightly), where search cannot leak the
answer.

## 5. Decision

**Keep terminal Platt extremization OFF (α = 1.0).** Validated on 240 ForecastBench + 480 total
resolved forecasts: extremization does not lower — and at √3 actively raises — our Brier, because the
agent does not hedge. This is exactly the empirical gate P0.1 + P2.3 were built to support. (Gate-1
resolved; recorded in agent memory and task #180.)

## 6. Limitations and next steps

1. **Market-visible confound — now resolved (§3.4).** The market-hidden arm was run (245 cases): the
   agent has no intrinsic edge (Brier 0.279, over-confident), so the visible-arm skill was anchoring.
   The next step is therefore **Gate-2 (#181): the supervisor fresh-search loop** — does an *informed*
   independent forecast (fresh evidence the market hasn't priced) beat and complement the market? — and
   the proof must run out-of-sample on **future-resolving markets (MarketNightly, P2.1)**, where search
   cannot leak the answer (the historical-ForecastBench-with-search arm is foreknowledge-unsafe).
2. **Single model / single config.** gpt-5.5 only; no reasoning-effort sweep; no panel/quorum
   pipeline (this is a single closed-book pass, a proxy for — not identical to — the live pool).
   The intrinsic over-confidence (SCE +0.20) on no-information questions argues for a
   **de-extremize-when-uninformed** calibration mechanism (toward the base rate), the opposite of √3.
3. **n and provider attrition.** 240 clean cases; 5 dropped to provider stream timeouts (since
   mitigated by the reasoning-budget-aware idle-watchdog fix).
4. **Question classes.** Aggregate only; we have not yet broken out where the agent might beat the
   market (long-horizon, illiquid, thin, or dataset/numeric questions) — the subject of the
   companion *Beating the Market* strategy.

## Appendix: reproduction

`forecast --db <db> backtest "forecastbench:<date>" --probability-source agent-protocol --closed-book
--agent-model gpt-5.5` (dates 2026-06-07/05-24/05-10/04-26). Sweep/complementarity via
`forecasting.backtesting.sweep_platt_alpha`, `forecasting.calibration_bias.diagnose_hedging`,
`forecasting.market_ensemble.simplex_brier_weights` over the resolved (agent_p, outcome, market_p)
triples (`domain='forecastbench'`, `forecast_origin='backtest'`). The ◇ Bench desk lens
(`forecast bench`) renders the per-row + aggregate scoreboard.
