---
name: bayes-forecast-scratchpad
description: "Auditable Bayesian forecasting scratchpad: likelihood-ratio updating, log-odds pooling, evidence weighting, reference-class blending, poll→probability, market de-vig, double-counting checks, sensitivity, and forecast-diff. Use whenever you move or combine a forecast probability."
version: 1.0.0
author: Superforecasting Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [forecasting, bayesian, probability, likelihood-ratio, pooling, calibration, polls, markets, sensitivity, superforecasting]
    category: forecasting
    related_skills: []
---

# Bayesian Forecast Scratchpad

Make every probability move **auditable, reusable, and not ad hoc**. This skill
wraps `forecasting/bayes_toolkit.py` (NumPy + SciPy, with exact stdlib
fallbacks). It is invoked two ways:

- **Agent tool:** `forecast_ledger` with `action="bayes"`, `bayes_action="<routine>"`,
  and a `bayes_payload` object.
- **CLI:** `forecast bayes <routine> --input '<json>'` (add `--json` for the
  machine payload; default prints a human rationale).

Every routine returns **both** machine-readable JSON (for the ledger) and a
human-readable rationale (for forecast notes).

## When to reach for it

Use it the moment you are about to **combine** sources or **change** a
probability. The biggest gains come from log-odds pooling, likelihood-ratio
updating, correlation-aware evidence weighting, poll→probability conversion,
and forecast-diff decomposition. Prefer these over a manual weighted average.

## Routines

### 1. Likelihood-ratio updating (`lr_update`, `decompose_update`)
Update a prior by multiplying odds by likelihood ratios (LR > 1 raises the
probability, < 1 lowers it). `decompose_update` answers "what LR did this move
imply?" — use it to sanity-check a change like "R from 62% to 59%".

```
forecast bayes lr_update --input '{"prior_p":0.62,"lrs":[0.85,0.70,1.25]}'
forecast bayes decompose_update --input '{"prior_p":0.621,"posterior_p":0.593}'
```

### 2. Evidence weighting (`evidence_weight`)
Turn one piece of evidence into a likelihood ratio and an effective pooling
weight. Separates **reliability** (is the source accurate?) from **relevance**
(does it bear on *this* question?), discounts non-independent / stale / biased
evidence, and keeps **direction** separate from **magnitude**.

```
forecast bayes evidence_weight --input '{"name":"NYT poll","reliability":0.78,"relevance":0.8,"independence":0.55,"recency":"high","bias_risk":"medium","direction":"against","strength":"medium"}'
```

### 3. Ensemble combiners (`combine`)
Pool disagreeing probability sources. Default `log_odds_pool` (geometric
pooling of odds) respects confident minorities; `linear_pool` and `log_pool`
are available. `extremize` (>1) sharpens when independent sources agree;
`correlation_matrix:"estimate"` (or an explicit matrix) downweights
double-counted signal and reports the effective number of independent sources.

```
forecast bayes combine --input '{
  "components":[
    {"name":"markets","p":0.555,"weight":0.30},
    {"name":"polling","p":0.49,"weight":0.25},
    {"name":"ratings","p":0.62,"weight":0.20},
    {"name":"base_rate","p":0.75,"weight":0.25}],
  "method":"log_odds_pool","extremize":1.05,"correlation_matrix":"estimate"}'
```

This same pooling is wired natively into the forecast flow:
`forecast update <id> --method log_odds_pool --extremize 1.05 --correlation estimate --component-json '{...}'`.

### 4. Reference-class blending (`blend_base_rates`)
Blend candidate reference classes weighted by applicability; propagates
uncertainty from within-class uncertainty and between-class disagreement.

```
forecast bayes blend_base_rates --input '{"reference_classes":[
  {"name":"Texas statewide D wins since 1994","base_rate":0.15,"applicability":"medium"},
  {"name":"non-incumbent Senate races in red states during D-wave midterms","base_rate":0.4,"applicability":"high"}]}'
```

### 5. Poll → probability (`poll_to_prob`, `polls`)
`poll_to_prob` converts a margin + uncertainty to a win probability (normal
CDF), optionally shrinking toward fundamentals. `polls` runs the full pipeline:
sample-size weighting, recency decay, sponsor/house-effect adjustment,
fundamentals shrinkage, and time-to-election uncertainty.

```
forecast bayes polls --input '{"polls":[
  {"margin":7,"sample_size":643,"sponsor_bias":"D","pollster_quality":"medium","days_old":5},
  {"margin":0,"sample_size":1223,"mode":"nonprobability","days_old":20}],
  "fundamentals_margin":-4,"days_to_election":160}'
```

### 6. Market de-vig (`devig`, `normalize_market`, `combine_markets`)
Remove the vig/overround, normalize mutually exclusive contracts, downweight
illiquid/wide-spread markets, and report cross-market disagreement.

```
forecast bayes combine_markets --input '{"markets":[
  {"source":"Kalshi","bid_yes":0.57,"ask_yes":0.58,"bid_no":0.43,"ask_no":0.44,"volume":1500000},
  {"source":"Polymarket","yes_mid":0.525,"volume":400000}]}'
```

### 7. Double-counting checker (`evidence_cluster`)
Collapse items that reflect one underlying signal (markets + ratings + articles
all downstream of the same poll) into one effective independent weight, so you
don't over-update.

```
forecast bayes evidence_cluster --input '{"name":"Paxton vulnerability","items":["NYT poll","ABC analysis","Polymarket move","270toWin price"],"shared_signal":"high"}'
```

### 8. Sensitivity / robustness (`sensitivity`)
One-way / tornado analysis: sweep each component and report what would move the
forecast most. Use the `"__drop__"` key to test ignoring a source.

```
forecast bayes sensitivity --input '{"components":[{"name":"polling","p":0.49,"weight":0.25},{"name":"markets","p":0.555,"weight":0.3},{"name":"base_rate","p":0.75,"weight":0.25}],"parameter_ranges":{"polling":[0.45,0.55],"base_rate":[0.6,0.9],"__drop__":["markets"]}}'
```

### 9. Forecast-diff explainer (`forecast_diff`)
Decompose a probability change into per-driver contributions (in points) that
sum to the net move. Supply explicit `delta_pts` per driver, or per-driver
`previous_p`/`current_p` (+ optional weight) to attribute via the log-odds pool.

```
forecast bayes forecast_diff --input '{"previous":0.621,"current":0.593,"components":[
  {"name":"NYT polling","delta_pts":-0.020},
  {"name":"generic ballot","delta_pts":-0.015},
  {"name":"markets","delta_pts":0.008},
  {"name":"ratings","delta_pts":0.004}]}'
```

## Recommended workflow

1. Establish a prior (reference-class `blend_base_rates`).
2. Convert each new source to a likelihood ratio (`evidence_weight`); cluster
   correlated sources (`evidence_cluster`) so you weight signal, not copies.
3. Pool sources (`combine`, `method="log_odds_pool"`, `correlation_matrix="estimate"`),
   or apply LRs to the prior (`lr_update`). Specialised inputs: `polls`,
   `combine_markets`.
4. Save the move with `forecast update` (use `--method log_odds_pool` to pool
   natively), then explain it with `forecast_diff` and stress-test it with
   `sensitivity`.

Always record the machine JSON on the snapshot and paste the rationale into the
forecast note so the update is reproducible.
