# The Shrinkage Study: Does α<1 Terminal Platt Help in the Evidence-Thin Stratum?

**Date:** 2026-07-05 · **System:** hermes-agent superforecasting fork (`superforecasting-agent-snapshot`)
· **Ledger:** `~/.superforecasting-agent/forecasting/forecasting.db` (read-only) · **Status:** measurement-first (GATE-1 pattern)

> **Pre-registration discipline.** Sections 1–4 (motivation, strata, metrics, and the *verbatim*
> decision rule) were written and frozen **before** the study was run on the real ledger. Section 5
> (results) and Section 6 (decision taken) were filled in **after** the run, without editing the
> frozen rule. This mirrors the ForecastBench grounding study
> (`docs/research/forecastbench-grounding-study.md`), where √3 extremization was measured, wired,
> and shipped **OFF**.

## 1. Motivation and hypothesis

The desk's terminal recalibration operator is a single log-odds affine slope,
`platt_scale(p, alpha) = inv_logit(alpha·logit(p))` (`forecasting/bayes_toolkit.py`). `alpha > 1`
**sharpens** (extremizes away from 0.5); `alpha < 1` **flattens** (shrinks toward 0.5); `alpha = 1`
is the exact identity. The per-question activation surface is `alpha_extremize`
(`forecasting/panel.py:185,255-259`; `forecasting/quorum.py:1224,1558-1562`, AIA P0.1), defaulting
to 1.0.

Every prior measurement of that slope on this ledger swept **only the extremization half**:
`sweep_platt_alpha` (`forecasting/backtesting.py`) ranges `α ∈ [1.0, 2.5]`. GATE-1 found the
LOO-best slope is `α = 1.0` (identity) in that range — extremizing *hurts*. **The shrinkage half,
`α < 1`, has never been measured on this ledger.**

The reason to look now is a specific, localized signal. The ForecastBench **market-hidden arm**
(grounding study §3.4) found that when the market price is withheld, the agent's *own* forecasts
become **over-confident** — Brier collapses to **0.279** (worse than a naive base rate) with a
signed calibration error of **+0.20**. Over-confidence (predictions too far from 0.5) is exactly
the miscalibration that `α < 1` shrinkage corrects. So the hypothesis is **not** that shrinkage
helps globally (GATE-1 already refutes that); it is that **shrinkage helps in the evidence-thin
stratum specifically** — the regime where the agent is forecasting from thin information and
over-commits.

## 2. Strata (frozen)

All strata are **binary-outcome resolved forecasts only** (Brier + Platt operate on a scalar
`P(yes)`), reduced to `(p_yes, outcome)` pairs using the **raw pre-adjustment probability** when a
lesson previously moved the number (the contamination control from
`forecasting/ledger/scoring.py:_bias_observations`). Strata are computed **independently per
`forecast_origin`** and **never pooled naively across origins** — `list_scores` is called per-origin
exactly as `build_forecasting_evidence_status` does (`live`, `backtest`, `imported_baseline` are
reported separately, never summed into one calibration set).

| Stratum | Filter | Role |
|---|---|---|
| **live** | `forecast_origin="live", calibration_eligible=True` | The **decision-relevant** stratum (matches the `_bias_observations` / `include_alpha_sweep` precedent). |
| **backtest** | `forecast_origin="backtest", calibration_eligible=None` | The **powered** agent-replay stratum. This is the ForecastBench-style market-hidden / evidence-thin regime; primary test of the hypothesis. Hypothesis-generating, **not** a live green-light. |
| **evidence-thin** | agent-generated obs (`backtest` + `live`) with `len(evidence_refs) ≤ 1` | The mechanical thin stratum (see below). |
| **evidence-rich** | agent-generated obs with `len(evidence_refs) ≥ 2` | Contrast stratum: shrinkage help should **not** concentrate here if the hypothesis is right. |
| **imported_baseline** | `forecast_origin="imported_baseline"` | **Negative control**: external market/analyst baselines (well-calibrated markets). Shrinkage is expected to *hurt* or no-op here. |
| **backtest / domain=D** | backtest obs within domain `D`, `n ≥ 50` | Optional domain resolution; skip any domain with `n < 50` and say so. |
| **global (agent, pooled)** | `backtest` + `live` pooled | **Diagnostic only, NOT an activation basis** (pooling origins violates the non-mixing discipline). Reported for completeness. |

**Evidence-thin definition (mechanical, justified from the fields that exist).** The snapshot fields
available on scored rows are `evidence_refs` (a JSON list, populated on **all** agent-generated
scored snapshots), `evidence_cutoff`, and `reference_class_refs` (empty on scored rows here). There
is no stored `stale_evidence_days` column. We therefore define **evidence-thin ≡ `len(evidence_refs)
≤ 1`**. Justification: (a) `evidence_refs` is the only evidence-count field populated across the
scored agent set; (b) the **median** evidence-ref count across agent-generated scored binary
snapshots is **1** (the backtest replay set carries exactly one ref per snapshot), so "`≤ 1`" is
literally "at or below the median evidence count"; (c) it cleanly separates thin replay/thin-live
forecasts from evidence-rich live forecasts (2+ refs). This is the decision-relevant thin stratum
the hypothesis names.

## 3. Metrics (frozen)

Per stratum:

1. **LOO Brier per α** over the widened grid `α ∈ [0.5, 2.5]` (step 0.05; `α = 1.0` lies exactly on
   the grid). The in-sample mean Brier curve `mean_brier(α)`, its minimizer `best_alpha`, the
   identity value `identity_brier = mean_brier(1.0)`, and the best value restricted to `α < 1`
   (`best_alpha_below_1`, `best_brier_below_1`).
2. **Out-of-sample leave-one-out**: for each held-out point pick the grid α minimizing Brier on the
   *rest*, score the held-out point with it, and average → `loo_brier` at a data-chosen α, plus the
   modal per-fold pick `loo_modal_alpha`. (Same estimator as `sweep_platt_alpha`; the study computes
   it with an `O(n·grid)` incremental identity so it scales to n≈1,700.)
3. **Significance vs α=1.0**: the **existing AIA-P0.2 seeded paired recenter-at-zero bootstrap**
   (`forecasting/ledger/scoring.py:_paired_bootstrap`, `PAIRED_BOOTSTRAP_SEED=0xA1A02`,
   `PAIRED_BOOTSTRAP_DRAWS=10000`) is reused verbatim on the per-question Brier deltas
   `δ_i = brier_i(α=1) − brier_i(best_alpha_below_1)` (δ > 0 ⇒ shrinkage better). It returns a
   two-sided p-value and a 95% percentile CI. No new bootstrap machinery is written.

## 4. Pre-registered decision rule (VERBATIM, frozen before results)

> Conditional terminal-Platt **shrinkage** (an `α < 1` slope fed into the existing `alpha_extremize`
> path in `forecasting/panel.py` / `forecasting/quorum.py`) will be **RECOMMENDED FOR ACTIVATION**
> for a stratum **if and only if ALL** of the following hold on that stratum's resolved binary set:
>
> - **(D1)** there exists a grid `α < 1` whose in-sample mean Brier is **strictly below** the
>   identity (`α = 1`) mean Brier;
> - **(D2)** the seeded AIA-P0.2 paired recenter-at-zero bootstrap of the per-question Brier deltas
>   (identity minus best-`α<1`) yields `mean_delta > 0` with **two-sided p < 0.05** **and** a 95% CI
>   whose lower bound **excludes 0**;
> - **(D3)** the out-of-sample leave-one-out procedure (each fold re-picks α on the held-out
>   remainder) selects a **modal `α < 1`** **and** achieves `loo_brier ≤ identity_brier`
>   (generalization guard against in-sample overfit);
> - **(D4)** the stratum has **n ≥ 50** resolved binary observations.
>
> **Even when a stratum clears (D1–D4), activation SHIPS OFF.** The code path is wired and gated
> behind an explicit per-stratum trigger, and this document *recommends* activation — mirroring how
> √3 Platt (P2.3) shipped OFF pending live confirmation. **Activation on the LIVE decision stratum
> additionally requires the LIVE stratum itself to clear (D1–D4)**; a backtest-only pass is
> hypothesis-generating, not a live green-light.
>
> **If NO stratum clears (D1–D4), the shrinkage hypothesis has failed on this ledger, NOTHING
> changes live, and this document records the null faithfully.**

## 5. Results

Read-only run on `~/.superforecasting-agent/forecasting/forecasting.db` (1,682 resolved questions;
`python -m forecasting.shrinkage_study`), grid `α ∈ [0.5, 2.5]` step 0.05 (41 nodes), thin ≤ 1 ref,
min-n 50. `identity` = mean Brier at α=1.0; `α*` = the Brier-minimizing slope **below 1.0**;
`B(α*)` = its mean Brier; `Δ` = mean per-question Brier reduction of shrinkage (paired, > 0 ⇒
shrinkage better); `p` / CI = the seeded AIA-P0.2 paired recenter-at-zero bootstrap; `loo` = the
out-of-sample leave-one-out Brier at a data-chosen α.

| Stratum | n | identity | α* | B(α*) | Δ (paired) | p | 95% CI | loo | modal α | clears (D1–D4) |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|:--:|
| **live** | 0 | — | — | — | — | — | — | — | — | **no** (categorical; 0 binary) |
| **backtest** | 1655 | 0.1953 | 0.50 | 0.1879 | +0.00739 | 1.0e-4 | [0.0038, 0.0111] | 0.1879 | 0.50 | **YES** |
| **evidence_thin** (≡ backtest) | 1653 | 0.1952 | 0.50 | 0.1878 | +0.00738 | 2.0e-4 | [0.0037, 0.0111] | 0.1878 | 0.50 | **YES** |
| evidence_rich | 2 | 0.2725 | 0.50 | 0.2611 | +0.0114 | — | — | — | — | no (n<50) |
| **imported_baseline** (control) | 3314 | 0.2159 | 0.70 | 0.2149 | +0.00103 | 0.018 | [0.00017, 0.0019] | 0.2154 | 0.70 | **YES** (weak) |
| backtest · prediction_markets | 600 | 0.1099 | 0.65 | 0.1094 | +0.00050 | 0.66 | [−0.0017, 0.0028] | 0.1109 | 0.65 | no |
| backtest · forecastbench | 485 | 0.2235 | 0.50 | 0.2105 | +0.01298 | 0.0015 | [0.0047, 0.0213] | 0.2105 | 0.50 | **YES** |
| backtest · macro | 89 | 0.2559 | 0.50 | 0.2471 | +0.00884 | 0.26 | [−0.0064, 0.0245] | 0.2471 | 0.50 | no |
| backtest · biotech | 87 | 0.2465 | 0.55 | 0.2419 | +0.00466 | 0.47 | [−0.0074, 0.0172] | 0.2465 | 0.55 | no |
| backtest · credit | 87 | 0.2461 | 0.55 | 0.2421 | +0.00391 | 0.59 | [−0.0097, 0.0186] | 0.2492 | 0.50 | no |
| backtest · policy | 87 | 0.2764 | 0.50 | 0.2596 | +0.01680 | 0.037 | [0.0012, 0.0329] | 0.2596 | 0.50 | **YES** |
| backtest · technology | 85 | 0.2322 | 0.90 | 0.2320 | +0.00022 | 0.87 | [−0.0022, 0.0029] | 0.2373 | 0.85 | no |
| global (agent, pooled — diagnostic) | 1655 | 0.1953 | 0.50 | 0.1879 | +0.00739 | 1.0e-4 | [0.0038, 0.0111] | 0.1879 | 0.50 | (diag) |

Domains skipped for n < 50: climate (45), geopolitics (45), public_health (45).

**What the numbers say.**

1. **The shrinkage hypothesis is confirmed on the powered stratum.** On the full backtest replay set
   (n=1,655), the strongest shrinkage slope on the grid (α = 0.50) lowers mean Brier from 0.1953 to
   0.1879 — a paired reduction of +0.0074 that is highly significant (p ≈ 1e-4, CI excludes 0) and
   **generalizes out-of-sample** (LOO Brier 0.1879 < identity; the modal held-out pick is also 0.50).
   This clears D1–D4. The evidence-thin stratum is numerically identical because it *is* the backtest
   set (every backtest snapshot carries exactly one evidence ref; the agent-generated median is 1).
2. **The effect concentrates where the agent is over-confident, and vanishes where it is calibrated.**
   The market-hidden / evidence-thin agent domains carry it: `forecastbench` (Δ +0.013, p 0.0015) and
   `policy` (Δ +0.017, p 0.037) clear; `macro` / `biotech` / `credit` point the same way but are
   underpowered at n≈85–89. The well-calibrated `prediction_markets` sub-domain (identity Brier 0.110)
   does **not** clear — its α* buys nothing (Δ +0.0005, p 0.66) and its LOO is *worse* than identity
   (0.1109 > 0.1099). This is exactly the localization the hypothesis predicted, and the mirror image
   of GATE-1's global α = 1.0 finding: shrinkage is not a global win, it is an over-confidence
   correction.
3. **Honest caveat — the negative control clears weakly.** `imported_baseline` (external
   market/analyst baselines, a stratum the desk does not author) also trips the gate, but ~7× more
   weakly (Δ +0.0010 vs +0.0074), at a much milder α* = 0.70, and with a razor-thin LOO margin
   (0.21544 vs identity 0.21590). So the widened grid detects a small residual over-dispersion even in
   imported baselines — the effect is not *perfectly* specific to the agent's thin forecasts. It is,
   however, far larger and far more robust exactly where the intrinsic-over-confidence finding placed
   it, and absent in the one genuine market sub-stratum. This weakens neither the null-elsewhere story
   (`prediction_markets`) nor the decision (imported baselines are not the live decision stratum).
4. **The decision-relevant LIVE stratum cannot be tested.** All 17 scored live forecasts are
   `categorical`, so the binary-Brier shrinkage sweep has **zero** live observations. The hypothesis
   is confirmed only on hypothesis-generating (calibration-ineligible) backtest data.

<!-- RESULTS -->

## 6. Decision taken

Applying the frozen rule of §4 to the results of §5:

- **Strata that clear D1–D4:** `backtest`, `evidence_thin`, `imported_baseline`,
  `backtest·forecastbench`, `backtest·policy`.
- **Live stratum clears:** **No** — it has 0 binary observations and cannot be evaluated.

The §4 rule states: *"Activation on the LIVE decision stratum additionally requires the LIVE stratum
itself to clear (D1–D4); a backtest-only pass is hypothesis-generating, not a live green-light."*
Every clearing stratum here is `calibration_eligible = 0` backtest/imported data — precisely the data
deliberately held **out** of the desk's live calibration derivation. The live stratum is untestable.

**Decision taken — ship OFF, wire ready, recommend, do NOT flip live.**

1. **Nothing changes live.** The per-question `alpha_extremize` default stays 1.0 (identity). No
   default, forecast, or calibration derivation is touched. This mirrors √3 Platt (P2.3), which was
   measured, wired, and shipped OFF.
2. **The wiring is already in place and OFF.** The activation mechanism is the **existing** terminal
   Platt path — `alpha_extremize` in `forecasting/panel.py` (`:185, :255-259`) and
   `forecasting/quorum.py` (`:1224, :1558-1562`). It already accepts any positive slope, so an α < 1
   shrinkage slope flows through it unchanged (`platt_scale` handles α < 1 as flattening-toward-0.5;
   covered by `test_platt_calibration.py`). No new live code is required to activate — only a
   per-stratum trigger that sets `alpha_extremize ≈ 0.5` for the evidence-thin stratum, left
   unset (identity) today.
3. **Recommendation (conditional, pending live evidence).** The measured, generalizing optimum for
   the evidence-thin agent regime is **α ≈ 0.50** (0.50 on the full backtest set and both clearing
   sub-domains). The desk should: (a) accrue live, resolved, **binary** forecasts in the thin regime
   until the live stratum reaches n ≥ 50; (b) re-run this study; (c) if the live stratum clears
   D1–D4, set `alpha_extremize ≈ 0.5` for the evidence-thin (`len(evidence_refs) ≤ 1`) trigger only,
   never globally — GATE-1 and the `prediction_markets` null both show shrinkage must **not** be
   applied where the desk is already calibrated.

**Bottom line.** The α < 1 half of the Platt slope — never before measured on this ledger — produces
a real, significant, out-of-sample Brier reduction (0.1953 → 0.1879, α = 0.50) in exactly the
evidence-thin, over-confident regime the ForecastBench market-hidden arm flagged, and is correctly
inert where the desk is calibrated. But the confirmation lives entirely in calibration-ineligible
backtest data; the live decision stratum has no binary observations to test. Per the pre-registration,
that is a **hypothesis-generating pass, not a live green-light**: the trigger is wired and shipped
**OFF**, and this document recommends activation only after the live binary stratum independently
clears the same bar.

<!-- DECISION -->
