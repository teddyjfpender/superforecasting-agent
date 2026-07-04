# Deep dive: panels, the quorum, and Delphi

The deliberation layer — how the desk turns one model's number into a defended,
multi-view, calibrated forecast. This goes deeper than the "panels → quorum/
Delphi" step in [forecasting-methodology.md](../forecasting-methodology.md); the
commit-gate side (`require_panel`, `quorum_*`, `terminal_calibration_applied`)
lives in [forecasting-pipeline.md](forecasting-pipeline.md).

Two sibling mechanisms sit here, both persisted through
`ForecastLedger.record_panel_run` (the third gated forecast-producing write) with
a `triggered_by` tag so role-disagreement and model-disagreement stay separately
attributable:

- **The perspective panel** (`forecasting/panel.py`) — *one* model run under five
  constrained role framings.
- **The quorum** (`forecasting/quorum.py`) — the *same* brief across a panel of
  independent **models**, plus a judge synthesis and an optional Delphi revision
  round.

---

## 1. The perspective panel

Five role framings (`PANEL_PERSPECTIVES`), each a constrained system prompt the
agent runs separately: `outside` (base rates / reference classes only), `inside`
(mechanistic causal story, no base-rate anchoring), `market` (de-vigged prices,
polls, expert consensus as likelihood ratios), `red_team` (argue the panel's
median is wrong), `sanity` (gut-feel unconditional cross-check). Each returns a
JSON `{probability, confidence_low/high, rationale, reasons_up/down,
change_my_mind, crux}`. The agent runs them silently and reveals only the spread
after all submissions — discussion is for error correction, not consensus
manufacture.

### Aggregation

`aggregate_panel_estimates` pools the estimates. Methods (`PANEL_AGGREGATION_METHODS`):

- **`trimmed_geomean_odds`** (the pinned default) — drop the `trim` highest and
  lowest probabilities (default `trim=1`, the Samotsvety "drop the extremes" rule),
  then a weighted geometric mean of odds via `bayes_toolkit.log_odds_pool`.
- **`log_odds_pool`** — full geometric mean of odds, no trim.
- **`median`** — weighted median (robust, ignores confidence).
- **`mean`** — weighted arithmetic mean, the convexity-backed **baseline**
  (`Brier(mean) ≤ mean(Brier)` by Jensen, the floor any pool/judge must beat).
  Selectable only; **never the silent default** (the code and tests pin this).

The **spread** is a first-class artifact ("the spread is the most valuable part"):
min/max/median/p25/p75/iqr/range/count. `disagreement_signal` folds in a learnable
scalar measured in **log-odds space** (so an order-of-magnitude split low in the
range counts as much as one mid-range): `sd_logit`, a `disagreement_index =
tanh(sd_logit / 2.0)` squashed to [0,1], and a `disagreement_band` (calm /
moderate / high / severe). The index is rounded *before* banding so the stored
index and band never disagree.

### Terminal Platt calibration (AIA P0.1)

After pooling, the scalar passes through the desk's single recalibration kernel
`bayes_toolkit.platt_scale` with a per-question `alpha_extremize` slope. **Default
1.0 is a strict no-op** — `pre_extremize_probability` stays `None` and the
aggregate is byte-identical to the historical bare pool (the hard invariant). When
alpha ≠ 1.0 the pre-value and `applied_alpha` are folded into the persisted spread
(`applied_alpha`, `terminal_calibration_applied`, `pre_extremize_probability`) so
the stage is observable downstream — this is exactly what the
`terminal_calibration_applied` hook reads. The *measured* per-scope confidence
rescale is applied **separately** downstream in
`learning.apply_active_lesson_adjustments` (the fixed de-hedge and the learned
correction compose along the pipeline, never multiplied at this one call site, or
the learned slope double-applies).

### The panel hard-gate and `record_panel_run`

`record_panel_run` (`forecasting/ledger/panels.py`) calls `_enforce_write_gate`
first (it is a gated forecast-producing write), resolves the per-question alpha,
and always aggregates **with** the real slope so the persisted calibration markers
are accurate. When the caller supplies an already-resolved `final_probability` (the
quorum path — `run_quorum` already applied alpha + the judge override), that exact
number is persisted and Platt is **not** re-applied (the P0.1 divergence fix:
`record_panel_run` used to silently re-pool with alpha while the `QuorumResult`
showed the bare pool). The `judge` synthesis is persisted so the `quorum_judged`
gate can see it. The commit-side gate is described in
[forecasting-pipeline.md](forecasting-pipeline.md#the-inline-gates-in-evaluation-order):
`require_panel` blocks a high-impact or re-committed live forecast with no linked
panel and no skip reason; `quorum_required` is stricter (a recorded skip reason is
not enough at that tier — an actual run must be linked).

---

## 2. The quorum

Where the panel varies *role*, the quorum varies *model*: the same forecasting
brief run across independent frontier models via the gateway, then a judge model
synthesises. Two findings shape it: model diversity lifts accuracy over any single
model, and the **synthesis step itself** carries a meaningful chunk of the lift —
a model paired with *itself* still gains, because the judge pass forces
consensus/contradiction/blind-spot reasoning. So a quorum is worth running even
with one provider key (the `self` preset, N samples).

Panelists are dispatched **in parallel** (Fusion design) up to `max_concurrency`
(default: whole panel in one wave, capped at 8 threads), so wall-clock is the
slowest single model, not the sum. A panelist that errors (bad JSON, timeout) is
recorded with its `error` set and excluded from pooling; the quorum completes as
long as one succeeds.

### Presets (`QUORUM_PRESETS`)

- **`frontier`** — two premium models + premium judge (highest quality/cost).
- **`budget`** — three cheap models (beats frontier-solo at ~half the cost).
- **`self`** — self-fusion: the active model sampled `samples` times (default 3);
  the lift comes from the judge synthesis, so it needs only one provider key.
- **`wide`** (AIA P1.4) — ~10 mixed-model draws past the variance-reduction knee.
  **Opt-in only, never a default**; the ensemble-size curve shows Brier variance
  falls sharply to ~k=5 then plateaus, so ~10 sits comfortably past it.

### Delphi revision (anonymous reveal → private second round)

Delphi (`delphi_rounds`, v1 supports 0 or 1) is a **process** change, not a
scoring change. At 0 (default) nothing changes and the result is byte-identical to
a non-Delphi run. At 1: the sealed round-1 panel is pooled and judged; an
**anonymous** reveal of the round-1 spread + the judge's contradictions/blind-spots
(+ any round-1 supervisor evidence) is built (`build_delphi_summary`); each panel
**seat** (`participant_id`, stable across rounds — distinct from `model` because
`self` repeats one model) privately revises against that reveal; the final
aggregate/override runs on the revision round only. The sealed round is preserved
in `delphi_audit['rounds'][0]`.

The reveal must **never** leak model identities ("Claude said", "GPT said") or the
judge's preferred number as an authority — only the distribution, the disagreement
band, and the anonymous strongest arguments. The revision prompt explicitly forbids
deferring to the median: a panelist moves only when an argument or fresh evidence
changed its view, and records a `revision_reason` when it holds. The supervisor
search runs at most once, on round 1 only, so cost stays bounded and predictable.

### The judge synthesis

`JudgeSynthesis` carries `probability`, `rationale`, `consensus`, `contradictions`,
`blind_spots` (which become evidence gaps), `reasons_up/down`, `change_my_mind`,
and two control signals:

- **`directional_confidence`** (`high`/`medium`/`low`, defaults `medium`) — the
  judge's self-report of confidence in its *revised* number.
- **`information_gap`** + **`clarifying_queries`** (AIA P1.1) — the agentic-
  supervisor signal: the judge flags an unresolved crux it could not settle and
  requests fresh searches. Both default to non-triggering values.

Parsing is tolerant by design (`_normalize_confidence` collapses garbage to
`medium`, `_coerce_bool` collapses garbage to `False`) so a malformed judge
response can never spuriously trip the override gate or start a research round.

### The confidence-gated judge override

`resolve_final_probability` is the entire override rule and is a **pure** function:

```
returns (judge.probability, 'judge_high')  IFF  judge exists
                                                 AND reported a usable probability
                                                 AND directional_confidence == 'high'
otherwise                                       (pool_probability, 'pool')
```

A low/medium-confidence judge can **never** drag the committed number off a sound
pool — bounded downside, gated upside. Composition with terminal Platt: the caller
feeds the already-calibrated pool on the `pool` branch and Platt-scales the raw
judge number on the `judge_high` branch, so the winning number is calibrated
**exactly once**; this function neither knows nor applies alpha. `should_research`
is the parallel pure gate for the supervisor loop: fire only if the judge flagged a
gap, supplied a query, and the loop is under budget.

`QuorumResult.committed_probability` is the single source of truth the pipeline
commits; `final_source` records which branch won. `degraded` honestly labels a run
where fewer than 2 panelists survived (a lone survivor dressed as a panel — the
aggregation math is unchanged, only the label).

---

## 3. Autorun: the decision layer and auditable skips

`maybe_autorun_quorum` (`forecasting/quorum_autorun.py`) is **the shared seam** for
every commit surface — the CLI `forecast update` verb and the agent tool's
`update_forecast` (which is what `full_forecast`, the chained pipeline, and `cycle
run --agent` commit through) — so the autonomous paths get the same multi-model
fusion a hand-typed update does. It is strictly bounded + **fail-open**: the commit
already happened, so any failure (config, resolution, job spawn) degrades to a
one-line note and never corrupts it.

It only fires for a **live** forecast with **no panel already attached**, when
`quorum.default_enabled` is on, and when `quorum_auto_indicated` says so — which
rides the existing panel trigger (`should_run_panel`) unless the operator widens
`default_scope` to `always` (`high_impact` default / `first_only` / `always`), so
a quorum never fires where a panel would not, keeping spend bounded. Every decline
returns an **auditable skip record** `{"skipped": True, "reason": …}`:

```
has_panel                        → "panel attached — quorum substitutes only when no panel ran"
origin != live                   → "origin '…' is not live"
not quorum.default_enabled       → "quorum.default_enabled is off"
not quorum_auto_indicated        → "not auto-indicated for this commit (impact/type/prior gate)"
```

### Impact-aware defaults + two honesty guards

`resolve_quorum_defaults` maps a question's impact + type onto a preset/delphi/trim
triple, the single place that decision is made (shared by manual `forecast quorum`
and the autorun path, so the printed reason matches):

- `high` impact **or** a contested type (`vote_share` / `multiple_choice` /
  `thesis`) → `frontier`, one Delphi round, trim 1 (the widest independent read).
- `medium` → `budget`, no revision, trim 1.
- routine / low / unset → `self` fusion, no revision, no trim (cheap).

Then two guards keep it honest:

1. **The single-key reality guard** — when the resolved multi-provider preset spans
   a provider that is not reachable (only one provider key, no OpenRouter),
   `models_reachable` falls it back to `self` fusion of the active model. It is
   **conservative / fail-open**: `available_provider_slugs()` returning `None` or
   an empty set means "assume reachable" (an unknown picture must never spuriously
   downgrade a panel); it only downgrades when it *positively* knows the host has a
   lone non-OpenRouter provider that cannot serve every model.
2. **The `max_calls` cost cap** — `cap_preset_by_calls` bounds the pre-run call
   estimate (`estimate_quorum_calls` = per-round panelists + judge, ×(delphi+1)).
   It downgrades in order: drop the Delphi round first (it doubles cost), then step
   **down** the preset ladder / reduce `self` samples to the largest affordable
   panel **at or below** the requested tier — it can never route a cheap `self`
   request onto a premium preset (the tiers `self < budget < frontier < wide` rank
   by call count *and* per-call cost). A pathologically small cap falls open to
   `self` sampled once, no Delphi, rather than blocking the run.

---

## 4. Track-record weighting (S7 / S7.5)

Not every model or perspective earns an equal vote. All weighting is **advisory,
never silently applied** — callers opt in (e.g. `forecast panel record
--track-record-weights`, or `run_quorum(model_weights=…)`). Three distinct
mechanisms, deliberately kept separate:

- **`component_track_record` / `recommended_component_weights`**
  (`forecasting/ledger/panels.py`) — each **ensemble component** and **panel
  perspective**'s Brier edge over the committed aggregate across resolved binaries.
  One observation per (question, component); scored against the snapshot's committed
  probability (ensemble) or the run's aggregate (perspective).
- **`model_track_record` / `recommended_model_weights`** — each **panelist model**'s
  Brier edge over the cross-model panel average. One observation per (question,
  model); a model that repeats within one run (the `self` preset) is averaged to a
  single per-question observation so it cannot double-count. The reference is the
  cross-model mean Brier on that question (difficulty-normalised). Consumed by
  `run_quorum(model_weights=…)`: a surviving panelist's weight is set from the map,
  default 1.0 for any unmeasured model, so a cold-start panel is equal-weighted by
  construction and no model dominates early; the map actually used is echoed on
  `QuorumResult.model_weights_used`. Deliberately **no `forecast_origin` filter** —
  quorum panel runs are not origin-tagged per estimate, so an origin argument could
  not honestly restrict pairing (strata-aware weighting is a schema change, left
  for when the need is real).
- **`model_skill`** (in `core.py`, **not** panel domain) — reads `model_runs` (the
  living-models path), a *different* signal from panel weighting. This is the
  distinction to keep straight: panel/quorum weighting scores how a perspective or
  a panelist model performed *inside deliberations*; `model_skill` scores a model's
  recorded probabilistic model runs.

All three route through `forecasting/track_record.py`'s shrinkage (`edge_to_weight`,
shrunk toward 1.0), a minimum-sample gate, and magnitude clipping, so a thin or
noisy edge produces a near-1.0 (near-equal) weight.

---

## 5. Extremization safety guards

Extremization (`alpha > 1`) sharpens a forecast away from 0.5; it only *lowers*
Brier on a scope the desk is reliably correct-sided on, and *raises* it otherwise.
Two pure guards in `forecasting/calibration_bias.py` keep the terminal Platt alpha
honest (neither turns extremization on — the per-question default stays 1.0):

- **`extremization_alpha_gate`** — permits `alpha > 1` **only** when the scope is
  under-confident on its leaned side: the empirical leaned-side hit rate must
  *exceed* the mean committed forecast there **+ margin**. Gating on `hit_rate >
  0.5` is insufficient — a scope leaning 0.7 that is right 0.59 of the time is
  correct-sided yet over-confident, and extremizing raises its Brier. Below the ESS
  floor, or not under-confident, alpha is forced to 1.0. `alpha ≤ 1` always passes
  through (this gate only ever *removes* extremization).
- **`diagnose_hedging`** — histograms the **raw** pre-adjustment P(yes) and returns
  `center_ward_hedge = True` only when BOTH the central-mass fraction is high AND
  the signed calibration error is negative (genuinely under-confident). A sharp
  scope or an over-confident one is never told to extremize.

---

## 6. The simplex-constrained market + LLM ensemble

`forecasting/market_ensemble.py` (AIA P1.3) fits a convex blend of the LLM forecast
and the de-vigged market price, and — crucially — *proves* the additive value out
of sample. The paper finding: the LLM carries orthogonal signal even when it loses
head-to-head, so a blend beats **both** inputs on Brier. It is **pure math /
analysis + an optional advisory weight**, no live-number behaviour change unless a
strict gate fires.

`simplex_brier_weights` grid-solves (or analytically finds) the Brier-minimising
`w_market ∈ [0,1]` for the 2-source `{market, llm}` case, then reports:
`per_source_brier`, in-sample `ensemble_brier`, the **leave-one-out**
`loo_ensemble_brier` (the honest number, removing in-sample optimism), and a seeded
bootstrap 95% CI on the weights. `beats_both` is claimed **only** against the LOO
Brier, never the optimistic in-sample one. `fitted_market_advisory_weight` ships
the fitted weight over the static one **only** when all hold: sufficient sample, LOO
beats both inputs, **and** the LLM weight's bootstrap CI excludes 0 (the orthogonal
signal is statistically real). It deliberately does **not** extremize/Platt the
blend — the paper warns that stacking recalibration on the convex blend erases its
edge. Numpy-optional (plain stdlib by default). The same collector feeds a
market-hidden backtest arm (`market_hidden_pool_report`) that asks whether the
agent manufactures signal orthogonal to a *withheld* price.

---

## Honest limits

- **All track-record weighting is advisory and opt-in.** The default panel/quorum
  is equal-weighted; a cold-start desk (empty weight map) is byte-identical to no
  weighting.
- **Terminal Platt defaults to identity (1.0).** Nothing here turns extremization
  on; the alpha is per-question config, and even then the safety gates can clamp it
  back to 1.0.
- **The fitted market weight almost never ships** — it needs ≥30 paired resolved
  binaries, LOO-beats-both, *and* a CI excluding 0. Below that the static advisory
  weight stands.
- **Delphi v1 is one round only.** No post-revision supervisor search;
  `delphi_rounds` is 0 or 1.
- **Autorun is fail-open.** A config/resolution/spawn failure silently degrades to
  no quorum (with a note) — the commit stands either way.
- **The single-key guard fails open.** An undetectable provider picture keeps the
  panel; individual unreachable panelists simply error and the run is labeled
  `degraded` rather than pre-downgraded.
- **`model_track_record` cannot stratify by origin** (panel runs aren't origin-
  tagged per estimate), so it mixes whatever resolved binary panel data exists.

---

## Sources

Derived from and verified against:

- `forecasting/panel.py` — `PANEL_PERSPECTIVES`, `aggregate_panel_estimates`,
  `disagreement_signal`, `should_run_panel`, `DEFAULT_PANEL_AGGREGATION_METHOD`,
  the terminal-Platt fold.
- `forecasting/quorum.py` — `QUORUM_PRESETS`, `run_quorum`, `ModelForecast`,
  `JudgeSynthesis`, `QuorumResult`, `resolve_final_probability`, `should_research`,
  `resolve_quorum_defaults`, `cap_preset_by_calls`, `models_reachable`,
  `available_provider_slugs`, `quorum_auto_indicated`, `estimate_quorum_calls`,
  the Delphi builders (`build_delphi_summary`, `build_revision_context_block`).
- `forecasting/quorum_autorun.py` — `maybe_autorun_quorum`, `resolve_active_model_id`,
  the auditable skip records.
- `forecasting/ledger/panels.py` — `record_panel_run` (the gated write + the
  resolved-vs-repool logic), `component_track_record` /
  `recommended_component_weights`, `model_track_record` /
  `recommended_model_weights`, `attach_panel_to_snapshot`.
- `forecasting/calibration_bias.py` — `extremization_alpha_gate`,
  `leaned_side_hit_rate`, `diagnose_hedging`.
- `forecasting/market_ensemble.py` — `simplex_brier_weights`,
  `fitted_market_advisory_weight`, `complementarity_report`,
  `market_hidden_pool_report`, `collect_market_llm_triples`.
- `forecasting/hooks/signals.py` — `quorum_signals_from_panel_run` (the commit-side
  participation/judged signals).
