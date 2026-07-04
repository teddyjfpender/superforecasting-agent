# Deep dive — benchmarking harnesses

This is the honest shape of how the desk *proves* it forecasts well — the three
harnesses that turn "the agent emitted a probability" into a scored, foreknowledge-
controlled claim, and the one finding that reframed the whole program: **the
closed-book agent has no intrinsic edge over a prediction market, so the edge has
to be manufactured and proved out-of-sample.**

Three harnesses, three jobs:

1. **ForecastBench closed-book backtests** — fast, resolved-outcome calibration
   grounding (and where the reframing finding came from).
2. **The Live-Edge / MarketNightly harness** — foreknowledge-proof scoring on
   *open* markets that resolve in the future.
3. **The E2E journey harness** — a pytest that pins the *desk workflow* composes
   end to end.

The scoring math these feed (paired bootstrap, simplex ensemble, leak-judge,
search-ablation) is in [scoring-and-ensembles.md](scoring-and-ensembles.md) — this
page links to it rather than repeating it. The full pre-registration-grade
benchmark design is the
[Harness Benchmarking Strategy](../research/harness-benchmarking-strategy.md); the
two studies that ran are the
[ForecastBench Grounding Study](../research/forecastbench-grounding-study.md) and
the [Live Edge Study](../research/live-edge-study.md). The desk process is in
[forecasting-methodology.md](../forecasting-methodology.md).

Files: `forecasting/forecastbench.py`, `forecasting/market_nightly.py`,
`forecasting/market_nightly_forecaster.py`, `forecasting/backtesting.py`,
`forecasting/market_ensemble.py`, `scripts/live_edge_analysis.py`,
`tests/forecasting/test_full_flow_e2e.py`.

---

## 1. ForecastBench ingestion → closed-book scored backtests

### 1.1 Ingestion (`forecastbench.py`)

[ForecastBench](https://github.com/forecastingresearch/forecastbench-datasets)
(Forecasting Research Institute; ICLR 2025, arXiv:2409.19839) ships dated question
sets with resolutions. The ingestion keeps **only the four market-probability
sources** — `MARKET_SOURCES = {manifold, metaculus, polymarket, infer}` — whose
`freeze_datetime_value` is a genuine `0..1` YES probability and whose `resolved_to`
is a clean binary outcome. Dataset sources (acled, fred, yfinance, …) are dropped:
their freeze value is a raw *level* (a CPI index, a share price, an event count),
not a probability, and their resolutions are frequently fractional, so admitting
them would fabricate ground truth. Only `resolved_to` within `1e-6` of `0.0`/`1.0`
survives; combination and conditional questions are excluded.

`build_forecastbench_case` carries the freeze market probability as an external
`market` **baseline** (scored separately from the agent), and exposes
`hide_market_baseline` → the `hidden_from_agent` marker that withholds the price
from the agent's prompt while still scoring it (the market-hidden arm, §2). A
minor-but-real gotcha lives here: ForecastBench's `latest-llm.json` is a **19-byte
pointer file** naming the newest dated set, not a question set — `_resolve_latest_
date` reads through it, and the mocked tests once hid this.

### 1.2 The closed-book seal

A backtest replays a resolved question *as if* it were open at the freeze instant:

```
forecast backtest "forecastbench:<date>" \
    --probability-source agent-protocol --closed-book --agent-model gpt-5.5
```

Closed-book means the agent forecasts with an **empty toolset** — no web search and
**no file access**. The file seal matters: the on-disk resolution-set cache holds
the answer, so a file-reading agent could trivially leak it. The resolution-source
URL is withheld (`resolution_source=None`), because a market slug often reveals the
outcome. The **model-cutoff gate** (see
[scoring-and-ensembles.md](scoring-and-ensembles.md) §6.2) refuses any case whose
event window overlaps the agent-model's pretraining cutoff — in the grounding run
every question resolved strictly after gpt-5.5's confirmed 2025-12-01 cutoff, so
zero cases were foreknowledge-tainted.

### 1.3 The 2026-06-28 grounding finding — and why it reframed everything

Over **240** closed-book, **market-visible** forecasts (the freeze price shown to
the agent as a legitimate forecast-time baseline), the agent scored a mean Brier of
**0.1668** vs the de-vigged market's **0.1629** — it **matches but does not beat**
the market (edge −0.0039). Three results all pointed the same way:

- the α-sweep put the Brier-minimizing extremization slope at **1.0** (√3 *raised*
  Brier), and `diagnose_hedging` found **no hedging**;
- the simplex ensemble put **all weight on the market** (agent weight 0.0, 95% CI
  `[0, 0.325]`, `beats_both=False`).

All three follow from a **single design choice: the agent was shown the market
price and anchored on it.** Anchoring makes the agent inherit the market's
calibration (nothing to extremize) and become a noisy copy of it (nothing
orthogonal to contribute). The results are *conditional on the market-visible
configuration* — internally consistent, but not a statement about the agent's own
skill.

**The market-hidden arm is the real test — and it is stark.** Re-run closed-book
with the price *withheld*, the agent's own Brier collapses to **0.279** (worse than
a constant base-rate forecaster's ≈0.247) and it becomes **over-confident**
(`SCE ≈ +0.20`). The agent has **no intrinsic edge over the market**; its
market-visible skill was *borrowed*. The strategic consequence, now load-bearing
across the program: **the edge must be manufactured by the harness from fresh
information the market has not priced, and proved out-of-sample on future-resolving
markets** — never from the model's parametric knowledge alone. That is the reason
the Live-Edge harness (§3) exists.

### 1.4 The market-hidden arm mechanically

The `hidden_from_agent` baseline marker withholds the price from the prompt but
**still scores it** as a `baseline_comparison`, so the head-to-head and the pool
are both computable from one run.
`market_ensemble.market_hidden_pool_report(ledger, run_id)` reads a single backtest
run's paired `(market, agent, outcome)` triples
(`collect_backtest_market_llm_triples`, one row per question, de-vigged) and reports:

- `agent_brier` / `market_brier` — standalone Brier of each;
- `agent_edge_vs_market = market_brier − agent_brier` (positive ⇒ the agent, blind
  to the price, beat the market);
- `win_rate_vs_market` (ties count as a half-win);
- `pooled_brier` — the Brier of the **equal-weight log-odds pool** of agent and
  market, with `pool_beats_both`;
- the fitted `simplex` complementarity block (§scoring-and-ensembles P1.3) — the
  honest out-of-sample test of whether the agent's blind forecast adds orthogonal
  signal.

The log-odds pool and agent-vs-market comparison answer "does the agent manufacture
signal *orthogonal* to the withheld price?"; the fitted simplex proves whether that
signal has *additive* value.

---

## 2. The Live-Edge / MarketNightly harness

The grounding finding is that the closed-book LLM has no edge — so the proof must
run on **open** markets a **search-enabled** agent forecasts *before* they resolve.
This design is foreknowledge-proof **by construction**: you cannot fit to outcomes
that do not yet exist.

### 2.1 The pipeline (`market_nightly*.py`)

```
load_open_markets  → quality + foreknowledge gates → informed forecaster → record_pending → score_matured
```

- **Source + quality gates** (`market_nightly_forecaster.load_open_markets`) — open
  binary markets pulled from the ForecastBench market sources (manifold / metaculus
  / polymarket / infer). Two objectivity gates: **≥8 distinct bettors** and
  **not self-referential** (drops "Will I…/Will my…/this market…"). Volume and
  trader count are carried for sample-quality reporting.
- **Foreknowledge filter** (`sample_open_markets`) — only **strictly-future-close**
  markets survive (`_is_strictly_future_close` on `min(close, resolution)`), so the
  resolving event is in the future and live search cannot return the answer. A
  violator is rejected and counted, never stored.
- **Informed forecaster** (`build_informed_market_forecaster`) — one search-enabled
  agent per market, prompted with a **forward/live** prompt (frames the question as
  OPEN and *instructs it to search for current evidence*) — deliberately not the
  backtest prompt (which would suppress the search that is the whole point). The
  agent is **market-hidden** (never shown the price), so any agreement is
  independent, not anchoring. (Hardening scars worth noting: the forecaster was once
  *over-tooled* with the ledger-write `forecasting` toolset and polluted the live
  ledger under `--parallel`; it is now stripped to research-only `["web"]` with a
  regression test.)
- **Ledger lifecycle** — `record_pending` commits the agent snapshot
  (`forecast_origin="market_nightly"`, not calibration-eligible) at forecast time
  and attaches the **de-vigged market price** as a `market_price` baseline;
  `score_matured` scores both against the realized outcome once the market resolves.
  CLI: `forecast market-nightly run|score|report`.

### 2.2 The orthogonality result — the necessary condition, MET

The in-session, fully-powered readout is **orthogonality**: does the search-informed,
market-hidden agent *diverge* from the price (manufacture independent signal), or
merely echo it as the closed-book market-visible agent did (r≈1.0)? Across accruing
samples the divergence **strengthens monotonically** with n — it is not a small-
sample artifact:

| n | mean \|Δp\| (agent − market) | Pearson r(agent, market) | diverge >10pp |
|---|---|---|---|
| 20 | 0.078 | 0.92 | 25% |
| 39 | 0.111 | 0.79 | 28% |
| 55 | 0.127 | 0.765 | 36% |
| 292 (incl. ForecastBench open set) | 0.144 | 0.756 | 44% |

The correlation to the price *falls* and the independent move *rises* with more
data. This is the exact capability the closed-book agent lacked — the harness turns
a no-edge model into an **independent** forecaster. The **necessary** condition for
a market edge is met.

### 2.3 The sufficient condition — the scheduled scored verdict

Whether that independent signal *beats and complements* the market (paired Brier
skill + non-zero simplex weight) is a property of **resolved** markets, and is
therefore fundamentally **longitudinal** — it cannot be produced in-session without
leaking. The verdict is scheduled, not forced: a **daily cron (`948b7e4b`)** runs
`forecast market-nightly score` + `scripts/live_edge_analysis.py`, and when markets
newly resolve it appends a **Scored** entry (agent Brier vs market Brier, the paired
bootstrap CI, the simplex agent weight + `beats_both`, ECE) bound by the pre-
registered decision rule and a null-result honesty pledge.

### 2.4 The contemporaneous-vs-frozen distinction — why the first scored batch is n=1

The "agent beats the market" claim only holds against a **contemporaneous** market
price (a live-priced baseline within `CONTEMPORANEOUS_THRESHOLD_SECONDS = 48h` of
the forecast instant). ForecastBench freeze prices are stamped weeks before the
forecast, so `baseline_is_contemporaneous` quarantines them into a
**`frozen_diagnostic`** bucket that is scored and shown but can **never** enter the
headline edge.

The first scored batch (2026-06-30) is the illustration: of 4 settled markets, 3
were frozen-price and excluded. Two were near-settled NHL Stanley Cup markets where
the agent forecast 0.999 / 0.001 against a stale 0.575 / 0.422 freeze — that gap is
the agent *reading a near-decided outcome*, not out-forecasting a live market;
counting it would manufacture a fake edge. Exactly **one** market carried a genuinely
contemporaneous baseline (a Manifold box-office question, a low-probability NO both
called correctly, the agent marginally sharper). So the honest headline is a
**contemporaneous-only n=1** — no CI, no p-value, no demonstrated edge on contested
questions. The full-set number (paired edge +0.09, p=0.004) is preserved in a
`full_set` sub-object precisely so it is on the record as *inflated by the two
frozen Stanley Cup pairs* and not read as live skill. This provenance discipline —
frozen baselines can never enter the headline — is the load-bearing methodology
change.

---

## 3. The search-ablation 2×2 and the calibration/attribution gotchas

The **2×2 search-ablation** (`search_ablation.py`, price/no-price × search/no-
search, attributing the paired Brier delta to search vs judge) is detailed in
[scoring-and-ensembles.md](scoring-and-ensembles.md) §9 — it is the harness that
isolates *which lever* produced a gain, and guards against the market price faking
a "search" edge.

Two data-integrity gotchas thread every harness above:

- **`calibration_eligible`.** Backtest and imported-baseline scores are stored
  `calibration_eligible=0` **by design** — a replay must never contaminate the live
  calibration memory or the real track record. The analyses read the raw
  `(probability, outcome)` pairs directly (`list_scores(..., calibration_eligible=
  None)` returns everything; the live calibration loop reads only the eligible
  subset). Confusing the two would either poison calibration with backtest replays
  or silently drop the backtest rows from an analysis.
- **`agent_model` attribution.** Every snapshot is stamped with its `agent_model`
  (e.g. `gpt-5.5`) and `method` (`agent_protocol_v0`), and the imported market +
  naive baselines are stored separately under `forecast_origin='imported_baseline'`
  / `'backtest'`. This separation is what keeps the head-to-head honest, and it lets
  leak flags be **grouped by `agent_model`** to catch a "mirage" model that scores
  well only by exploiting leaks.

---

## 4. The E2E journey harness

`tests/forecasting/test_full_flow_e2e.py` is a different kind of benchmark: it does
not score forecast accuracy, it pins that the **desk workflow composes**. It runs
the lazy prompter's whole journey as one tested story:

```
onboard (accept-defaults) → gated tool commit → recurrence installed
   → deterministic scheduled refresh (NO LLM) → deadline-aware escalation
   → resolution (auto-score + lesson synthesis) → the desk still commits cleanly
```

Every wave's features are unit-tested elsewhere; this file pins that they *compose*.
A change that greens its own unit tests but breaks the journey — a gate that starts
refusing the auto path, a refresh that stops firing, a resolution hook that throws —
fails here first. It is the regression backstop for the autonomy spine that the
accuracy harnesses assume is working underneath them.

---

## 5. Two theses, one credibility bar

The [Harness Benchmarking Strategy](../research/harness-benchmarking-strategy.md) is
explicit that the benchmark serves **two distinct theses** that must not be
collapsed:

| Thesis | Core question | Primary benchmark |
|---|---|---|
| **Autonomous edge** | Can the harness add a little independent signal vs a registered market comparator? | Prospective market cohort, paired Brier vs the de-vigged price (the Live-Edge harness) |
| **Forecasting desk** | Can a user+agent compound superforecasting-level judgment over time? | Human+agent workflow cohorts, repeated updates, calibration, postmortems, lesson reuse |

The core principle: **do not benchmark the probability alone — benchmark the
probability plus the environment that produced it.** The strategy defines a
`ForecastCase` as the unit of evaluation (question + candidate-pool record +
pre-registration manifest + market baseline set + evidence set + agent-run set +
snapshots + resolution + score + postmortem + audit manifest), and five measurable
subclaims the harness must exercise: **C1** clean case creation (baseline + cutoff
frozen before outcome), **C2** evidence discovery, **C3** independent judgment
(market-hidden, not a noisy market clone), **C4** proper paired scoring, **C5** the
learning loop (postmortems → lessons → later-cohort policy tests). The current
292-question MarketNightly cohort is a **pilot** that partially exercises C1 and C3;
it lacks the evidence/model-run/postmortem persistence to support a full harness
claim, and the strategy is candid that it should be scored as-is and *not* used as
the main evidence that the harness improves forecasting.

The honest bottom line the studies converge on: **the necessary, hardest-to-fake
half of the value proposition — that the system manufactures real, independent,
evidence-grounded signal beyond the market — is demonstrated in-session
(orthogonality). The "provably step-function better" half is a held-out measurement
the harness has seeded and will resolve on the market's clock, not ours.**

---

## Sources

Verified against the current tree on branch `superforecasting-agent-snapshot`:

- `forecasting/forecastbench.py` — `MARKET_SOURCES`, `_is_market_source`,
  `_is_clean_binary_resolution`, `build_forecastbench_case` (the external `market`
  baseline + `hide_market_baseline`), `_resolve_latest_date` (the pointer-file
  gotcha).
- `forecasting/market_nightly.py` — `CONTEMPORANEOUS_THRESHOLD_SECONDS`,
  `baseline_is_contemporaneous`, the `frozen_diagnostic` quarantine.
- `forecasting/market_nightly_forecaster.py` — `load_open_markets`,
  `sample_open_markets`, `build_informed_market_forecaster`.
- `forecasting/market_ensemble.py` — `market_hidden_pool_report`,
  `collect_backtest_market_llm_triples` (the market-hidden arm collectors).
- `forecasting/backtesting.py` — the closed-book backtest scoring surfaces
  (`build_forecasting_evidence_status`, `benchmark_claim_status`).
- `scripts/live_edge_analysis.py` — the scored-verdict analysis driver
  (cron `948b7e4b`).
- `tests/forecasting/test_full_flow_e2e.py` — the E2E journey harness;
  `tests/forecasting/test_market_hidden_arm.py`,
  `tests/forecasting/test_forecastbench.py`,
  `tests/forecasting/test_market_nightly*.py`.
- Studies:
  [ForecastBench Grounding Study](../research/forecastbench-grounding-study.md),
  [Live Edge Study](../research/live-edge-study.md),
  [Harness Benchmarking Strategy](../research/harness-benchmarking-strategy.md),
  [Beating-the-Market Strategy](../research/beating-the-market-strategy.md).
