# BLF → hermes: adoption map

**Source:** "Agentic Forecasting using Sequential Bayesian Updating of Linguistic Beliefs" (anon., ICML-preprint 2026; `~/Downloads/15_Agentic_Forecasting_using_S.pdf`).
**Why it matters to us:** BLF is the new ForecastBench SOTA (BI 73.3 overall; ABI 71.0 vs human-superforecaster median 70.9) and it **cites and beats AIA** — the system our 12-slice upgrade (arXiv:2511.07678) ported. It is the natural next harvest.
**Status:** analysis + build proposals; nothing here is built yet.

## The paper in one paragraph

BLF is a binary-question agent built on three ideas: (1) a **linguistic belief
state** — a semi-structured JSON slot `{p, confidence, evidence_for,
evidence_against, open_questions}` that the LLM re-emits after *every* tool
step (vs. accumulate-then-reason-once); (2) **multi-trial aggregation** — K=5
independent runs per question, pooled as a *shrunken logit-space mean*, where
the shrinkage weight α grows with inter-trial variance (James–Stein flavor,
hyperparams by LOO-CV); (3) **hierarchical Platt calibration** — global
slope/intercept plus **per-source intercept offsets** δ_s (L2-regularized),
because sources with skewed base rates (e.g. Polymarket markets that mostly
resolve one way) get over-shrunk by global Platt. Support machinery: a
meta-controller that picks the tool set per question type; the crowd price
injected as a prompt anchor on market questions; per-source empirical priors
on dataset questions; a **KNN model that fully bypasses the LLM** on
temperature time-series questions (the LLM was bad at them); a four-layer
leakage defense (~1.5% residual); paired-bootstrap mixed-effects evaluation
(question difficulty absorbs **62%** of variance); final probabilities clamped
to [0.05, 0.95]. Ablation: hierarchical calibration is the biggest single
component for weak base models; belief state adds on top; shrinkage helps when
trials are noisy; on strong models without a crowd anchor the marginal gain is
small. Their negative result: **within-architecture ensembling doesn't help** —
gains need genuine model diversity.

## What we already have (no action)

| BLF component | Our counterpart |
|---|---|
| Crowd price as prompt anchor | market_anchor in panelist prompts + >10pp named-edge discipline + blind-then-reconcile |
| Platt calibration | √3 Platt terminal calibration (Gate 1, validated on resolved data) |
| Paired bootstrap / difficulty control | P0.2 recenter-at-zero paired bootstrap + Win-Rate-vs-Best |
| Leakage defense layers | P2.4 time-travel pinning + leak-domain denylist + model-cutoff gate; P1.2 content-aware leak judge |
| Multi-model aggregation | connected-provider quorum, trimmed log-odds pools, judge, Delphi rounds |
| Search in the loop | P1.1 supervisor fresh-search loop |
| Their "lone skeptic" trial discovering key evidence at step 9 | our blind_pool orthogonality feed exists — but see A2: we run each panelist ONCE, so we cannot catch our own lone skeptics |

Their negative result **validates our architecture**: our quorum is
cross-provider (codex/gemini/copilot…), which is exactly the diversity regime
where ensembling pays. Corollary: a degraded codex-only quorum is not a
smaller version of the same thing — it is structurally outside the regime
where ensembles work. The degraded-panel label is carrying real weight.

## Adoption map (priority order)

### A1. Belief-state updating in the panelist loop — the biggest gap
Our panelists are closest to the paper's **NoBel/Batch baselines**
(search-accumulate, reason once). BLF's core result is that re-emitting the
belief after each evidence step beats both. Build: the panelist runner
maintains the belief slot `{p, confidence, evidence_for, evidence_against,
open_questions}`; every tool result triggers a belief revision; the final
commit is the last belief. **The trajectory gets recorded** — per-step
`(t, p_t, what_moved_it)` into panel metadata. That feeds three things we
already own: desk notes ("what moved the number"), postmortems (which step
went wrong), and the information-frontier/path-driven methodology (the
trajectory IS the path). Fits: `forecasting/quorum.py` panelist runner +
prompt; records on `panel_runs`.

### A2. Multi-trial aggregation per panelist (K=3–5, logit-space, variance-shrunk)
Their inter-trial σ=0.20 on a single model is enormous — one run per panelist
(our current shape) is a noisy point-sample of the model's own distribution.
Build: K trials per panelist (K=3 high-impact, K=1 default for cost), pooled
per-panelist as a shrunken logit mean α·ℓ̄ + (1−α)·logit(anchor), α from
inter-trial variance, THEN the cross-model pool. The lone-skeptic effect is
the payoff: divergent trials surface evidence majorities miss, and our
disagreement index already knows how to read that spread. Fits: quorum runner
(trial loop), spend governed by the policy matrix.

### A3. Variance-adaptive shrinkage toward the outside view
We already compute a disagreement index (calm/contested) and a market/prior
anchor — but the pool weight is fixed. BLF's rule: **the noisier the trials,
the harder you shrink toward the anchor**. Wire α = f(disagreement) into the
existing log-odds pool so contested panels lean market/base-rate and calm
panels keep their signal. Small change, principled, uses only pieces we have.

### A4. Hierarchical Platt — per-source intercepts on the calibration commit
Our Platt is global. Their finding: per-source δ_s matters precisely when
empirical priors differ by venue — Polymarket-sourced vs Kalshi vs
FRED-derived vs ForecastBench-dataset questions have different base-rate skews
(our cohort scoreboard now exposes exactly these strata). Build: extend the
terminal calibration with per-cohort intercept offsets (L2 + LOO-CV), validate
on resolved data first — same discipline as Gate 1. The cohort scoreboards
(e470e58b9) are the natural grouping key.

### A5. Deterministic specialists as panelists — formalize the KNN lesson
BLF routes temperature time-series questions to a KNN model that bypasses the
LLM entirely, because the LLM measurably underperformed there. We hold the
same philosophy (Market Models, living models) but haven't wired
deterministic models INTO the quorum. Build: register climatology/seasonal-
naive/KNN specialists as panelist types for continuous questions; the
track-record weighting (S7.5) then decides their weight empirically — if the
KNN beats LLM panelists on weather CRPS, it earns the pool share. No new
trust machinery needed; it already exists.

### A6. Difficulty-adjusted scoreboard (ABI-style)
62% of score variance is question difficulty. Our cohort split fixed the
*composition* lie; difficulty adjustment fixes the *hardness* lie. Add a
mixed-effects/ABI-style difficulty-adjusted column to the cohort scoreboard so
a desk that takes hard questions isn't punished against one that farms easy
ones. (ForecastBench publishes the methodology; our ForecastBench harness
already ingests their question set.)

### A7. Commit clamping audit (small)
BLF clamps to [0.05, 0.95] to bound worst-case Brier. We have extremization
guards on the calibration side; verify the *commit* path enforces a floor
(the deviation-bets scorer and Brier=1.0 artifact quarantine both showed what
degenerate 0.0/1.0 rows do to aggregates).

## Sequencing note

A3 and A7 are small and ride existing seams. A1+A2 are one coherent quorum
slice (belief loop + trial loop land in the same runner). A4 and A6 are
calibration/scoreboard slices gated on resolved data. A5 rides the jobs +
track-record machinery. All post-P3 — the gate lattice (P1 shipped a873892f3,
P2/P3 in flight) comes first: gates make behavior mandatory; BLF makes the
behavior better.
