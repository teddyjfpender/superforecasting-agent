# Forecasting-Capability Audit — the substance, not the plumbing

**Date:** 2026-07-06
**Branch:** `superforecasting-agent-snapshot`
**Scope:** what would most improve this system *as a superforecasting / quantitative agent harness* — the forecasting and quant substance, not the platform spine (typed protocol, jobs runtime, data planes, hooks, docs, multiplayer M1–M3 are treated as done).
**Method:** read all 13 `docs/deep-dives/`, `docs/decisions.md`, and the five research studies (`shrinkage-study`, `forecastbench-grounding-study`, `beating-the-market-strategy`, `live-edge-study`, `harness-benchmarking-strategy`); interrogate the **live ledger** read-only at `~/.superforecasting-agent/forecasting/forecasting.db` (2,209 questions, 6,557 snapshots, 12,503 evidence items, 4,996 score records — *actively producing forecasts through today*); trace the real code paths in `forecasting/` (quorum, panels, bayes_toolkit, calibration_bias, thesis, factor, market_ensemble, triage, supervisor_search, search_ablation).

Every number below is from the live ledger or a cited file. No git operations were performed.

---

## What surprised me in the live data

The plumbing is genuinely excellent and the research discipline is unusually honest. What surprised me is how **thin the layer of real, learnable forecast signal is underneath it** — the harness has built a superb measurement apparatus and then starved it of the one thing it measures.

1. **The measurement loop runs on ~20 data points, 15 of them trivial.** Of 4,996 score records, only **20 are `calibration_eligible`** (`SELECT SUM(calibration_eligible) FROM score_records` → 17 brier + 3). All 20 are `forecast_origin='live'`; **15 of them are `weather` questions with Brier ≈ 0.000** (the agent correctly calling near-certain forecasts). The remaining genuine signal is 2 macro NLL, 2 politics, 1 vote-share. The mean live Brier of **0.0083** is an artifact of easy weather, not skill. Everything else — 3,314 `imported_baseline` (Brier 0.216) and 1,655 `backtest` (0.195) — is calibration-*ineligible* by design (the market/answer was visible). **The learning loop, the shrinkage activation gate, and calibration-bias all have essentially nothing to learn from.**

2. **The only lever proven capable of beating a market has fired zero times.** `build_supervisor_search_runner` (fresh agentic search on a flagged crux) is fully built and correctly wired into `forecasting/jobs/types/quorum.py:505-555`, but it is default-OFF and the live config never enables it: **0 of 223 `panel_runs` have `research_rounds > 0`; 0 have `supervisor_evidence`.** `beating-the-market-strategy.md:677-688` calls this "the *only* lever" (closed-book agent Brier 0.279, no intrinsic edge). It has never run on this ledger.

3. **Reference-class discipline — the superforecasting cornerstone — is at 3.6%.** Of 1,588 agent-authored snapshots (live + market_nightly + exploratory), only **57 link a reference class** (`reference_class_refs`), only 34 carry `key_assumptions` (2.1%). The `require_outside_view_anchor` rule exists but is `Severity.WARN` (`forecasting/hooks/builtins.py:605`), so it never blocks.

4. **Cruxes are generated but thrown away.** The `question_cruxes` table has a full CRUD API (`add_crux`/`get_crux`/`list_cruxes`, `forecasting/ledger/core.py:2381-2455`) and CLI commands — and **0 rows**. Meanwhile **271 of 1,048 `panel_estimates` carry a `crux`** that dies inside the panel blob, never promoted to the first-class, queryable, re-checkable table.

5. **Median source diversity per question is 1.0.** Across 1,966 questions with evidence, the median distinct `source_name` is **1**, and **1,195 questions draw from a single source** — exactly the "algorithmic monoculture" that `beating-the-market-strategy.md:164-172` names as "our biggest hidden risk," since the whole edge rests on *orthogonal* signal.

6. **The newest feature is dormant and the numeric class is unscored.** Delphi revision rounds (shipped in HEAD commit `0e8a5e4a4`): **0 of 223 panels** used them. CRPS: **zero occurrences anywhere in the codebase**; of ~162 non-binary resolved questions, **6 have a score record**, and the 78 *active* distribution questions have no proper scoring rule waiting for them.

---

## Ranked findings

Ranked by **(impact on Brier or decision quality) / effort**. Each: evidence → why it matters → the concrete buildable fix → impact → effort.

### 1. Turn on the fresh-search lever in the live quorum (it has never fired)

- **Evidence.** `forecasting/supervisor_search.py` builds a bounded, leak-filtered fresh-search runner; `forecasting/jobs/types/quorum.py:497-555` constructs it and threads it into `run_quorum` **only when `_supervisor_search_enabled(spec)` is true** (`:261-280`), which is opt-in, default OFF. Ledger: `SELECT COUNT(*) FROM panel_runs WHERE research_rounds>0` → **0** (of 223). `beating-the-market-strategy.md:684-688`: "the entire bet now rests on Lever B (search, #181) … B is not the largest lever — it is the *only* lever." `harness-benchmarking-strategy.md:97`: the closed-book agent "has no intrinsic edge over the market; its market-visible skill was borrowed."
- **Why it matters.** The grounding study proved the LLM alone loses head-to-head (Brier 0.279 vs 0.164) and is over-confident (SCE +0.20). Fresh information the market hasn't priced is the mechanically-only path to a real edge. The seam is built and unit-tested (`tests/forecasting/test_supervisor_search_wiring.py`) — it is simply switched off in production.
- **Fix.** Flip `quorum.supervisor_search` to default-ON for `forecast_origin='live'` runs (keep it OFF for backtest/historical-cutoff paths, which must not leak). Verify the live cron/autorun config actually passes it end-to-end. Add a `research_rounds` coverage tally to the desk so a regression back to 0 is visible.
- **Impact.** Potentially the whole edge. This is the difference between a harness that *can* beat markets and one that provably echoes them.
- **Effort.** Low — a default flip, a config-plumbing verification, and one telemetry line. No new algorithm.

### 2. Feed the measurement loop calibration-eligible *contested* binaries

- **Evidence.** 20 calibration-eligible scores total, 15 trivial weather (above). `shrinkage-study.md:161-163`: "The decision-relevant LIVE stratum cannot be tested. All 17 scored live forecasts are `categorical`, so the binary-Brier shrinkage sweep has **zero** live observations." The confirmed shrinkage correction (α≈0.50, Δ Brier +0.0074→+0.013, p≈1e-4, `shrinkage-study.md:122-131`) is **shipped OFF** and cannot activate without live binary n≥50. Active stratum today: 384 binary, 78 distribution, 6 numeric, **194 closing within 30 days** — but the live `market_nightly` cohort (292 snapshots) has only **4 score records**.
- **Why it matters.** Learning loop, shrinkage activation, calibration-bias lessons, track-record weights, and any panel-vs-solo verdict *all* require resolved, scored, calibration-eligible questions. The desk is producing 662 live snapshots per fortnight and learning from ~20 lifetime. This is the binding constraint on every downstream capability.
- **Fix.** Curate/author a standing pool of **short-horizon (≤30d) contested binary** questions (Kalshi/Polymarket weeklies where the market is genuinely uncertain, |p−0.5| small), and make sure their resolutions flow as `calibration_eligible=1`. Add a desk readout: "calibration-eligible resolved binaries: N / target 50" so the accrual toward the shrinkage activation gate is visible and steerable.
- **Impact.** High and compounding — it is the prerequisite that unblocks findings 1, 5, shrinkage activation, and the whole learning-loop thesis (C5).
- **Effort.** Medium — question authoring/curation + a resolution-eligibility check + one dashboard tile. No new math.

### 3. Wire CRPS (or a proper continuous score) for the distribution/numeric class

- **Evidence.** `grep -ri crps` over the repo: **zero hits.** Distributions are scored by `normal_negative_log_likelihood` (2 records) and vote-shares by `vote_share_rmse_pp_manual` (4) — of ~162 non-binary resolved questions. 78 distribution + 6 numeric questions are *active now*. `beating-the-market-strategy.md:586-588,737`: the numeric/dataset class is "the biggest *structural* gap [markets don't cover] … needs CRPS, not Brier … the most promising hunting ground is also the least validated today."
- **Why it matters.** The class the literature says is *most* beatable is the class we cannot yet score, so we can neither prove skill there nor learn from it. `normal_NLL` also assumes a Gaussian and punishes tails arbitrarily; CRPS is proper for any predictive distribution and is the standard for continuous forecasts.
- **Fix.** Add `crps` as a `score_rule` in `score_snapshot` for `distribution`/`numeric` outcome types (closed-form CRPS for the normal/mixture families the desk already emits; empirical CRPS for sample-based ones). Backfill the resolved distribution/numeric questions. Surface CRPS alongside Brier in `calibration_summary`.
- **Impact.** High — unlocks measurement on the highest structural-edge class and gives the 78 active distributions a real scoreboard.
- **Effort.** Medium — a well-defined scoring function + backfill; the distribution representations already exist.

### 4. Enforce the outside-view anchor and promote cruxes to first-class objects

- **Evidence.** `reference_class_refs` populated on 57/1,588 agent snapshots (**3.6%**); `require_outside_view_anchor` is `Severity.WARN` (`forecasting/hooks/builtins.py:605`). `question_cruxes`: **0 rows** despite `add_crux` + CLI (`forecasting/ledger/core.py:2381`); `panel_estimates.crux`: **271/1,048 populated** but non-durable.
- **Why it matters.** Reference-class base-rate anchoring is the single most reliable superforecasting technique, and the agent skips it 96% of the time because the rule is advisory. Cruxes are the substrate for "what would change my mind" (decision leverage), for the consistency-arbitrage skill gate (`beating-the-market-strategy.md:329-336`), and for re-checking whether the pivotal variable moved between updates — none of which is possible while they live only inside per-panelist blobs.
- **Fix.** (a) Promote `require_outside_view_anchor` to `Severity.ERROR` for high-impact live questions (keep WARN for exploratory). (b) Auto-promote `panel_estimates.crux` → `question_cruxes` at panel commit (dedupe by variable), making cruxes queryable, materiality-ranked, and status-trackable across updates.
- **Impact.** Medium-high — directly lifts reasoning quality (base-rate anchoring) and turns 271 discarded cruxes into a decision-relevance and consistency-check surface.
- **Effort.** Low — one severity change + a ~20-line promotion hook over an API that already exists.

### 5. Run the panel/quorum-vs-solo ablation to a verdict *on this ledger*

- **Evidence.** No on-ledger result shows panels/quorum/ensemble beat the mean baseline. `quorum-and-panels.md:43` defines the mean as "the floor any pool/judge must beat" — never shown beaten here; `:92` cites quorum lift from *literature*, not this ledger. `search_ablation.py` (the 2×2) is built but **cannot populate**: its search arm keys on `research_rounds>0`, which is 0 everywhere (finding 1). Panels ran on only **110 of 2,209 questions (5%)**.
- **Why it matters.** The desk spends real compute on 5-role panels + judge synthesis + (soon) Delphi on the belief they help, with zero measured confirmation. The paired recenter-at-zero bootstrap (B=10k) already exists — the verdict is one scheduled job away, and it decides whether the panel machinery earns its cost.
- **Fix.** A scheduled ablation job that, over resolved calibration-eligible binaries, computes solo-vs-panel-vs-judge (and search-on/off once finding 1 lands) mean Brier + paired bootstrap CI, persisted to a report table and surfaced on the desk. Depends on findings 1 & 2 for a populated sample.
- **Impact.** High for decision quality — converts "we believe panels help" into a measured, defensible number (or kills a costly ritual).
- **Effort.** Medium — orchestration over existing scoring/bootstrap primitives; gated on eligible-resolution supply.

### 6. Instrument source and panel diversity (the monoculture guard)

- **Evidence.** Median distinct `source_name` per question = **1.0**; 1,195/1,966 questions single-source (ledger). `beating-the-market-strategy.md:164-172,240`: "Diversity must be engineered and MEASURED, not assumed — this is the missing instrument"; "Pairwise panel correlation + agent-vs-market residual correlation as first-class metrics" (a stated need, unbuilt). Panels are single-model in practice (`live-edge-study.md:390-391`: "Single model (codex/gpt-5.5), single search backend … no model or search-provider sweep yet").
- **Why it matters.** The entire edge rests on *orthogonal* signal (`live-edge-study.md:231` — the n=55 orthogonality result r=0.765 is the in-session headline). A homogeneous panel reading one source reproduces the consensus and has nothing to pool. Diversity is currently assumed; if it silently collapses, so does the edge, invisibly.
- **Fix.** Three first-class metrics on the desk: per-question independent-source count + primary-source fraction; pairwise panel-estimate correlation; agent-vs-market *residual* correlation. Warn (not block) when a serious live forecast is single-source or the panel is near-collinear.
- **Impact.** Medium — protects the one property the whole thesis depends on, and makes the diversity/model-sweep investment steerable.
- **Effort.** Low-medium — aggregation queries over data already stored (`evidence_items`, `panel_estimates`) + a desk surface.

---

## Secondary findings (real, lower rank)

- **Delphi is shipped-but-dormant.** 0/223 panels used `delphi_rounds` (HEAD feature). It rides on the panel path; enabling it is cheap but should wait behind a measured reason (finding 5) so it doesn't add cost without evidence.
- **Human-in-the-loop surfaces are empty.** `operator_estimates`, `forecast_corrections`, `forecast_update_proposals`, `ingest_candidates`, `triage_rubrics` all have **0 rows**; `triage_labels` = 12 (labeler is `suggest_only` until an 80% gate clears, `evidence-and-triage.md:216`). The correction/proposal/operator-estimate loop that the multiplayer work presumes is untrodden — worth a lightweight seeding pass before it's assumed to work.
- **Factor/thesis correlation ρ is a heuristic, not fit.** `ρ = clamp(0.6 − 0.25·spread, 0, 0.95)` (`thesis-and-factor-math.md:136`) rather than estimated from member co-movement history. The quant band is honest but its correlation input is assumed. Only 2 `market_models` / 14 `market_data_series` exist — the quant layer is barely exercised live, so this is low-urgency until it's used.
- **"Why did the number move?" is not attributed.** `change_my_mind` is populated (61%), but there is no snapshot-to-snapshot decomposition of *what evidence drove a probability change*. This is the top operator-leverage gap once findings 1–4 make numbers move for real reasons.
- **Deferred scoring rigor.** Log score is stored but never used downstream (all ensembling/α-sweep/weighting is Brier-only); DM test, Murphy decomposition, Mincer-Zarnowitz, and block/clustered bootstrap are pre-registered in `beating-the-market-strategy.md:298-336` but unrun. Time-weighted (workflow) skill has no cohort at all. Fold these in when finding 2 gives them a sample.
- **VOI is a prompt A/B, not a computation.** The "voi" arm (`market_nightly_forecaster.py:231-349`) is a research-discipline *prompt*, not an expected-value-of-information allocation over cruxes/sources. A true EVPI targeting layer is a natural successor to findings 4+6, not a near-term win.

---

## Deliberately fine as-is (do not "fix")

- **Terminal Platt extremization OFF (α=1.0).** Empirically correct and refuted twice: LOO-Brier-minimizing α is 1.0 on both the 240-case ForecastBench and 480-case backtest; √3 raises Brier; `diagnose_hedging` returns `center_ward_hedge=False`. Leave off.
- **Shrinkage (α≈0.50) shipped OFF behind a live-binary-n≥50 gate.** The correct posture — confirmed on backtest, honestly withheld from live until the decision stratum can test it (finding 2 is what earns the flip).
- **Estimator honesty (None-never-0), max-drawdown refusal, no-fabricated-bands, thesis extremization hard-disabled.** These are principled refusals to manufacture numbers, and they are the reason the ledger can be trusted. Keep them.
- **The leak firewall's UNCALIBRATED prevalence constant.** Flagged honestly as the "one un-de-risked piece"; the fix is hand-labeling, not code — a data task, correctly deferred.

---

## Honest data limits of this audit

- **The positive forecasting results live in calibration-ineligible data.** The only large-n Brier comparison (ForecastBench, 240) had the market visible; the market-hidden arm (n small) showed no intrinsic edge; the live contested stratum is effectively n=1. Nothing here can be read as "the harness beats markets" — the audit's findings are about *unblocking the ability to prove or disprove it*, which is the correct near-term objective.
- **Ledger origin mixing.** Rates were computed on the agent-authored subset (live + market_nightly + exploratory, n=1,588) where backfill methods can't contribute reasoning artifacts, to avoid understating them. Even so, reference-class (3.6%) and key-assumption (2.1%) rates are strikingly low.
- **`source_name` nulls.** ~1,036 evidence rows have a null `source_name`, which slightly deflates the diversity median; the qualitative finding (heavy single-adapter concentration per question — FRED 3,610, Yahoo 854) is robust regardless.

---

## The one-line takeaway

The harness has built a world-class *measurement and honesty apparatus* and a genuine *edge mechanism* (fresh agentic search), then left the mechanism switched off and starved the apparatus of eligible data. The top two moves — **turn on supervisor search for live quorum** and **feed the loop contested-binary resolutions** — are low-effort, unblock everything else, and are the difference between a harness that provably beats markets and one that has only proven it *can echo them honestly*.
