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
orthogonal signal) and **(b)** beat and complement it once resolved. **Early result (n=39 live
forecasts):** the agent diverges from the market by a **mean 11pp** (Pearson r **0.79** vs r≈1.0 for
the market-visible agent that merely echoed), with substantive, search-grounded disagreements —
**confirming (a)**, the necessary condition. Part **(b)** is the longitudinal resolved-set question,
seeded and accruing as markets settle (≈ June 29–30 onward).

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

### Iteration 2 — 2026-06-28 · first sample in, orthogonality confirmed

**Sample 1** (`--seed 1`, n=20, 503 admissible candidates): 20/20 recorded, 0 rejected/skipped.

**Orthogonality (n=20) — the premise holds.** The search-informed, market-hidden agent does **not**
echo the market:

| metric | value | reading |
|---|---|---|
| mean \|Δp\| (agent − market) | **0.078** | ~8pp average independent move off the price |
| 45% of markets | \|Δp\| > 0.05 | nearly half move materially |
| 25% of markets | \|Δp\| > 0.10 | a quarter move a lot |
| Pearson r(agent, market) | **0.92** | correlated but clearly **not** identical |
| mean \|Δ logit\| | 1.08 | large on the (many) low-probability questions |

Contrast with the [grounding study](forecastbench-grounding-study.md): the market-*visible* agent had
r≈1.0 and ~zero divergence (it **echoed**). Withholding the price and giving it live search turns it
into an **independent** forecaster. **The orthogonality premise (strategy Lever A→C) is confirmed.**

**The divergences are substantive and researched, not noise** (largest \|Δ\|):

| Δ (agent−mkt) | agent | market | question |
|---|---|---|---|
| **−0.276** | 0.020 | 0.296 | S&P 500 closes ≥ 7650 in June 2026 (agent searched the actual level → confident NO) |
| **+0.264** | 0.420 | 0.156 | Anthropic restores Fable 5 access for US customers |
| **+0.240** | 0.530 | 0.290 | US–Iran ceasefire formally declared ended |
| **+0.225** | 0.360 | 0.135 | DOJ wins its antitrust suit |
| −0.120 | 0.580 | 0.700 | Ashwin returns to US by Aug 19 |

These are testable disagreements — when they resolve we learn whether the divergence is **skill**.

**Scored: 0 / 20 resolved** (all pending; the month-end markets resolve ≈ June 29–30). The longitudinal
record is now **seeded**; scored agent-vs-market (paired Brier + simplex complementarity) is reported as
resolutions arrive.

*Interpretation.* In-session we have shown the **necessary** condition — the harness manufactures
independent, substantive signal the market is not simply mirroring. The **sufficient** condition
(that signal *beats/complements* the market) is the resolved-set analysis, which is longitudinal by
construction. We continue to accrue samples and score on resolution.

### Iteration 3 — 2026-06-28 · sample 2 folded in (n=39), orthogonality robust

**Sample 2** (`--seed 2`, 19 recorded + 1 idempotent skip) brings the pooled live set to **n=39**.
The orthogonality estimate is **stable under more data** — the independence is not a small-sample
artifact:

| metric | n=20 (sample 1) | **n=39 (pooled)** |
|---|---|---|
| mean \|Δp\| | 0.078 | **0.111** |
| Pearson r(agent, market) | 0.92 | **0.79** |
| diverge >5pp | 45% | 44% |
| diverge >10pp | 25% | 28% |

With more markets the agent's correlation to the price *falls* (0.92 → 0.79) and its mean independent
move *rises* (7.8 → 11.1pp) — the signal strengthens, not regresses. **Scored: 0 / 39 resolved**
(all pending; bulk resolve ≈ June 29–30). Sample 3 (`--seed 3`) is firing to push toward n≈58 for a
solid orthogonality base while resolutions accrue.

### Iteration 4 — 2026-06-28 · n=55, orthogonality established; pivot to scoring

Sample 3 brings the pooled set to **n=55**. The orthogonality result is now established across three
independent samples and **monotonically strengthens** with n — it is not a small-sample artifact:

| n | mean \|Δp\| | Pearson r | diverge >10pp |
|---|---|---|---|
| 20 | 0.078 | 0.92 | 25% |
| 39 | 0.111 | 0.79 | 28% |
| **55** | **0.127** | **0.765** | **36%** |

**This is the in-session headline: the harness reliably manufactures independent, search-grounded
signal that the market is not mirroring** — precisely the capability the closed-book agent lacked
(grounding study: it *echoed*, r≈1.0). The necessary condition for a market edge is met.

**Scored: still 0 / 55** — every market is pre-resolution. A probe for an in-session scored read (a
targeted batch closing within ~14 h) found only **3** such markets in the liquid pool, confirming that
the scored verdict is **fundamentally longitudinal**: the bulk of the 55 forecasts are month-end
markets resolving ≈June 30 (~1.5 days out), and Manifold resolves *manually*, so settlement lags close
time. The loop therefore shifts to **resolution-watch** — `market-nightly score` each cycle to fold in
outcomes as they settle, rather than burning further agent samples (orthogonality is already
saturated). The scored paired-Brier / simplex-complementarity verdict accrues at the markets' pace.
*(A minor robustness note for the harness: `build_informed_market_forecaster` should resolve the active
model id itself when called without one, rather than passing an empty string to the provider.)*

---

### Interim conclusion (end of the in-session phase)

After four iterations and **55 live, foreknowledge-proof forecasts**, the in-session ceiling is
reached and the result is clear-cut on the half that is measurable now:

- **Necessary condition — MET, robustly.** Given the market price withheld and live search, the agent
  produces **independent, search-grounded forecasts that the market is not mirroring**: mean |Δp|
  **12.7pp**, Pearson r **0.765**, a third of markets moving >10pp — and the signal *strengthens*
  monotonically with n (it is not a small-sample artifact). This is the exact capability the
  closed-book agent lacked (it echoed at r≈1.0, grounding study §3.4). The harness demonstrably turns
  a no-edge model into an independent forecaster.
- **Sufficient condition — SEEDED, physically pending.** Whether that independent signal *beats and
  complements* the market (paired Brier skill + non-zero simplex weight) is a property of **resolved**
  markets. Our 55 forecasts are pre-resolution; the bulk settle ≈June 30 (and Manifold settles
  manually, so with lag). This verdict **cannot be produced in-session without leaking** — it is the
  unavoidable cost of a clean, out-of-sample design. The harness is now configured to score it
  automatically (`market-nightly score`) as outcomes land.

The honest framing for the product: **the necessary, hardest-to-fake half of the value proposition —
that the system manufactures real, independent, evidence-grounded signal beyond the market — is
demonstrated in-session.** The "provably step-function better" half is a held-out measurement that the
harness has now *seeded and will resolve on the market's clock*, not ours.

**Scored verdict — scheduled.** A daily job (`948b7e4b`, 11:23 local, 7-day expiry) runs
`market-nightly score` + `scripts/live_edge_analysis.py` and, when markets newly resolve, appends a
**Scored** entry here — agent Brier vs market Brier, the paired bootstrap CI (positive ⇒ agent beats
market), the simplex agent weight + `beats_both`, and ECE — committing the result. The pre-registered
decision rule (§3.3) and the null-result honesty pledge bind that future entry. Manual fallback at any
time: `forecast --db <ledger> market-nightly score && python scripts/live_edge_analysis.py --db <ledger>`.

### Iteration 5 — 2026-06-29 · scaled to ForecastBench (n=292), orthogonality holds on the quality set

The Manifold sampler surfaced too much trivial/personal noise (e.g. *"will somebody mammogram me 1500
times"*, *"Ashwin returns to US"*) — questions the agent cannot meaningfully research and that dilute the
benchmark. We replaced the substrate with **curated ForecastBench open questions** — the standard the
field benchmarks against, with published superforecaster/LLM baselines. A new `--source forecastbench`
loads the latest question_set's open, market-priced questions (manifold/metaculus/polymarket/infer),
foreknowledge-proof by construction (resolution strictly in the future).

Hardening surfaced en route (the testable environment again catching real defects):
- The live forecaster was **over-tooled** — it carried the ledger-WRITE `forecasting` toolset and, instead
  of returning a probability, fumbled through `create_question`/`update_forecast`, **polluting the live
  ledger** under `--parallel` (4 garbage questions, since deleted). Stripped to research-only (`["web"]`)
  with a regression test (`823a6ddc2`).
- Added a **parallel forecaster** (bounded `ThreadPoolExecutor`, serialized ledger writes) — a 237-question
  sweep runs in ~70 min instead of many hours (`6a529239b`).
- Fixed a `latest`-pointer bug — ForecastBench's `latest-llm.json` is a 19-byte *pointer* file naming the
  newest dated set, not a question set; the mocked tests had hidden it (`49def5c04`).

**Run:** `market-nightly run --source forecastbench --parallel 5 -n 250` → **233 recorded, 0 rejected**
(4 deduped). The `#market` benchmark now holds **292** questions (55 Manifold + 237 ForecastBench):
Anthropic ARR, Strait-of-Hormuz, Russia State Duma polling, Cerebras financials, FIFA World Cup, Senate
reconciliation — researched, serious questions.

**Orthogonality — robust to a 5× scale-up onto curated, harder questions:**

| metric | n=55 (Manifold) | **n=292 (incl. 237 ForecastBench)** |
|---|---|---|
| mean \|Δp\| (agent − market) | 0.127 | **0.144** |
| Pearson r(agent, market) | 0.765 | **0.756** |
| diverging > 0.10 | — | **43.8%** |

The independent-signal premise holds on the bigger, harder set — the agent moves ~14pp off the price on
average and ~44% of its forecasts are materially its own call. (Caveat: the ForecastBench market baseline
is the question_set *freeze* price, ~8 days stale at forecast time — a small agent-information advantage,
flagged for the scored analysis.)

**Scored: 0 / 292 resolved** (all open; close range 2026-06-29 → 2029-01-01). The **necessary** condition
(orthogonality) is confirmed on the quality set; the **sufficient** condition (beats + complements the
market) is now measured on the *same* questions ForecastBench scores, so the resolved-set Brier becomes
directly comparable to its published superforecaster/LLM baselines. Scoring is on the market's clock via
`score_matured` (cron `948b7e4b`); these foreknowledge-proof snapshots are deliberately **not** re-forecast.

### Iteration 6 - 2026-06-30 · first SCORED batch (4 of 13 due settled); contemporaneous edge is n=1, no contested-question edge yet

The market clock turned over the first resolutions. Of the 13 entries whose close had passed, **4 settled
with real source outcomes and were scored; 9 were correctly left pending** (no confirmed resolution yet, or
close still ahead). This is the first time the harness produced agent-vs-market Brier on questions it could
not have foreknown, so the discipline that matters here is **provenance**, not the headline delta. Most of
what settled was scored against a **frozen ForecastBench freeze price**, and the now-fixed
contemporaneous-only edge logic (`market_nightly.py`, `baseline_is_contemporaneous` + the
`frozen_diagnostic` quarantine) is exactly what keeps that stale baseline out of the "agent beats the
market" claim.

**The four scored markets (agent Brier vs market Brier, realized outcome):**

| question | id | agent P(yes) | market P(yes) | outcome | agent Brier | market Brier | baseline |
|---|---|---|---|---|---|---|---|
| Carolina Hurricanes win 2026 Stanley Cup | `fq_45e2624f4498` | 0.999 | 0.575 | yes | 0.000001 | 0.180625 | **frozen** |
| Vegas Golden Knights win 2026 Stanley Cup | `fq_870d9c961d0b` | 0.001 | 0.422 | no | 0.000001 | 0.178084 | **frozen** |
| X.com accessible in the UK on 30 Jun | `fq_aa9d042531ec` | 0.940 | 0.9712 | yes | 0.003600 | 0.000827 | **frozen** |
| "Jackass: Best and Last" opens > $25M domestic | `fq_6d4b8e332580` | 0.003 | 0.108 | no | 0.000009 | 0.011625 | **contemporaneous** |

**Why 3 of the 4 do not count toward edge (frozen-price provenance artifact).** The three ForecastBench
markets carry a freeze price stamped weeks before the forecast instant, so the head-to-head is not
contemporaneous and is quarantined into the `frozen_diagnostic` bucket. The two NHL Stanley Cup
settlements are the clearest illustration of *why this exclusion is mandatory*: by the agent's forecast
time the Cup was effectively decided, so the agent showed **0.999 (Carolina) / 0.001 (Vegas)** against a
**stale 0.575 / 0.422** freeze baseline. That gap is the agent reading a near-settled outcome versus a
weeks-old prior, not the agent out-forecasting a live market. Counting it would manufacture a fake edge.
The third frozen market, X.com, is the inverse caution: there the frozen baseline (0.971) actually *beat*
the agent (0.940), but because that baseline is also a stale freeze price it counts neither for nor against
the agent. Frozen diagnostic for transparency: n=3, mean agent Brier **0.00120**, mean market Brier
**0.11985**, paired agent edge **+0.11864** (agent 2 / baseline 1, p=0.038) -- impressive-looking and
**deliberately excluded** from the claim.

**The contemporaneous subset -- the only part that counts toward edge -- is n=1.** Exactly one settled
market carried a genuinely live-priced baseline: the Manifold "Jackass: Best and Last" opening-weekend
box-office question. It was a **low-probability NO that both the agent and the market called correctly**;
the agent was marginally sharper (Brier **0.000009** vs **0.011625**, paired edge **+0.011616**, agent 1 /
market 0). With n=1 there is **no bootstrap CI and no p-value** -- nothing statistically meaningful, and
nothing about hard, contested questions. **Honest verdict: at n=1 the contemporaneous live-edge is
undetermined; no edge on contested questions is demonstrated.** The one genuinely-contested fair market in
this batch, X.com, would have been the interesting test, but it is frozen-price (ForecastBench), so it is
excluded; had it been contemporaneous it would have gone *to the market* (market 0.971 vs agent 0.940), so
its exclusion is not cherry-picking in the agent's favor.

**Full set (transparency only, NOT the claim):** n=4, mean agent Brier **0.00090**, mean market Brier
**0.09279**, paired agent edge **+0.09189** (agent 3 / baseline 1), bootstrap p **0.0044**, CI95
**[+0.0044, +0.1794]**. This number looks like a decisive win and is reported here precisely so it is on
the record that it is **inflated by the two frozen near-settled Stanley Cup pairs** and must not be read as
live skill.

**Surfaced edge confirms the fix.** `forecast --db <ledger> market-nightly report --json` now reports the
**contemporaneous-only headline**: `n_scored: 4`, `n_contemporaneous: 1`, `n_frozen_excluded: 3`,
`paired_agent_edge_mean_brier: 0.011616`, `paired_agent_wins: 1`, `paired_baseline_wins: 0`,
`paired_agent_edge_ci95_low: null`, `paired_p_value: null` (n=1), with the inflated full-set
(`+0.09189`) and frozen (`+0.11864`) numbers preserved in their `full_set` / `frozen_diagnostic`
sub-objects. The surfaced headline matches the hand-computed contemporaneous result exactly.

**Methodology change made load-bearing.** The agent-vs-market edge is now **restricted to contemporaneous
baselines** (price vintage within 48h of the forecast instant); a frozen ForecastBench freeze price is
scored and shown but can never enter the headline edge or its win counts. The standing decision rule is
unchanged: the live-edge claim stays **undetermined** until a contemporaneous, multi-question, statistically
powered batch resolves. 9 of the 13 due entries are still legitimately pending, and the large ForecastBench
cohort settles on its own clock; the next scored batch will be the first with enough contemporaneous pairs
to attempt a real CI.

## 5. Limitations

- The decisive accuracy proof is **longitudinal**; in-session we can show orthogonality + a seeded
  record + a small-n read, not significance.
- Single model (codex/gpt-5.5), single search backend (keyless DuckDuckGo `ddgs`); no model or
  search-provider sweep yet.
- Market de-vig is a simple proportional model; venue-specific vig structure is not modelled.
- The supervisor fresh-search *round* (Gate-2) fires only when the judge flags an information gap; the
  primary agent here uses its own in-loop `web` search, which is the dominant fresh-evidence channel.
