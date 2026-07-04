# Deep dive — scoring, calibration & ensembles (the AIA map)

This is the honest map of the twelve mechanical levers ported from the **AIA
Forecaster technical report** (Bridgewater AIA Labs, arXiv:2511.07678) into the
desk, with the one thing the port audit cares about most stated for each: **is the
activation gate ON or deliberately OFF, and why.** Several of these levers are
*present in the code but default to a no-op* — that is a design choice, not an
oversight, and the reasons are empirical (measured on resolved data), not
theoretical.

The plan this map implements is
[docs/plans/aia-forecaster-improvements.md](../plans/aia-forecaster-improvements.md);
the empirical study that set several of the gates is the
[ForecastBench Grounding Study](../research/forecastbench-grounding-study.md); the
harnesses that measure all of this are in
[benchmarking-harnesses.md](benchmarking-harnesses.md). The desk pipeline these
slot into is in [forecasting-methodology.md](../forecasting-methodology.md). This
page is the math and the gate status.

Files: `forecasting/bayes_toolkit.py`, `forecasting/panel.py`,
`forecasting/quorum.py`, `forecasting/supervisor_search.py`,
`forecasting/calibration_bias.py`, `forecasting/market_ensemble.py`,
`forecasting/leak_judge.py`, `forecasting/leak_prevalence.py`,
`forecasting/leak_domains.py`, `forecasting/search_ablation.py`,
`forecasting/backtesting.py`, `forecasting/ledger/scoring.py`.

---

## 0. Where the fork already led — the deterministic pool

The paper documents two failure modes: naive-LLM-aggregation (an LLM reads all the
forecasts and re-emits a number — scores *worse* than the mean) and best-of-k
selection (also worse than the mean). The fork is structurally ahead of both: **the
committed number is a deterministic pool, never an LLM free-picking a value.**
`panel.aggregate_panel_estimates` pools via **trimmed geometric-mean-of-odds**
(`log_odds_pool` with a trim), the judge sits *on top*, and the soul forbids the
agent from reinventing the aggregation. So the AIA levers below are refinements on
an already-correct spine, not a rescue.

The paper's headline "previously-undocumented equivalence" is also already ours:
**a log-odds pool followed by Platt scaling is exactly Platt-of-the-geometric-mean-
of-odds** (Baron 2014 Eq. 2). Both halves live in `bayes_toolkit`; the port's job
was to unify them and decide when to fire the second half.

The formal pipeline order the levers assemble (each stage records its pre/post
probability, so the chain is reversible and auditable):

```
research → M independent draws → log-odds pool (trimmed geomean-of-odds)
        → agentic supervisor (detect disagreement → fresh search → confidence-gated synthesis)
        → terminal fixed-α Platt on the single reconciled scalar
        → (optional) simplex blend with the de-vigged market price
        → commit
```

---

## 1. The one recalibration operator (P2.5)

There is exactly **one** sigmoidal recalibrator on the desk, in `bayes_toolkit`:

```
platt_scale(p, α, d)          = inv_logit( α·logit(p) + log(d) )
extremize(p, factor)          = platt_scale(p, α=factor, d=1)          # a thin alias
platt_scale_anchored(p, b, α) = inv_logit( logit(b) + α·(logit(p) − logit(b)) )
```

- `α` is the log-odds slope: `α>1` sharpens away from `0.5`, `α<1` flattens toward
  it, `α==1` is the **exact identity** (the kernel never silently extremizes).
- `d` is a multiplicative odds bias (`d==1` unbiased).
- `PLATT_ALPHA_VARIANCE_MATCH = √3 ≈ 1.732` — the Neyman–Roughgarden variance-
  matching slope (the `n>50` limit of the closed-form), the *theory-grounded value
  to activate with* but never a kernel default.
- `platt_scale_anchored` extremizes the deviation from a **reference-class base
  rate** rather than from `0.5`; `α==1` is the identity for any base rate, and
  `base_rate==0.5` reduces exactly to `platt_scale` (`logit(0.5)==0`).

`extremize` being a *thin alias* is the anti-drift consolidation (P2.5): the
lesson-Platt path (`learning.py`), the ensemble-extremize path, and the panel's
terminal stage all call the same kernel, and the geometric-mean == Platt identity
is locked by a regression test so the two paths can never diverge.

---

## 2. Activation gate map — ON vs deliberately OFF

| Slice | Mechanism | Where | Gate status | Why |
|---|---|---|---|---|
| P0.1 | Terminal fixed-α Platt on the committed aggregate | `panel.aggregate_panel_estimates` (`alpha_extremize`) | **OFF by default (`α=1.0`, strict no-op)** | Empirically: on 240 ForecastBench cases the Brier-minimizing α is **1.0**; √3 *raises* Brier 0.167→0.182; no hedging to fix |
| P0.2 | Paired recenter-at-zero bootstrap + win-rate-vs-best | `ledger/scoring.py` | **ON** (reporting) | Pure diagnostic; turns a point edge into a significance-backed verdict |
| P0.3 | Confidence-gated judge override of the pool | `quorum.resolve_final_probability` | **ON in the quorum path** — fires only on a `high`-confidence judge | Bounded downside: a low/medium judge can never drag the number off a sound pool |
| P1.1 | Agentic-supervisor fresh-search loop | `quorum.run_quorum` + `supervisor_search.py` | **Wired for live quorum; fires only on a judge-flagged gap** (`search_runner=None` ⇒ no-op) | Fresh info is the only lever that can beat a market it hasn't priced |
| P1.2 | Content-aware foreknowledge leak-judge + robustness bounds | `leak_judge.py`, `ledger.rescore_backtest_run`, `leak_prevalence.py` | **Opt-in at backtest time; calibration UNCALIBRATED** | Trust, not Brier; the true-rate back-out is honest only once hand-labelled |
| P1.3 | Simplex market+LLM Brier-minimizing ensemble | `market_ensemble.simplex_brier_weights` | **ON as analysis; live advisory weight gated** (`n≥30 ∧ beats_both ∧ CI excludes 0`) | Ship the blend only where LOO proves out-of-sample additive value |
| P1.4 | Simple-mean baseline + ensemble-size variance curve | `bayes_toolkit.mean_probability`, `panel.PANEL_AGGREGATION_METHODS` | **Selectable; desk default stays `trimmed_geomean_odds`** | The convexity floor any pool must beat, recorded alongside — not replacing — the geomean |
| P2.1 | MarketNightly foreknowledge-proof live benchmark | `forecasting/market_nightly*.py` | **ON as a job** (see [benchmarking-harnesses.md](benchmarking-harnesses.md)) | The only structurally-unleakable test |
| P2.2 | Search-ablation 2×2 (price/no-price × search/no-search) | `search_ablation.py` | **ON, read-only, opt-in** | Attributes any gain to the specific lever |
| P2.3 | Help/hurt gate + base-rate-anchored form + hedging histogram + α-sweep | `calibration_bias.py`, `backtesting.sweep_platt_alpha` | **ON as guards** (they only ever *remove* extremization) | Make P0.1 safe: never extremize a wrong-sided or non-hedging scope |
| P2.4 | Time-travel source pinning + leak-domain denylist + model-cutoff gate | `leak_domains.py`, `models.MODEL_PRETRAINING_CUTOFF` | **Denylist tagging ON; cutoff gate ON in backtests** | Attack the leak mechanism at the root, protecting live forecasts too |
| P2.5 | Unify extremize/Platt into one operator | `bayes_toolkit.extremize` alias | **ON** | Anti-drift; the identity locked by a regression test |

The recurring theme: **the recalibration and blend levers are built, correct, and
default to the identity/analysis regime.** They flip on only behind an empirical
gate measured on resolved data — the opposite of a blind theoretical default.

---

## 3. Terminal Platt calibration + the safety guards (P0.1, P2.3)

### 3.1 The terminal stage

`panel.aggregate_panel_estimates(..., alpha_extremize=1.0)` pools, then applies one
terminal Platt scale to the single reconciled scalar:

```
aggregate = pool(estimates, method)                      # trimmed geomean-of-odds
if α ≠ 1.0:
    pre_extremize = aggregate
    aggregate     = platt_scale(aggregate, α, d=1)
```

At the default `α=1.0` the branch is a **strict no-op**: `pre_extremize_probability`
stays `None`, `terminal_calibration_applied=False`, and the aggregate is byte-
identical to the bare pool. When it fires, the pre/post probabilities and the
applied α are persisted so the stage is fully auditable and reversible.

### 3.2 Why it is OFF

Terminal Platt is the paper's single highest-leverage change (Brier 0.1140→0.1076),
so leaving it off is a deliberate, *measured* decision. Extremization only lowers
Brier when a forecaster systematically **hedges toward 0.5**. The
[ForecastBench Grounding Study](../research/forecastbench-grounding-study.md)
tested this on resolved data: the LOO Brier-minimizing α is **1.0** on both the
240-case ForecastBench set and the 480-case full backtest; √3 makes Brier
materially *worse*; and `diagnose_hedging` returns `center_ward_hedge=False` — the
agent does not hedge (in the market-hidden arm it is over-confident, `SCE ≈ +0.20`,
the *opposite* of the condition extremization fixes). So the empirical gate the
port was built to support correctly keeps α at the identity.

### 3.3 The three safety guards (so P0.1 can only ever help)

These live in `calibration_bias.py` and only ever *remove* extremization:

- **`extremization_alpha_gate`** — permits `α>1` on a scope only when it is
  genuinely **under-confident on its leaned side**: the leaned-side empirical hit
  rate must exceed the *mean committed forecast* on that side by a margin (`0.02`),
  with sufficient effective sample. Gating on `hit_rate > 0.5` is *insufficient* —
  a scope leaning 0.7 that is right 0.59 of the time is correct-sided yet over-
  confident, and extremizing it raises Brier. `α≤1` always passes through unchanged.
- **`diagnose_hedging`** — histograms the **raw pre-adjustment** `P(yes)` and
  returns `center_ward_hedge=True` only when BOTH the central-mass fraction
  (weighted share in `[0.35, 0.65]`) is high (`≥0.5`) AND `SCE<0` (genuinely under-
  confident). A sharp or over-confident scope is therefore never told to extremize.
- **`platt_scale_anchored`** — the base-rate-anchored form (P2.3): on the 899-
  question Metaculus panel, extremizing the deviation from the reference-class base
  rate beat every 0.5-anchored method. The right quantity to amplify is "how far is
  this forecast from its reference class", not "how far from a coin flip".

### 3.4 The α-sweep — data gives the magnitude

`backtesting.sweep_platt_alpha` is the read-only diagnostic that decides
activation. Over the resolved set it recomputes mean Brier at each α in
`linspace(1.0, max_alpha)` and reports `best_alpha` / `best_brier`,
`brier_at_sqrt3` (the value one would blindly activate with), `identity_brier`, and
the honest **leave-one-out** out-of-sample Brier (`loo_brier`) at a data-chosen α —
the non-overfit number to trust when justifying activation. "Theory gives the form
(√3), data gives the magnitude" — and on our data the magnitude is 1.0.

---

## 4. Paired bootstrap significance (P0.2)

The headline comparison is a **per-question paired Brier delta**, not two marginal
means (pairing removes question-difficulty variance, the dominant term):

```
δᵢ         = brier(baselineᵢ) − brier(agentᵢ)        # positive ⇒ agent better
mean_δ     = mean(δᵢ)
d0ᵢ        = δᵢ − mean_δ                              # recenter at zero (the H0 series)
for b in 1..B (B = 10000, seeded):
    idx    = resample-with-replacement of the question indices
    p-value counts  |mean(d0[idx])| ≥ |mean_δ|
    CI collects     mean(δ[idx])   (the UNcentered resample means)
p_value    = (ge_count + 1) / (B + 1)                 # plus-one: p is never exactly 0
CI95       = 2.5 / 97.5 percentiles of the uncentered resample means
```

A **single seeded stream** drives every draw, so identical inputs reproduce the
p-value and CI byte-for-byte. `n<2`, no mean, or an all-equal-delta (variance-free)
spread returns `p=None, CI=None` — correctly un-actionable. The sibling
`_win_rate_vs_best` reports the fraction of questions where the agent's Brier is
`≤` *every* baseline (guarding against a mean-edge that is really a few large
wins). This is a literal port of the AIA test (their B=10,000), not an in-house
invention — the point estimate is unchanged from the old parametric
implementation; only the significance statistics moved from a normal approximation
to the bootstrap.

---

## 5. The agentic supervisor — override + fresh search (P0.3, P1.1)

The judge does two jobs the plain pool cannot: it can **override** the pool, and it
can **add evidence** before it does.

### 5.1 Confidence-gated override (P0.3)

```
resolve_final_probability(pool_p, judge):
    if judge and judge.probability is not None and judge.directional_confidence == "high":
        return judge.probability, "judge_high"
    return pool_p, "pool"
```

This is the entire override rule — a pure predicate, no I/O. A low- or medium-
confidence judge can **never** drag the committed number off a sound pool (bounded
downside), while a high-confidence one captures the documented lift (gated upside).
The terminal Platt (§3) applies to *whichever branch wins*, so the committed number
is recalibrated exactly once. Wired into `run_quorum`, which records `final_source`
(`pool` / `judge_high`) on the panel run.

### 5.2 Fresh-search loop (P1.1)

The judge is an evidence-*adding* reconciler, not just a re-weigher. When it flags
an unresolved crux it names it:

```
should_research(judge, rounds_done, max_rounds):
    return judge.information_gap and bool(judge.clarifying_queries) and rounds_done < max_rounds
```

If so, `run_quorum` hands `judge.clarifying_queries` to a `search_runner`, folds
the returned evidence into the working context, and **re-synthesises once**
(bounded by `max_research_rounds`, default 1). With `search_runner=None` (the
default) nothing changes: no gap check, no extra calls, the committed probability
is byte-identical.

`supervisor_search.build_supervisor_search_runner` is the live backend that wires
it (the live QUORUM job originally never passed a runner, so the loop could never
fire — this closed that gap). It is:

- **bounded** — at most 3 distinct queries, 5 results per query, 12 items total,
  deduped by canonical URL / normalised title;
- **robust** — a failing backend yields `[]` and never throws, so a research round
  that finds nothing simply re-synthesises on the original context;
- **live-legitimate** — `available_at` is stamped at *now* (the question resolves
  in the future, so fresh search now is legitimate evidence, not foreknowledge),
  and it drops P2.4 leak-domain URLs so a live-widget answer can't slip into the
  judge context. (The leakage-sensitive backtest path does not use this runner — it
  pins sources to the cutoff.)

This is the lever the grounding study identified as *the* path to a real edge: the
closed-book model has no intrinsic edge over the market, so the only way to beat it
is fresh information it has not yet priced.

---

## 6. Foreknowledge control — the leak channels (P1.2, P2.4)

Leakage is a two-channel taxonomy, each with its own mitigation.

### 6.1 Content-aware leak-judge (P1.2) — channel 2

The cheap date pre-filter (always on) drops evidence whose `available_at` is after
the cutoff, but it is blind to leakage *inside the text* of admissible evidence.
`leak_judge.build_leak_judge_prompt` + `parse_leak_verdict` add a high-recall
LLM-as-judge that reads the cited evidence + model rationale for the **four tells**
(explicit outcome references / past-tense narration of a future event / facts
stated as actual that were unknown at cutoff / info that only exists post-event),
behind a **"good forecasting is NOT leakage" guardrail** so it does not flag skilled
forward-looking inference. Both functions are pure (a prompt builder + a tolerant
parser) and the parser **fails closed** to the no-leak default — a broken judge call
can never *manufacture* a leak flag.

**Robustness bounds** (`ledger.rescore_backtest_run`, modes `baseline` / `filtered`
/ `worst_case`): the superiority claim stands only if all three Briers agree —
`filtered` drops every flagged case, `worst_case` forces `p=0.5` (Brier 0.25) on any
heavily-flagged question. This converts leakage handling from a pass/fail kill-
switch into a quantified upper bound on metric inflation.

**The UNCALIBRATED honesty (`leak_prevalence.py`).** A high-recall judge buys recall
with low precision, so a raw flag count over-states leakage. The true rate is backed
out from precision/recall:

```
true_rate = (precision · flags) / (recall · N)
```

But `LEAK_JUDGE_CALIBRATION` is explicitly `calibrated: False`, version
`"…-v0-UNCALIBRATED"`, carrying the paper's working `precision=0.198, recall=0.64`
as **placeholders** with `labelled_sample_size: 0`. The module and its constant both
say, in prose, do not cite the resulting true-rate as *measured* until a flagged-
case sample is hand-labelled. This is the one un-de-risked piece of the whole
firewall, and it is labelled as such rather than quietly presented as a measured
~1-2% leak rate.

### 6.2 Root-cause mitigation (P2.4) — protecting live forecasts too

The leak-judge only runs in backtests; these protect the live path at zero
inference cost:

- **Leak-domain denylist** (`leak_domains.py`) — `LEAK_DENYLIST` (macrotrends,
  ycharts, tradingeconomics, tipranks, FIDE, finance-quote and market-activity
  hosts …) + `LIVE_WIDGET_PATTERNS` (a high-precision regex for `/quote/`,
  `/live-scores`, `/rankings/`, `?ticker=` shapes) + a `charts.`-host pattern.
  These pages serve *today's* value regardless of any historical query, so evidence
  cited from them time-travels. `is_leak_domain` is consulted at
  `ledger.add_evidence` to **tag** (not silently delete) matching items and mark
  them inadmissible for backtest scoring; the normal live ledger keeps them. The
  patterns are deliberately narrowed (bare `/live/` and `/charts/` PATH were removed
  because they false-positive on news live-blogs and official stats).
- **Model-cutoff gate** — `models.MODEL_PRETRAINING_CUTOFF`; when a backtest case's
  agent-model cutoff overlaps the event window, calibration is forced off and a
  readiness flag is raised (mirroring the paper rejecting a too-fresh model).
- **Dated-revision pinning** — continuously-edited pages (Wikipedia) are pinned to
  the newest revision at/before the cutoff, killing the "timestamp lies for a page
  updated after publication" failure.

---

## 7. The simplex market+LLM ensemble (P1.3)

The paper's central positive result: a convex blend of the LLM forecast and the
de-vigged market price beats **both** inputs (LLM 0.126 / market 0.111 / ensemble
0.106), because the LLM carries orthogonal signal even when it loses head-to-head.
`market_ensemble.simplex_brier_weights` fits and, crucially, *proves the additive
value out-of-sample*.

For the 2-source `{market, llm}` case the simplex is the interval `w ∈ [0,1]` and
the Brier objective is a convex parabola in `w`, so the minimiser is the analytic
vertex (grid-snapped for reproducibility):

```
dᵢ = marketᵢ − llmᵢ ,   rᵢ = llmᵢ − outcomeᵢ
w* = clamp01( −Σ dᵢ rᵢ / Σ dᵢ² )                     # the Brier-minimizing market weight
```

Three honest instruments come with it:

- **`loo_ensemble_brier`** — refit `w` on `n−1` points, score the held-out point,
  average. This removes the in-sample optimism of scoring at weights chosen to
  minimise that same sample's Brier.
- **`bootstrap_ci_95`** — a seeded (2000-draw) percentile CI on the weights.
- **`beats_both`** — `True` only when the **LOO** ensemble Brier is strictly below
  *every* per-source Brier, never the optimistic in-sample number.

`fitted_market_advisory_weight` is the only thing here that could ever move a live
number, and it is triple-gated: the fitted weight ships **only** when `n ≥ 30`,
`beats_both == True`, AND the LLM weight's 95% CI excludes 0; otherwise the existing
static advisory weight is returned unchanged (missing gate = no change, never a
silent reweight). And the blend is deliberately **not** Platt-extremized — the paper
warns that stacking recalibration on a *different* aggregation method erases its
edge, and `market_ensemble.py` encodes that as a load-bearing invariant. In the
grounding study this gate correctly returned agent weight **0.0** — no orthogonal
signal to ship, because the agent had seen the price.

---

## 8. The convexity baseline (P1.4)

`bayes_toolkit.mean_probability` (an alias of `linear_pool`) is the **convexity-
backed simple mean**: Brier is convex in the forecast, so by Jensen's inequality
`Brier(mean(p)) ≤ mean(Brier(p))` for a fixed outcome. That makes the naive average
the **formal floor** any odds pool or judge synthesis must beat to justify its extra
machinery. It is a *selectable* panel-aggregation method (`'mean'` in
`PANEL_AGGREGATION_METHODS`) recorded alongside the trimmed-geomean, but the desk
**default stays `trimmed_geomean_odds`** — the mean is the baseline to beat, not the
committed number. The ensemble-size story (Brier drops sharply from 1→~5 draws, then
plateaus; decompose sampling variance from question variance) rides the same
machinery.

---

## 9. Search-ablation 2×2 (P2.2)

`search_ablation.py` is the read-only attribution harness. It bins resolved backtest
cases into the four cells `(search_on, judge_on)` by the arm actually recorded, and
`ablation_decomposition` attributes the paired Brier delta to **search vs judge**
specifically — so a gain can be pinned to the lever that produced it rather than to
undifferentiated "agent goodness". Surfaced via an opt-in `forecast ablation`
subcommand and an opt-in evidence-status row; it never touches a live forecast.
This is how the desk would replicate the paper's finding that search is the dominant
lever (0.1230 no-search → 0.1140 search) while guarding against the ~42% of "search
gain" that is really the leaked market price.

---

## Sources

Verified against the current tree on branch `superforecasting-agent-snapshot`:

- `forecasting/bayes_toolkit.py` — `platt_scale`, `platt_scale_anchored`,
  `extremize` (the alias), `PLATT_ALPHA_VARIANCE_MATCH`, `log_odds_pool`,
  `mean_probability`.
- `forecasting/panel.py` — `aggregate_panel_estimates` (`alpha_extremize`,
  the strict-no-op terminal stage), `PANEL_AGGREGATION_METHODS`,
  `DEFAULT_PANEL_AGGREGATION_METHOD`.
- `forecasting/quorum.py` — `resolve_final_probability`, `should_research`,
  `JudgeSynthesis` (`directional_confidence` / `information_gap` /
  `clarifying_queries`), the `run_quorum` search loop.
- `forecasting/supervisor_search.py` — `build_supervisor_search_runner`, the
  bound/robust/live-legitimate caps.
- `forecasting/calibration_bias.py` — `signed_calibration_error`,
  `extremization_alpha_gate`, `diagnose_hedging`, `leaned_side_hit_rate`.
- `forecasting/backtesting.py` — `sweep_platt_alpha` (LOO α sweep),
  `expected_brier_delta_by_bin`.
- `forecasting/market_ensemble.py` — `simplex_brier_weights`,
  `fitted_market_advisory_weight`, `_best_w_market`, `_loo_ensemble_brier`.
- `forecasting/leak_judge.py` — `FOUR_TELLS`, `NOT_LEAKAGE_GUARDRAIL`,
  `parse_leak_verdict` (fails closed); `forecasting/leak_prevalence.py` —
  `estimate_true_leak_rate`, the `LEAK_JUDGE_CALIBRATION` UNCALIBRATED block;
  `forecasting/leak_domains.py` — `LEAK_DENYLIST`, `LIVE_WIDGET_PATTERNS`,
  `is_leak_domain`.
- `forecasting/search_ablation.py` — `ablation_decomposition`,
  `collect_ablation_cells`, `ablation_report`.
- `forecasting/ledger/scoring.py` — `_paired_brier_summary`, `_paired_bootstrap`
  (recenter-at-zero, seeded, plus-one), `PAIRED_BOOTSTRAP_DRAWS`.
- Plan: [docs/plans/aia-forecaster-improvements.md](../plans/aia-forecaster-improvements.md).
- Empirical gates: [ForecastBench Grounding Study](../research/forecastbench-grounding-study.md),
  [Beating-the-Market Strategy](../research/beating-the-market-strategy.md).
