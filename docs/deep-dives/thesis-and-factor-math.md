# Deep dive — thesis & factor math

This is the honest math of the two weighted-basket aggregators the desk runs when
a forecast is not one question but a *portfolio* of them: a **thesis** ("Democrats
take back the Senate", "AI-infrastructure boom holds") and a **factor** (a
long/short basket of return distributions). Both are pure math — stdlib `math`
plus a few reused primitives from `forecasting.bayes_toolkit`, no DB, no I/O, and
no `datetime.now` (the reference instant is always injected so callers and tests
stay deterministic). Both obey the same two honesty rails, stated once here and
enforced in every branch below:

- **Never fabricate precision.** A member with no calibrated dispersion
  contributes *zero* to the uncertainty band, never an invented standard
  deviation.
- **Never fake variance reduction.** Members co-move, so the band uses the full
  correlated quadratic form. The naive independence formula `Σ wᵢ²σᵢ²` is
  *refused* unless the caller passes the explicit float `rho=0.0`.

The desk process that produces these members — questions → evidence → panels →
commit — is in [forecasting-methodology.md](../forecasting-methodology.md); the
thesis question-type and its CLI/TUI surfaces are summarised in
[architecture.md](../architecture.md). This page is the layer *underneath*: what
`aggregate_thesis`, `simulate_thesis_event`, and `aggregate_factor` actually
compute, and why the shapes are the way they are.

Files: `forecasting/thesis.py`, `forecasting/factor.py`,
`forecasting/market_model.py`, `forecasting/market_compute.py`.

---

## 1. `aggregate_thesis` — a mean index with an honest band

A thesis has weighted **members** — each a `binary` or `distribution` belief with
a `direction` (`support` / `inverted`), a raw `weight`, an `as_of` stamp, and a
belief payload. Distribution members are reduced *upstream* (by
`dashboard._distribution_view`) to `{mean, sd, ci90, pmf, median}` before they
reach the module — `thesis.py` never reduces a raw distribution itself.
`aggregate_thesis` collapses those into a single **health** probability, a 0..100
**score**, and a correlation-honest band.

### 1.1 Per-member signal `sᵢ` and its 0..1-unit dispersion `σᵢ`

Each member is reduced to a raw signal `s_raw ∈ [0,1]` (a directionless
"health-ness") and a dispersion `σ` living in the *same* 0..1 units as the signal:

```
binary          s_raw = clamp(p, 1e-4, 1 − 1e-4)          σ = √(s_raw(1−s_raw))      "bernoulli_proxy"
distribution:
  PMF (exact)   s_raw = mass on the good side of target    σ = √(s_raw(1−s_raw))      "pmf_mass"
  normal-thresh s_raw = Φ((mean − target)/sd)              σ = clamp(φ(z), 0, 0.5)    "normal_threshold"
  bounded map   s_raw = clamp((mean − lo)/(hi − lo), 0,1)  σ = 0  (no band weight)    "point_map_degenerate"
```

The distribution priority is **PMF-mass → normal-threshold → bounded min-max**:
PMF mass past the target is exact and parametric-assumption-free, so it is
preferred; the normal-threshold uses `Φ((mean−target)/sd)` (via
`bayes_toolkit.normal_cdf(mean, target, sd)`) with a dispersion mapped from the
*local slope* `φ(z)` of `s_raw` in `mean` (clamped to `[0, 0.5]` since `φ(0)≈0.399`);
the bounded min-max is the last resort and is deliberately dispersion-less
(`σ=0`) because a bare index has no calibrated spread — it earns a signal but
**no band weight**. The `σ` is honest about being a *proxy*: a PMF's own outcome-
unit standard deviation is not comparable to a 0..1 signal, so the Bernoulli proxy
of the past-target mass is used instead.

**Direction flip is applied last and uniformly:** `sᵢ = s_raw` for a `support`
member, `sᵢ = 1 − s_raw` for an `inverted` one. This keeps the flip out of the
signal-extraction branches so no branch has to know its own polarity.

### 1.2 Staleness → freshness → effective weight

Age down-weights but never silent-drops. With `max_age = max_age_days or 45`:

```
f = 1                                  if age ≤ max_age            (fresh)
f = clamp(1 − (age − max_age)/max_age, 0.15, 1)   if age ≤ 2·max_age   (linear decay to a 0.15 floor)
f = 0                                  if age > 2·max_age          (stale, dropped from the pool)
```

An `as_of` that will not parse is treated as a *missing* snapshot (`f=0`,
flagged), not as fresh. The effective weight is `w_eff = weight_raw · f`, and the
normalised weight is `wᵢ = w_effᵢ / W` with `W = Σ w_eff`. If `W ≤ 0` (everything
stale/missing) the whole aggregate is **withheld** (`health`, `score`, `band` all
`None`) with the note `"withheld: no usable member signal (not fabricated)"` —
the module emits nothing rather than a fabricated number.

### 1.3 Health — a log-odds pool

```
health = inv_logit( Σᵢ wᵢ · logit(clamp(sᵢ, 1e-6, 1 − 1e-6)) )
```

This is the superforecasting workhorse (geometric pooling of odds; see
[reference/tool-actions.md](../reference/tool-actions.md) `bayes`). The
extremization factor is **hard-fixed to 1.0** (`_EXTREMIZE_FACTOR = 1.0`,
constant, not a parameter): members of a thesis *co-move*, so sharpening the pool
away from 0.5 would manufacture false confidence. The general recalibration
operator that *does* extremize elsewhere (`bayes_toolkit.platt_scale`, see
[scoring-and-ensembles.md](scoring-and-ensembles.md)) is deliberately not applied
here.

### 1.4 Score — a weighted arithmetic mean

```
score = 100 · Σᵢ wᵢ · sᵢ          (on the 0..100 scale)
```

The score is the *linear* index (a weighted-mean health-ness) and the health is
the *log-odds* index; both are reported because they answer different questions
(the mean position vs. the pooled odds). Each member's `contribution_pts =
100·wᵢ·sᵢ` sums exactly to the score.

### 1.5 The correlation-honest band

The band is the honesty centrepiece. It is the full correlated quadratic form,
never the independence sum:

```
Var   = Σᵢ Σⱼ wᵢ wⱼ ρ_ij σᵢ σⱼ           (ρ_ii = 1;  ρ_ij = ρ or a pairwise override)
sd    = 100 · √(max(Var, 0))
band  = ( clamp(score − 1.645·sd, 0, 100),  score,  clamp(score + 1.645·sd, 0, 100) )
```

`1.645` is the 90%-central half-width in standard-normal units, so the band is a
`(q05, q50, q95)` triple. Two withholding rules keep it honest:

- **No calibrated dispersion → no band.** If no usable member has `σ>0`, the band
  is `None` (`"no calibrated dispersion; band withheld"`).
- **Binary-only → no band.** If *every* usable member is `binary`, the band is
  also withheld: a Bernoulli proxy `√(p(1−p))` is a signal-space convenience, not
  a calibrated forecast dispersion, so a thesis of pure binaries reports a point
  score with no fabricated interval. (This is the invariant behind the TUI's
  central-in-band and never-fabricate-bands rules noted in memory.)

**`ρ` resolution** (`aggregate_thesis(..., rho=0.4)`):

- a float is clamped to the honest band `[0, 0.95]`;
- `"estimate"` derives `ρ = clamp(0.6 − 0.25·spread_of_s, 0, 0.95)` from the
  spread of usable signals (wider disagreement → lower implied co-movement);
- **independence (`ρ=0`) is honoured only when the caller passes the explicit
  float `0.0`** — it is never a default, so a caller can never *accidentally* buy
  free diversification.

A thesis may also supply a **pairwise correlation matrix** (`correlation_matrix`):
members co-move *unequally* (coding↔nvidia tighter than coding↔power), so real
per-pair correlations override the scalar `ρ` where specified, falling back to
`ρ` elsewhere. Keys are accepted as `{a,b}` / `(a,b)` / `"a:b"` / `"a|b"`.

### 1.6 Effective sample size and leave-one-out marginals

The **Kish-style effective N** uses the same correlation matrix `R`:

```
n_eff = W² / ( Σᵢ Σⱼ w_effᵢ w_effⱼ ρ_ij )
```

With a unit diagonal and off-diagonal `ρ`, the denominator inflates with
correlation, so `n_eff < n_members` — correlated members do not each count as an
independent vote. Every member also gets a **leave-one-out marginal**:
`health(all) − health(all-but-i)` on the renormalised pool, the honest "how much
does this member move the headline" (a member that is the *only* contributor
returns `0` — "all but i" is undefined). Every input member appears in
`components` even at weight 0, for auditability.

---

## 2. `simulate_thesis_event` — the thesis as a joint threshold event

`aggregate_thesis` returns a **mean index**. But a thesis like "Democrats take
back the Senate" is not a mean — it is a **joint threshold event**:
`P(#member successes ≥ K)`. The mean is damped and threshold-insensitive: it moves
~linearly with each member and can barely twitch when a battleground crosses 50%,
even though the *event* pivots exactly there. And correlation, which only ever
entered the mean's *band*, is first-class for the event: co-moving races collapse
toward all-or-nothing.

### 2.1 Why the old mean-walk failed the sniff test

This layer exists to answer a specific operator complaint, quoted verbatim in the
source: *"I'd have thought it would use some kind of monte carlo... it isn't
treated equally to the underlying questions."* A weighted mean of member
health-ness is a **linear walk** — the aggregate is a damped average that:

1. moves proportionally with each member rather than pivoting at the decision
   boundary `K`, so it under-reacts to a battleground crossing 50%; and
2. treats correlation as a second-order *band* effect, never as a driver of the
   headline, when for a seat count correlation is the whole game (correlated
   races collapse the count distribution toward its tails).

The Monte-Carlo event layer is the fix: it runs a **Gaussian-copula** simulation
over the *same* binary member beliefs the mean consumes, so the thesis is scored
as the event it actually is.

### 2.2 The Gaussian-copula Monte Carlo

Only **binary** members participate (distribution members are excluded with an
honest note — a count threshold is defined over binary trials). For each
participant `i`: `pᵢ = clamp(probability, 0, 1)` and `counterᵢ = (direction ==
"inverted")`.

```
R      : n×n correlation matrix, unit diagonal, ρ off-diagonal, per-pair overrides
Σ = R  ,  L Lᵀ = Σ         (lower-triangular Cholesky factor)
X ~ N(0, I_n)              (independent standard-normal draws)
Z = X · Lᵀ                (correlated latent Gaussians)
τᵢ = Φ⁻¹(clamp(pᵢ, 1e-6, 1 − 1e-6))     (per-member latent threshold)
rawᵢ   = (zᵢ < τᵢ)         (the underlying "yes")
successᵢ = rawᵢ XOR counterᵢ            (an inverted member counts NOT its underlying yes)
count  = Σᵢ successᵢ
P(event) = mean( count ≥ K )
```

The copula construction gives each member exactly its marginal `P(underlying yes)
= P(zᵢ < Φ⁻¹(pᵢ)) = pᵢ` while `Σ` couples the latents, so raising `ρ` tightens the
joint without disturbing any marginal.

**Cholesky with a jitter ladder.** Pairwise-correlation overrides can push `Σ`
out of positive-definiteness. The factorisation retries along a jitter ladder
`(0, 1e-9, 1e-7, 1e-5, 1e-3)`, nudging the diagonal until the nearest PD matrix
factors (recording a note when it does), and falls back to independence
(identity) only in the unreachable worst case — never a silent failure.

### 2.3 Common-random-number sensitivities — "which race matters"

The per-member sensitivity is a finite difference re-scored **on the same latent
draws `Z`** (common random numbers, so the bump signal is not swamped by MC
noise). For each member `i`, with `base = count − successᵢ` (drop `i`'s own
contribution):

```
p⁺ = min(1 − 1e-6, pᵢ + 0.02),   p⁻ = max(1e-6, pᵢ − 0.02)
P⁺ = mean( base + success(zᵢ < Φ⁻¹(p⁺)) ≥ K )     (re-scored on the SAME zᵢ)
P⁻ = mean( base + success(zᵢ < Φ⁻¹(p⁻)) ≥ K )
sensitivity = (P⁺ − P⁻) / (p⁺ − p⁻)               (∂P(event)/∂pᵢ)
delta_p_event = P⁺ − P⁻                            (total event swing over the ±2pp bump)
```

`top_sensitivities(k)` ranks members by `|delta_p_event|` — the honest "which race
most moves the event", a readout a mean index can never give.

### 2.4 Count distribution, backends, seeds, and event kinds

- **Count distribution:** `{p10, p50, p90, mean}` of the simulated `count` (the
  shape of the seat count), via linear-interpolation quantiles.
- **Event kinds:** `count_threshold` (`K` explicit), `all` (`K = #participants`),
  `any` (`K = 1`). The echoed `event` always carries the resolved integer `K`.
- **Backends and draw counts:** numpy fast path = **20,000** draws (vectorised);
  pure-python stdlib fallback = **2,000** draws (kept small so it stays snappy
  offline; an explicit `n_draws > 2000` is capped on the fallback with a note).
  Determinism is **per-path**: the same `seed` reproduces the same result on the
  same backend, but numpy and pure-python are not draw-for-draw identical.
- **Seed derivation:** the function never touches `Date.now` or a global RNG. The
  **caller** derives the seed from `(thesis_id, as_of)`, so a re-run at the same
  as-of is byte-reproducible and a genuine new snapshot re-rolls.
- **Withholding:** `event_probability` is `None` when no binary member
  participates — withheld, not fabricated.

### 2.5 Why seat weights are excluded from the event

The mean index weights members by their aggregation `weight` (evidence quality,
importance). The **event does not**: a count threshold `P(#successes ≥ K)` is
defined over binary *trials*, and each seat is one trial. A member's mean-index
weight has no meaning in a seat count — weighting the count would answer a
different, ill-posed question. So the event layer reads only `{probability,
direction}` per binary member and ignores `weight` entirely. This is deliberate,
and it is *why* the event is "treated equally to the underlying questions": every
race is one vote in the count, exactly as it resolves.

### 2.6 The operator's `set-event` CLI

The event is attached to a thesis through the desk CLI
(`forecasting/cli.py`, `forecast thesis set-event`):

```
forecast thesis set-event <thesis> --kind count_threshold --threshold K
forecast thesis set-event <thesis> --kind all      # every member must succeed
forecast thesis set-event <thesis> --kind any       # at least one member
```

`<thesis>` is a row number, id, or search words. The event spec is stamped into
the thesis snapshot alongside the mean index (`to_payload` emits
`event_probability`, the echoed `event`, `count_distribution`, and the top-5
`sensitivities`), so a thesis carries *both* readouts: the damped mean index and
the pivot-aware event probability.

---

## 3. `aggregate_factor` — a long/short return basket

`factor.py` is the thesis math's sibling for **return distributions**. It
aggregates a basket of constituent `mean ± sd` returns (each `long`/`short`) into
a single factor-return distribution: an expected return, a correlation-honest
volatility, normal return quantiles, and a left-tail downside. It reuses the same
staleness shape and the same variance-honesty discipline, over signed returns
instead of 0..1 signals.

```
per constituent i:  μᵢ = mean if long else −mean       (direction-signed mean)
                    σᵢ = sd    (0 if sd missing/negative → flagged "no_dispersion", never invented)
                    fᵢ = freshness (same 0.15-floor decay as §1.2), w_effᵢ = weightᵢ·fᵢ
factor mean:        μ_f  = Σᵢ wᵢ μᵢ
factor variance:    Var_f = Σᵢ Σⱼ wᵢ wⱼ ρ_ij σᵢ σⱼ        (default ρ=0.4; independence refused unless ρ=0.0)
                    σ_f  = √(max(Var_f, 0))
quantiles:          q05/q50/q95 = μ_f ∓ 1.645·σ_f        (normal approximation, noted as such)
```

Because `Var_f` uses the full correlated form, the factor volatility **exceeds**
the naive independent sum and the Kish `n_eff` sits strictly below the constituent
count — co-moving names buy no free diversification, exactly as in the thesis
band.

### 3.1 The downside — and the max-drawdown critique

The factor reports a **left-tail downside**, deliberately *not* a max drawdown:

```
downside = q05                                    (5th-percentile return)
cvar     = μ_f − σ_f · φ(1.645)/0.05              (normal expected shortfall below q05; φ(1.645)/0.05 ≈ 2.063)
prob_loss = Φ(0; μ_f, σ_f)                        (P[return < 0] under the normal approximation)
```

The honesty rail here is the critique noted in the plans: **a path-dependent
maximum drawdown cannot be honestly recovered from a single-horizon return
distribution.** Max drawdown is a property of the *path* an asset takes through
time; a `mean ± sd` snapshot of the horizon return carries no path. Reporting a
"max drawdown" from it would be a fabricated number of exactly the kind the desk
refuses, so the module reports the expected shortfall (a genuine property of the
return distribution) and labels it plainly. As with the thesis, an all-stale
basket withholds every headline field rather than emitting a guess.

---

## 4. The Market Models tab — agentic quant research

The thesis/factor aggregators are pure closed-form math. The **Market Models** tab
(`forecasting/market_model.py`, surfaced in the TUI Markets view) is the opposite
end: an *agentic* quant-research artifact where a bounded agent researches and
computes a model, then persists a typed presentation. It sits next to the
aggregators because it is the other way a "model" enters the desk — built, not
derived.

**Lifecycle.** `build_market_model` runs a bounded agent (the `market-models`
toolset) that researches and computes via the deterministic `market_compute` tool,
emitting a typed **Presentation**; the model, its presentation version, the data
series, and a re-runnable spec are persisted. `open_market_model` re-pulls the
series and recomputes the math on live data (keeping the timestamped write-up);
`renarrate` rewrites only the prose against fresh numbers; `chat` is an ongoing
refine conversation that versions the presentation; `model_to_forecast` spins a
projection into a Desk forecast. The agent run and the auxiliary LLM call are
module-level seams, so the persistence / extraction / degradation logic is
unit-testable without a live model.

**Depth presets.** `DEPTH_PRESETS` (`quick` / `standard` / `deep` / `ultra`) each
size the run: a hard `max_iterations` cap, a `max_tokens` budget (so big
multi-block presentations do not truncate), a reasoning-effort level, and the set
of `required` block types the build must include (enforced via the prompt's
self-check). `quick` is one primary model + a couple of charts; `ultra` escalates
to broad data + web/supply-chain research with diagnostics and a
sensitivity/scenario view.

**Presentation contract + numpy/statsmodels-optional compute.** The typed schema
lives in `forecasting.presentation`; the math lives in
`forecasting.market_compute`, which is **numpy/scipy/statsmodels-optional** in the
same style as `bayes_toolkit`. `backends()` reports which are present; a pure-
stdlib path (`_solve_normal_equations` for OLS, a `_t_quantile` approximation,
`_ols_1d`) runs when numpy is absent, numpy accelerates the linear algebra when
present, and the advanced econometrics families lazily provision `statsmodels`
(`ensure_econometrics`) only when actually invoked — so the tab works offline at
reduced capability and never hard-depends on the scientific stack. Every result is
seeded and reproducible, and a family that cannot be computed degrades to a
labelled `_degraded` block rather than a fabricated fit.

---

## Sources

Verified against the current tree on branch `superforecasting-agent-snapshot`
(reading the code, not inheriting from upstream):

- `forecasting/thesis.py` — `aggregate_thesis`, `simulate_thesis_event`,
  `_binary_signal` / `_pmf_signal` / `_normal_threshold_signal`,
  `_cholesky_with_jitter`, `_simulate_numpy` / `_simulate_python`,
  `_sensitivity_rows`, the `_EXTREMIZE_FACTOR = 1.0` / `_EVENT_DRAWS_*` /
  `_CHOL_JITTER` constants, and the event-layer design comment (lines ~645-665).
- `forecasting/factor.py` — `aggregate_factor`, `_freshness`, the correlated
  variance quadratic form, and the expected-shortfall / no-max-drawdown rails.
- `forecasting/cli.py` — the `forecast thesis set-event` subparser
  (`--kind` / `--threshold`, handler `_cmd_thesis_set_event`).
- `forecasting/market_model.py` — the build/open/renarrate/chat/to-forecast
  lifecycle and `DEPTH_PRESETS`.
- `forecasting/market_compute.py` — `backends()`, `ensure_econometrics()`,
  `_solve_normal_equations`, the numpy/scipy/statsmodels-optional contract.
- `forecasting/bayes_toolkit.py` — `logit` / `inv_logit` / `normal_cdf` /
  `normal_ppf` (the reused primitives) and `log_odds_pool`.
- Tests that pin the invariants: `tests/forecasting/test_thesis_aggregate.py`,
  `test_thesis_event.py`, `test_thesis_correlation_matrix.py`,
  `test_factor_ledger.py`.
