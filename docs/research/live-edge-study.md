# The Live Edge Study: Does the Harness Manufacture Real, Market-Beating Forecasting Skill?

**Status:** running lab notebook / pre-registration (live, updated each iteration) ·
**System:** hermes-agent superforecasting fork (`superforecasting-agent-snapshot`) ·
**Companions:** [ForecastBench Grounding Study](forecastbench-grounding-study.md) ·
[Beating-the-Market Strategy](beating-the-market-strategy.md)

> This document is written as a publishable research report and updated as data arrives. Sections
> marked **[LIVE]** are appended to each loop iteration with timestamped results; the methodology and
> pre-registration (§2–§4) are fixed *before* results are collected, so the analysis cannot be tuned
> to the data.

---

## Abstract

A companion study established that our closed-book LLM forecaster has **no intrinsic edge** over a
de-vigged prediction market: on 240 resolved ForecastBench questions its market-*visible* forecasts
merely *echo* the price (Brier 0.167 ≈ market 0.163, zero ensemble weight), and stripped of the price
(market-*hidden*) its own judgment collapses to Brier 0.279 — worse than a base rate, and
over-confident. The conclusion was sharp: **the model's parametric knowledge carries no edge; any edge
must be manufactured by the harness from fresh information the market has not yet priced, and proven
out-of-sample on future-resolving markets where search cannot leak the answer.** This study is that
proof. We forecast **open** prediction markets with a **search-enabled** agent, record the agent's
probability and the de-vigged market price *at forecast time*, and score on resolution. The design is
foreknowledge-proof by construction (we cannot fit to outcomes that do not yet exist) and the central
question is whether informed, independent forecasts **(a)** diverge from the market (manufacture
orthogonal signal) and **(b)** beat and complement it once resolved.

---

## 1. Motivation and the bar

The product thesis is not "an LLM that forecasts" — the LLM alone is demonstrably worse than a base
rate. The product is the **environment**: a harness that feeds the model fresh information (agentic
search), forces independent reasoning (panel/quorum), measures calibration on resolved outcomes, and
**proves the resulting skill out-of-sample**. The last clause is the moat: anyone can claim skill;
almost no one can *demonstrate* it on held-out, foreknowledge-proof resolutions.

Two prior results frame this study:

- **No intrinsic edge (grounding study §3.4).** Market-hidden, closed-book: Brier **0.279**, SCE
  **+0.20** (over-confident). The model knows little about these niche/near-term questions.
- **Search is the only lever (strategy §0.2, §5).** The AIA Forecaster (arXiv:2511.07678) found
  agentic search decisive (0.114 with search vs 0.123 without), and that an LLM+market ensemble beats
  the market even when the LLM loses head-to-head — *if* the LLM carries orthogonal information. Our
  Gate-2 work wired a live fresh-search loop; this study tests whether it produces that orthogonal,
  market-beating signal.

**The bar for "the harness shows its value":** not a single number, but a chain of evidence —
(i) the harness runs end-to-end on live open markets; (ii) the search-informed agent's forecasts
**diverge** from the market (it is not echoing); (iii) on resolved markets, the agent **complements**
the market (non-zero ensemble weight) and ideally **beats** it (lower Brier), with the paired,
pre-registered test; (iv) the divergences are **toward the truth** on the fast-resolving subset
observable in-session. We hold ourselves to the same skepticism the grounding study applied to
extremization: a divergence that is just noise, or a lift that is just leakage, is not skill.

---

## 2. The harness under test

The pipeline (all on `superforecasting-agent-snapshot`; commits `54dbc9391`, `eda28cf7d`):

1. **Source + quality gates** (`market_nightly_forecaster.load_open_markets`). Open binary markets are
   pulled from Manifold (Metaculus is HTTP-403-blocked from this runtime — a documented limitation).
   Manifold is open-creation play-money, so two gates keep the sample objective: **≥ 8 distinct
   bettors** (`uniqueBettorCount`) and **not self-referential** (`_looks_personal` drops
   "Will I…/Will my…/this market…"). `n_traders` + `volume` are carried for sample-quality reporting.
2. **Foreknowledge filter** (`sample_open_markets`, re-asserted in `record_pending`). Only
   **strictly-future-close** markets survive (`_is_strictly_future_close` on `min(close, resolution)`),
   so the resolving event is in the future and live search cannot return the outcome. A violator is
   rejected and counted, never stored.
3. **Informed forecaster** (`build_informed_market_forecaster`). One search-enabled agent
   (`build_agent`, toolsets `["forecasting","file","web"]`, codex/gpt-5.5, built once and reused) per
   market. It is prompted with a **forward/live** prompt (`build_live_market_messages`) that frames the
   question as OPEN and *instructs it to use web search for current evidence* — explicitly **not** the
   backtest prompt (which would tell it "use only supplied data, do not infer from later information",
   suppressing the search that is the whole point). The agent is **market-hidden** — never shown the
   price — so any agreement is independent, not anchoring. Failure → `None` → the market is skipped.
4. **Ledger lifecycle.** `record_pending` commits the agent snapshot (`forecast_origin=
   "market_nightly"`, not calibration-eligible) at forecast time and attaches the **de-vigged market
   price** (`default_market_devig`) as a `market_price` baseline; `score_matured` scores both against
   the realized outcome once the market resolves. CLI: `forecast market-nightly run|score|report`.

The live quorum + supervisor fresh-search loop (Gate-2) it builds on required three codex-only-deployment
fixes the Gate-2 smoke surfaced (commit `585e73639`: detached-worker plugin discovery; `build_agent`
provider auto-resolution instead of hardcoded OpenRouter; `config["model"]`-dict id extraction). Those
are documented in the strategy report and roadmap memory.

---

## 3. Methodology (pre-registered)

### 3.1 Substrate
Open binary prediction markets (manifold / metaculus / polymarket / infer — the same market-probability
sources as ForecastBench), sampled **strictly future-close** so the resolving event lies in the future
and live search cannot return the outcome. Each market contributes one record at forecast time:
`(agent_p, market_p_devigged, close_time, market_id)`.

### 3.2 Arms
- **M0 — market.** The de-vigged freeze price. The constant baseline, always scored.
- **A_search — informed agent.** A single search-enabled agent (codex/gpt-5.5 + `web` toolset),
  forecasting from the question text + fresh search only; it is **not** shown the market price
  (market-hidden), so any agreement is independent, not anchoring.
- **E — ensemble.** Simplex-constrained log-odds pool of {M0, A_search} (`market_ensemble.py`).

### 3.3 Pre-registered metrics and decision rule
- **Orthogonality [in-session, no resolution needed]:** distribution of `|logit(agent_p) −
  logit(market_p)|`; correlation of agent vs market; fraction of markets where the agent moves
  >0.05 from the price. The market-visible ForecastBench agent had ~zero divergence (it echoed);
  a search-informed market-hidden agent that *also* echoes would falsify the orthogonality premise.
- **Calibration:** reliability curve + ECE of `A_search` on the resolved subset.
- **Accuracy:** mean Brier of `A_search` vs `M0` on resolved markets; **paired bootstrap** of the
  difference (the P0.2 machinery, seed pinned), reported with a 95% CI.
- **Complementarity:** `simplex_brier_weights({market, agent})` on the resolved subset — non-zero
  agent weight + `beats_both` is the headline.
- **Decision:** the harness "shows value" when, on an accruing resolved sample, `A_search` carries
  **non-zero ensemble weight** (orthogonal signal that helps) and the ensemble Brier is **≤** the
  market's, trending toward significance as n grows. We pre-commit to reporting a *null* result
  plainly if the agent diverges but does not help.

### 3.4 Foreknowledge controls
Strictly-future-close sampling (event in the future); the agent is market-hidden (no price anchor);
agent_p recorded at forecast time (never back-filled); resolution pulled only at scoring time. This is
clean by construction — unlike a search-enabled replay of *resolved* ForecastBench questions, which
would leak (searching a settled question returns its answer) and is therefore **excluded** from the
primary analysis.

### 3.5 Power and honesty
Per the strategy's power analysis, certifying a ~0.02 Brier edge needs n ≈ 280–400 resolved markets —
weeks of accrual. **No in-session result will be statistically powered.** We therefore report
in-session: (a) orthogonality (fully powered now), (b) the seeded longitudinal record, and (c) a
small-n directional read from fast-resolving markets — and we will not over-claim significance from
an underpowered sample.

---

## 4. Results  **[LIVE — appended each iteration]**

### Iteration 1 — 2026-06-28 · harness up, first sample firing

- **Harness built + committed** (`54dbc9391`, `eda28cf7d`); full forecasting suite green (1548).
  The Gate-2 smoke that preceded this caught and fixed three bugs that had silently broken the *entire*
  live quorum in this codex-only deployment (`585e73639`) — itself a demonstration of the testable
  environment surfacing real defects.
- **Candidate pool (Manifold, post-quality-gate):** **174** objective, liquid (≥8-trader),
  non-self-referential open binary markets. Many close **today/tomorrow** (e.g. *Will Canada qualify
  for the round of 16?* p≈0.73 close 18:59; *Will WTI crude be above \$76 on Jun 30?* p≈0.20; *Will
  X.com be accessible in the UK on 30 Jun?* p≈0.97; *Will Serena Williams play singles at Wimbledon
  2026?* p≈0.98) — so a meaningful fraction will **resolve within the study window**, giving an
  in-session scored read alongside the longitudinal record. Metaculus: HTTP 403 from this runtime
  (limitation).
- **First sample fired:** `market-nightly run -n 20 --source manifold --seed 1` into the live ledger —
  the search-informed, market-hidden agent forecasting 20 markets, recording `agent_p` +
  de-vigged `market_p` at forecast time. Results (orthogonality + any in-session resolutions) appended
  next iteration.

*(orthogonality + scored metrics pending the sample's completion)*

---

## 5. Limitations

- The decisive accuracy proof is **longitudinal**; in-session we can show orthogonality + a seeded
  record + a small-n read, not significance.
- Single model (codex/gpt-5.5), single search backend (keyless DuckDuckGo `ddgs`); no model or
  search-provider sweep yet.
- Market de-vig is a simple proportional model; venue-specific vig structure is not modelled.
- The supervisor fresh-search *round* (Gate-2) fires only when the judge flags an information gap; the
  primary agent here uses its own in-loop `web` search, which is the dominant fresh-evidence channel.
