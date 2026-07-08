# Superforecaster Gates — making the formal practices the hard-wired default

**Date:** 2026-07-08 · **Status:** PLAN (researched against the live ledger + `superforecasting-agent-snapshot` HEAD)
**Author:** desk engineering, with a full read of `forecasting/hooks/`, the `create_snapshot` commit path, the quorum market-anchor discipline, crux promotion, lesson enforcement, and the live ledger at `~/.superforecasting-agent/forecasting/forecasting.db` (read-only).

---

## 0. Operating principle

The operator is a lazy prompter **by design**. Every formal superforecasting practice must
therefore be **native** (a first-class ledger/schema concept, not prose in a prompt),
**default-ON** (the standard profile enforces it with zero per-question config), and
**gate-enforced** (a commit that skips the practice is refused or visibly flagged; the system
cannot silently regress). The measure of success is: the operator can trust a committed
forecast without checking it, because the class of failure they just caught by hand can no
longer pass the gates.

This plan exists because that trust was violated by an exemplar that passed everything.

---

## 1. The exemplar autopsy — why Clacton passed at 100/100

`fq_3d4b092912a1` "What vote shares will candidates receive in the 2026 Clacton
parliamentary by-election?" — outcome space `distribution` with `choices` (a candidate-share
question), `impact=high`, `domain=politics`. Current snapshot `fs_526baa283165` (live,
gpt-5.5, committed 2026-07-08T11:28:57Z):

- **Payload:** `{Count Binface: 16.5, Laurence Fox: 4.0, Nigel Farage: 67.0, Other official candidates: 12.5}` (pp).
- **The leader work is 8/10:** BBC ballot-structure crux, Davis-2008 (71.6%) / Carswell-2014
  (59.7%) reference classes, PollCheck 60.2% model, conditioned Monte Carlo → 67% median.
  One reference class linked (`rc_28fa63156f9b`, base_rate 0.6 — the *leader's* winner share).
- **The tail is 3/10:** Count Binface at **16.5%** with **no cited base rate anywhere** (his
  real electoral ceiling is ~1-3%); unearned specificity for a named person vs the residual
  "Other" bucket; `confidence` NULL (the TUI's `conf —`).
- **Recorded saturation: 100.0, passed, zero warnings.** All 22 applicable rules PASS.

Why every gate passed — three scope holes and two unbuilt gates:

1. **The `question_type→distribution` gotcha.** `require_outcome_paths` and
   `tails_justified` apply only when `ctx.is_categorical`
   (`forecasting/hooks/builtins.py:617,640`). A candidate-share question has
   `outcome_space.type == "distribution"`, so the entire tail-audit arm — the one gate
   family built exactly for "unearned mass on a named-but-non-live option"
   (`forecasting/tail_audit.py:1-22`) — **never evaluated**. `metadata['tail_audit']` is only
   stamped for categoricals (`snapshots.py:574`).
2. **The anchor gate counts, it does not cover.** `require_outside_view_anchor`
   (`builtins.py:548`) passes on `linked_reference_class_count >= 1`. One leader-scoped
   reference class satisfied it; nothing demands that *each named outcome carrying material
   mass* has a base rate.
3. **Sharpness is scale-broken for pp payloads.** `ForecastLedger._sharpness`
   (`forecasting/ledger/core.py:10084`) returns `max(numeric values)` for a dict — 67.0 on a
   0-100 pp payload — so `confidence_committed` (floor 0.05) is vacuously satisfied for every
   share forecast.
4. **Per-candidate intervals have a render path but no gate.** The snapshot actually carried
   `metadata.candidate_share_intervals_pp` (the protocol nudge at `forecasting/protocol.py:128`
   worked), including Binface `p05 11.5 / p95 22.5` — precise, unanchored, and **nothing
   validated coverage, coherence, or anchoring**. 18 of the other 19 live candidate-share
   questions carry no intervals at all. The `conf —` is the NULL `confidence` column
   (`forecastsWorkspace.tsx:1844`), never gated either.
5. **No market/coherence/crux/cadence rules exist at all** (§3, G5-G8).

The target class: **pass-when-it-shouldn't on the tail of a distribution.** P1 closes exactly
that.

---

## 2. The lattice today — what already enforces, and where

27 built-in rules (`forecasting/hooks/builtins.py`, generated table
`docs/reference/hooks-rules.md`, staleness-gated by `python -m scripts.docgen --check`).
Enforcement chokepoints in `create_snapshot` (`forecasting/ledger/snapshots.py:291`):

1. **Inline gates** (first-failing-wins, byte-identical messages): structured reasoning,
   components, fresh evidence, decision readiness, panel, citations, categorical tail audit,
   style, distribution structure.
2. **User-rule + compiled `lesson:*` pass** — fail-open engine, legitimately-failing ERROR
   blocks; lesson severities resist overrides (`engine.py:90-95`).
3. **Resolved-policy blocking pass** — the non-inline builtins under
   `resolve_severities` (profile + impact/origin scaling + overrides), fires only for
   `forecast_origin == "live"` + `enforce_resolved_hooks=True` (the agent's `update_forecast`
   path) + no autofix flags + kill-switch unset. **All new rules in this plan ride this pass**
   — no new inline gates.
4. **Observe-mode report** stamped to `metadata['saturation']` (best-effort, never blocks);
   the sweep/badge/alert surfaces read it (`hooks/sweep.py`, `ledger/alerts.py`).

Severity ladder: `exploratory-lenient → standard → strict` (`profiles.py`), impact scaling
bumps rungs, per-question `metadata['forecast_hooks']` overrides, per-question numeric
thresholds via the `thresholds.py` registry. Exploratory origin bypasses everything by
design (the relief valve — keep it).

**The WARN-first precedent** (reused throughout §5): `require_outside_view_anchor` landed
WARN (`a0cfae8a2`), gathered live evidence (skipped ~96% of the time), then was promoted to
ERROR scoped to high-impact (`0673c0296`) — after gating on `has_prior` **bricked the routine
re-forecast flow** (proven by the stale-rerun e2e before scoping). Lesson-compiled rules
default WARN ("observe-then-flip", `lesson_templates.py`). Phase-1 hooks ran observe-mode
before the enforcement flip. That is the promotion discipline this plan follows.

---

## 3. The eight gates

Conventions for each: **Exists** (what partial machinery is already there, by rule/file),
**Gap**, **Signal** (computable at commit, from what data), **Rule** (id / category /
severity per profile / weight / applies scope), **Remediation message** (teaching, in the
house voice of the existing messages), **Test**, **Live fail count** (read-only, run
2026-07-08 against 387 active questions; 380 with a current snapshot; **175 of those
live-origin** — the other 205 are `market_nightly` benchmark arms that the live gates
correctly ignore).

### G1 · Distribution-tail base rates (the Binface gate) — **P1**

- **Exists:** the categorical tail audit (`tail_audit.py`: `audit_outcomes`,
  `OutcomePath{name, probability, path, classification, evidence_strength}`, residual
  taxonomy, `DEFAULT_MASS_THRESHOLD=0.005`, `DEFAULT_RESIDUAL_CAP=0.05`) +
  `require_outcome_paths` (WARN standard / ERROR strict) + `tails_justified` (WARN). The
  `outcome_paths` commit param already plumbs through `create_snapshot` and the CLI
  (`--outcome-path`).
- **Gap (two):** (a) scope — the whole family keys on `is_categorical`, so candidate-share
  *distributions* (the Clacton shape, 19 live questions) are never audited; (b) substance —
  a path is not a base rate. Binface had an implied "novelty focal candidate" path; what he
  never had was a **cited reference class** ("Binface's own prior results: 2024 GE Richmond
  0.9%, 2021/2024 London mayoral ~1-2%"). Named-person mass above a threshold must carry a
  numeric outside view, else the mass belongs in the residual bucket.
- **Signal (all computable at commit, no new IO):**
  - `is_candidate_share: bool` — reuse `_is_candidate_share_pmf`'s share extraction
    (`hooks/distribution.py:32`: numeric non-stat keys summing ~1/~100) + `outcome_space.choices`.
  - Extend `OutcomePath` with `base_rate: float | None`, `base_rate_source: str` and the
    commit param `outcome_paths` accordingly (the agent already passes this dict; add the two
    keys per outcome). An outcome is **anchored** when it carries a finite `base_rate` and a
    non-empty `base_rate_source`, or when `outcome_anchors[name].reference_class_ref` names a
    reference class that is linked to this snapshot (validated question-scoped, like every
    other ref).
  - New context fields: `share_named_unanchored: tuple[str, ...]`,
    `share_named_unanchored_mass: float`, computed by running `audit_outcomes` over the
    extracted shares normalized to 0-1 (pp payloads divided by 100).
  - **Residual matcher fix:** `_RESIDUAL_NAMES` is exact-match; "Other official candidates"
    escapes it. Extend `OutcomePath.is_residual` to prefix-match `other`/`others`/`any other`
    and honor `classification="residual"`.
  - Threshold: `named_outcome_anchor_share` in the `thresholds.py` registry, default
    **0.10** (10% of mass; `direction="higher_looser"`), per-question overridable.
- **Rule:** `require_tail_base_rates` · Category `REASONING` · weight 14.0 ·
  applies: live, modeled, `(is_categorical or is_candidate_share)` ·
  severities: exploratory OFF / **standard ERROR** / strict ERROR.
  Check: every named, non-residual outcome whose share exceeds the threshold is anchored.
  Residual buckets are exempt (that is where unanchored mass belongs). ERROR is safe to land
  immediately because it only binds *future* commits; the 19 open share questions hit it on
  their next re-forecast, which is exactly when the anchor should be collected.
  Also extend the scope of `require_outcome_paths` + `tails_justified` from
  `c.is_categorical` to `c.is_categorical or c.is_candidate_share` and stamp
  `metadata['tail_audit']` for share payloads in `create_snapshot` (closing the gotcha for
  the path rules too, at their existing WARN severity — no new blast radius).
- **Remediation message:**
  > "live {categorical|vote-share} forecast puts {mass:.1%} on named outcome(s) with NO cited
  > base rate: {offenders}. A named person or option above {threshold:.0%} must carry an
  > outside view — pass outcome_paths with base_rate + base_rate_source for each (e.g. the
  > candidate's own prior vote shares), link a reference class scoped to that outcome, or
  > move the mass into the residual 'Other' bucket where unanchored mass belongs. Precision
  > you cannot cite is not precision."
  Remediation descriptor: agentic `add_reference_class`, target_stage `research`.
- **Test:** `tests/forecasting/test_tail_base_rates.py` — (1) Clacton canary: a fixture
  reproducing `fs_526baa283165`'s commit context (pp shares, one leader rc, no per-outcome
  anchors) MUST raise `SaturationBlocked` naming `Count Binface`; (2) anchored version
  (Binface base_rate 0.02 + source) passes and forces the number down or the mass into
  residual is *not* asserted (the gate teaches, it does not compute); (3) residual bucket
  "Other official candidates" at 30% does not fire this rule (it fires the residual-cap WARN
  in the tail audit instead); (4) categorical question keeps byte-identical behavior;
  (5) binary/continuous unaffected (`applies` False).
- **Live fail count:** **19 / 19** live candidate-share questions (every open primary/
  by-election share board, incl. Clacton) currently have ≥1 named non-residual outcome >10%
  with no per-outcome anchor. None block until their next commit.

### G2 · Per-candidate intervals — build out + gate — **P1 (gate) / P2 (surfaces)**

- **Exists (more than the memory says):** commit `e5811e3b2` shipped the chosen
  representation: out-of-band `metadata.candidate_share_intervals_pp = {candidate: {p05,
  median|p50, p95}}` (pp), dashboard normalization `_candidate_intervals`
  (`dashboard.py:497`, scale auto-detect, drops inverted), workspace field
  `candidate_intervals` (`dashboard.py:1015`), TUI numeric rendering (`[lo–hi]` per bar,
  `forecastCharts.ts:690-693`; leader line "· 90% [lo–hi] / · no interval published"), and
  the protocol elicitation nudge (`protocol.py:128`). Clacton complied.
  **Nested `{candidate:{share,lo,hi}}` payloads are confirmed incompatible** with
  `_validate_probability_payload` (`core.py:9815`), `_vote_share_vector_score`
  (`scoring.py:1373`), and `_is_candidate_share_pmf` — keep intervals out-of-band; do NOT
  change the payload schema.
- **Gap:** no gate (18/19 live share questions carry no intervals; nothing checks coverage,
  coherence lo≤mid≤hi, or median-vs-payload agreement); the stale comment at
  `forecastsWorkspace.tsx:1879` says "unbuilt"; no whisker glyphs on the bar rail; resolution
  scoring ignores interval coverage; `confidence` NULL renders `conf —` un-gated.
- **Signal:** at commit, parse `metadata.candidate_share_intervals_pp` with the SAME
  normalization the dashboard uses (lift `_candidate_intervals`'s core into
  `hooks/distribution.py` so gate and chart agree, mirroring the `assess_distribution`
  pattern). New context fields: `candidate_interval_coverage: float | None` (covered named
  non-residual choices / total; None for non-share), `candidate_intervals_coherent: bool`
  (every entry finite, `lo <= mid <= hi`, `mid` within `interval_median_tolerance_pp`
  (new threshold, default 2.0pp) of the payload share, `lo/hi` within bounds), plus the
  metadata escape `no_interval_reason` (string, stamped like `panel_skipped_reason`).
- **Rules (two):**
  - `candidate_intervals_present` · `OUTPUT` · weight 10.0 · applies: live, modeled,
    `is_candidate_share` · severities: exploratory OFF / **standard WARN → promote to ERROR
    after one review cycle** (§5) / strict ERROR. Check: coverage == 1.0 for named
    non-residual choices, OR `no_interval_reason` recorded.
  - `candidate_intervals_coherent` · `OUTPUT` · weight 12.0 · applies: live, modeled,
    `is_candidate_share`, intervals present · severities: **standard ERROR immediately**
    (structural bug-catcher, same class as `uncertainty_well_formed`; fail count today ~0).
- **Remediation messages:**
  > present: "vote-share forecast carries no per-candidate uncertainty: add
  > metadata.candidate_share_intervals_pp = {candidate: {p05, median, p95}} (percentage
  > points) for every named candidate — the Desk draws an error bar per candidate and the
  > scorer will grade interval coverage at resolution. A point share with no spread is a
  > claim you did not quantify. If intervals are genuinely not computable here, record
  > no_interval_reason."
  > coherent: "per-candidate intervals are malformed: {issues}. Each candidate needs finite
  > p05 <= median <= p95, the median within {tol}pp of the committed share, inside the
  > question bounds. Fix the intervals — a band that contradicts its own point is worse than
  > no band."
  Remediation: mechanical `fix_distribution` (coherence) / agentic `sharpen` (presence).
- **P2 build-out (the rest of the arc):** (a) whisker glyphs on the histogram rail
  (`forecastCharts.ts:673` — render `lo/hi` as positioned marks; the per-bar `interval` data
  is already attached); (b) resolution-time interval scoring: extend
  `_vote_share_vector_score` to record per-candidate hit/miss of `[p05,p95]` (target ~90%
  coverage over time — the desk's interval calibration curve, fed to `forecast calibration`);
  (c) delete the stale "chosen-but-unbuilt" comments; (d) quorum share-vector prompts elicit
  per-candidate spreads natively (`quorum.py` panelist field), so intervals arrive from the
  panel instead of being back-filled by the committer.
- **Test:** `test_candidate_interval_gates.py` — coverage/coherence/escape/scale (fraction
  vs pp payload) cases; Clacton canary asserts its intervals PASS coherence (they were
  well-formed) while G1 still blocks it — the two failures are independent.
- **Live fail count:** presence **18 / 19**; coherence **0** observed (Clacton's parse
  cleanly).

### G3 · Reference-class universality (extend the anchor honestly) — **P3**

- **Exists:** `require_outside_view_anchor` — ERROR in standard **scoped inside the check to
  high-impact only** (`builtins.py:548-583`), snapshot-honest (`linked_reference_class_count`
  falls back to question count on lint so re-reads don't over-fire). The scoping history
  (`0673c0296`): gating `has_prior` too demanded a freshly-linked reference class on EVERY
  routine re-forecast and **bricked the re-forecast flow** (stale-rerun e2e). `research_adequate`
  (WARN) already counts a missing reference class among its deterministic checks.
- **Gap:** ~96% of non-high-impact live commits never link an anchor and never will while the
  rule self-passes. 171/175 current live snapshots link zero reference classes; **93
  questions have none at all** — pure inside view on the books.
- **Design around the has_prior trap (two tiers, two rules, no re-forecast bricking):**
  - Extend `_check_outside_view_anchor` to also fire on **`not ctx.has_prior`** (the FIRST
    live commit of ANY question) at its resolved severity (ERROR in standard). The first
    commit is where the outside view is cheapest, most valuable, and has no re-forecast flow
    to brick — the e2e that broke gated *re*-commits, not first commits. High-impact stays
    ERROR on every commit, exactly as today (snapshot-linked).
  - New rule `outside_view_refresh` · `REASONING` · weight 6.0 · applies: live, modeled,
    `has_prior`, not high-impact · **WARN in standard, ERROR in strict**. Check:
    `reference_class_count >= 1` at the QUESTION level (not snapshot-linked — a routine
    re-commit need not re-link, killing the brick vector) — i.e. "this question has an
    outside-view anchor somewhere on the books". WARN nags every stale re-forecast of the 93
    anchor-less questions without blocking the flow.
- **Remediation messages:** first-commit tier reuses the existing three-branch message
  (unlinked / claims-outside-view / none) with the added opener "first live forecast on this
  question requires an outside-view anchor". Refresh tier:
  > "this question still has NO reference class on the books after {n} commits — the
  > forecast has been pure inside view since birth. Call 'add_reference_class' with the base
  > rate you are implicitly using; if you cannot name one, that is the finding."
- **Test:** extend `test_hook_blocking_pass.py` — first-commit non-high-impact with no rc →
  blocks; re-commit of the same question (rc linked once) → passes both tiers; re-commit
  with question-level rc but unlinked snapshot → passes ERROR tier, passes WARN tier; the
  stale-rerun e2e (`tests/` journey harness) stays green — this is the regression that
  scoped the rule last time, and it must be in CI before the flip.
- **Live fail count:** first-commit tier: **0 retroactive** (fires only on new questions);
  refresh WARN tier: **93 / 175** (the anchor-less backlog, surfaced not blocked).

### G4 · Granularity discipline (Tetlock's hallmark) — **P3**

- **Exists:** `confidence_committed` (anti-coin-flip WARN, floor `min_sharpness=0.05`,
  escape `metadata.uncertainty_justified`) — the *hedging* half. Nothing checks the
  *false-roundness* half, and `_sharpness` is scale-broken for pp payloads (§1.3).
- **Gap + fix:** (a) **fix `_sharpness`**: detect pp-scale share dicts (sum ~100) and
  normalize to 0-1 before `max()`, so `confidence_committed` means something for share
  boards; (b) new round-number rule. Deliberately **WARN forever, never ERROR** — hard-gating
  precision teaches models to fabricate 0.43s, the opposite failure. The rule exists to make
  round-number anchoring *visible* (the desk badge + adherence scorecard), not to block.
- **Signal:** binary live commits: `round_number_anchored: bool` — `p` is an exact multiple
  of 0.10, or exactly 0.5, and `uncertainty_justified` unset and `ensemble_components`
  carry no numeric pooled value within 0.005 of `p` (a pool that legitimately lands on 0.60
  is earned roundness; check is pure arithmetic on data already in scope).
- **Rule:** `granularity_disciplined` · `CONFIDENCE` · weight 4.0 · applies: live, modeled,
  binary · exploratory OFF / standard WARN / strict WARN.
- **Remediation message:**
  > "the committed probability {p} is a round-number anchor (multiple of 0.10) that no pooled
  > component actually produced. Tetlock's granularity finding: superforecasters' edge lives
  > in distinctions finer than 10%. Re-pool the components and commit the number the
  > evidence computes — or record uncertainty_justified if the roundness is genuinely earned."
  Remediation: agentic `sharpen`.
- **Test:** p=0.60 with components pooling 0.60 → pass; p=0.60 with components pooling 0.57 →
  warn; p=0.5 warns regardless unless justified; distribution/categorical unaffected;
  `_sharpness({shares pp})` returns normalized value (unit test pinning the Clacton payload
  at 0.67, not 67).
- **Live fail count:** **16 / 94** binaries sit on 0.05-multiples (2 at exactly 0.5) — the
  proxy count without the components-pool subtraction; the shipped rule will fire on fewer.

### G5 · Update cadence (stale beyond cadence escalates) — **P3**

- **Exists:** rich but un-gated: weekly default `scheduled_reviews` on live questions
  (`reviews.py:77,225`), deadline-aware cadence clamp (`reviews.py:770`), the VOI staleness
  term (dominant weight 0.55, `dashboard.py:643`), review-queue reasons
  (`last_update_{N}d_plus`), the freshness badge, `require_fresh_evidence` +
  `stale_evidence_justified` at commit, under-saturation alerts (`alerts.py`). The cron spine
  runs `run_due_scheduled_reviews`.
- **Gap:** "stale beyond cadence" never becomes a *rule verdict* — it is a soft VOI number
  the lazy operator has to go looking for. Nothing escalates a question whose current
  snapshot has out-lived its cadence with no recorded reason. (A commit-time gate is the
  wrong shape: a stale question is stale precisely because it is NOT committing.)
- **Signal:** sweep/lint-side (`build_context_from_ledger` already has the question):
  `cadence_overdue_ratio: float` = age(current.as_of) / cadence_days(question.review_cadence,
  default 7) — new context field, populated only for lint/sweep events (commit path leaves it
  0.0). Threshold `cadence_grace_ratio` in the registry, default **1.5**
  (`higher_looser`). Passing state also requires: no `stale_evidence_reason` on the current
  snapshot covering the gap (an acknowledged, explained pause is honest).
- **Rule:** `update_cadence_honored` · `DECISION` · weight 8.0 · applies:
  `event in {"lint","finish_sweep"}`, live current snapshot, question active with a cadence ·
  exploratory OFF / standard WARN / strict ERROR. WARN here has teeth because the sweep
  wiring exists: a failing verdict (a) drops the saturation score below the badge bar on the
  Desk, (b) rides `sweep_saturation_alerts` → a deduped `cadence_overdue` alert in the
  warnings drain the cron already services, (c) shows on the doctor scorecard (§7). The
  autonomous reforecast cycle (`cycle --agent`) treats the alert as a work item — the desk
  heals itself; the operator just sees the badge count fall.
- **Remediation message:**
  > "this forecast is {ratio:.1f}x past its {cadence} review cadence with no recorded
  > reason. A forecast that is not updated on cadence is not a live forecast — run
  > `forecast refresh <id>` (or the autonomous cycle), or record stale_evidence_reason if
  > nothing material can have changed."
  Remediation: agentic `collect_evidence`, target_stage `research`.
- **Test:** lint on an 8-day-old weekly question fails; the same with
  `stale_evidence_reason` passes; commit event never evaluates it; alert dedupe (two sweeps,
  one alert).
- **Live fail count:** **44 / 175** live questions are past cadence × grace today.

### G6 · Sum/coherence for distributions — **P1 (rides existing ERRORs)**

- **Exists:** `output_renderable` + `uncertainty_well_formed` (both ERROR standard) via
  `assess_distribution`: ordered, nested ci50⊂ci90, finite, non-degenerate, in-bounds,
  central-in-band. Share payloads: `_is_candidate_share_pmf` requires sum in [0.9,1.1] /
  [90,110] for renderability — an implicit, loose (±10%) sum gate.
- **Gap:** (a) share-sum tolerance ±10% is not "sums to 100"; a 108pp board commits; (b) no
  negativity check on shares; (c) no monotone-CDF check over the quantile vocabulary
  (`q01..q99`/`p05..p95` keys) — only the ci pairs are ordered/nested; a payload with
  `q25 > q75` passes today.
- **Change (no new rule — extend `assess_distribution`, the failures surface through the
  existing ERROR rules and the same autofix/programmatic leniency):**
  - share payloads (when `is_candidate_share`): `sum within ±2%` of 1/100 (new issue string
    "candidate shares sum to {total}, not ~100"), every share ≥ 0; keep the 0.9-1.1 band for
    *classification* so a mis-summed board is still recognized as a share PMF and produces
    the precise message instead of the generic not-renderable one.
  - continuous payloads: extract the ordered quantile chain from the stat keys; any
    inversion → `well_formed=False` with "quantiles are not monotone: {pairs}"; median/mean
    must sit within [q05,q95] when both present (generalizes central-in-band).
  - `autofix_distribution` learns the mechanical repairs (renormalize shares by the sum when
    within ±10%; sort nothing — a non-monotone quantile chain is a reasoning error, recorded
    `distribution_autofix_incomplete`).
- **Remediation:** existing `fix_distribution` messages, now carrying the new issue strings.
- **Test:** extend `test_hook_v2.py` distribution cases — 108pp board blocks with the sum
  message; negative share blocks; `q25>q75` blocks; programmatic path autofix-renormalizes
  within band; all 19 live boards re-linted still pass (the count below).
- **Live fail count:** **0 / 175** — free to land at ERROR immediately; it is pure
  anti-regression armor.

### G7 · Pre-mortem / crux minimum on high-impact — **P3**

- **Exists:** `change_my_mind` hard-required on every live commit (structured reasoning,
  ERROR); panelist `crux` fields auto-promote into `question_cruxes` on every
  `record_panel_run` (`panels.py:264-276`, text-hash dedupe, operator status preserved);
  backfill CLI (`forecast crux backfill`, dry-run found 203 candidates); `pre_mortem` is a
  required reasoning method only in strict. **No hook rule touches cruxes; no crux signal
  exists in `HookContext` or the DSL.**
- **Gap:** a high-impact commit can carry zero registered cruxes (60/63 do — only 4 questions
  have any crux rows). The promotion machinery fills the table only when a panel runs and
  only going forward; nothing requires the commit to be crux-covered.
- **Signal:** `crux_count: int` — one indexed COUNT on `question_cruxes` (the
  `idx_question_cruxes_question` index makes this free) in both context builders; metadata
  escape `crux_skip_reason`. New DSL signal `cruxes.count` (number).
- **Rule:** `crux_named` · `REASONING` · weight 8.0 · applies: live, modeled,
  **high-impact** · exploratory OFF / standard **WARN → ERROR one cycle later** / strict
  ERROR. Check: `crux_count >= 1` OR `crux_skip_reason` recorded. In-flow this is nearly
  free: a high-impact commit already requires a panel (`require_panel` ERROR), the panel
  auto-promotes its cruxes before the commit reaches the gate, so the rule binds only the
  panel-skipped path and pre-promotion legacy questions — exactly the ones that should
  explain themselves.
- **Remediation message:**
  > "high-impact forecast has no registered crux: nothing on the question names the variable
  > that would most change this call. Run the panel (its cruxes auto-promote), promote them
  > with `forecast crux backfill --apply`, or record crux_skip_reason explaining why no
  > single crux exists. change_my_mind prose is not a tracked crux — a crux row is watchable,
  > statusable, and survives the next re-forecast."
  Remediation: agentic `run_panel`.
- **Test:** high-impact commit with 0 crux rows + no skip → fails; after
  `promote_panel_cruxes` → passes; medium impact never applies; DSL `cruxes.count` usable in
  a user rule.
- **Live fail count:** strict reading (crux rows only): **60 / 63** high-impact; lenient
  proxy (crux rows OR change_my_mind present): **14 / 63**. Running
  `forecast crux backfill --apply` (203 candidates ready) before the flip collapses most of
  the 60 — do the backfill as part of P3 migration.

### G8 · Market-anchor universality (the deviation-ledger path) — **P3**

- **Exists (strong, but sealed inside the quorum job):** full blind→reconcile discipline —
  phase-1 prompts built with `market_anchor=None` (`quorum.py:1926-1939`), reconcile block
  demanding a named edge past `threshold_pp` (`quorum.py:491`), judge
  `market_deviation_justification` (`quorum.py:541-599`), commit-time log-odds pull
  `apply_market_anchor_discipline` (`quorum.py:1705`), provenance
  (`blind_pool`/`reconciled_pool`/`market_anchor` annotation on the panel run), and the
  pre-registered `deviation_bets` ledger + resolution scoring + edge report
  (`ledger/deviation_bets.py`). Anchor detection: `extract_market_anchor`
  (`jobs/types/quorum.py:451`) — binary-only, component source prefixes
  `{polymarket, kalshi, manifold, metaculus, market}` else `baseline_comparisons`.
- **Gap:** all of it is a *quorum-job courtesy*, not a commit invariant. `HookContext` has no
  market fields; no rule requires that a question with a live market anchor its commit; and
  the proof is on the books: **`deviation_bets` has 0 rows ever** while 7 live questions
  watch market sources. A commit path that skips the quorum job (direct agent commit, panel
  instead of quorum) silently ignores the market.
- **Signal (cheap, from data the commit already touches or one indexed read):**
  - `has_linked_market: bool` — an `ensemble_components` row whose source slug starts with a
    market prefix (in-memory, the components are in scope), OR an active watched source
    matching the prefixes (the `list_watched_sources` call already made for
    `no_watched_sources`), OR a `baseline_comparisons` market row (one indexed read).
  - `market_comparison_recorded: bool` — the linked panel run's `market_anchor` annotation
    carries a non-null `market_price` (the run is already fetched once for the quorum
    signals), OR new snapshot metadata `market_comparison = {price, deviation_pp,
    justification?}` stamped by the committer, OR `market_skip_reason`.
  - New DSL signals `market.linked`, `market.comparison_recorded`.
- **Rule:** `market_anchor_engaged` · `QUORUM` · weight 10.0 · applies: live, modeled,
  `has_linked_market` · exploratory OFF / standard **WARN → ERROR for high-impact after the
  deviation ledger accrues its first scored cohort** / strict ERROR. Check:
  `market_comparison_recorded`. Note the rule requires *engagement* (record the price and,
  past threshold, the named edge), never *agreement* — the soul's anti-market-echo stance and
  the blind phase are untouched; the Live-Edge finding (agent manufactures independent
  signal) is the reason to record the deviation, not suppress it.
- **Remediation message:**
  > "this question has a live market ({source}) but the commit records no comparison against
  > it. Run the quorum (its blind-then-reconcile phase records the anchor, the deviation, and
  > the named edge automatically), or stamp metadata.market_comparison = {price,
  > deviation_pp, justification} — a deviation past {threshold}pp with a named edge becomes a
  > pre-registered deviation bet the ledger scores at resolution. Disagreeing with the market
  > is fine; not knowing you disagree is not."
  Remediation: agentic `run_quorum`.
- **Test:** commit with a polymarket component + no comparison → warns; quorum-linked commit
  (annotation present) → passes; `market_skip_reason` passes; no market → not applicable;
  non-binary share board with a market watched source still applies (engagement is
  outcome-type-agnostic even though the *pull* stays binary-only).
- **Live fail count:** **6 / 7** market-watched live questions record no comparison;
  0 deviation bets ever recorded.

---

## 4. Cross-cutting fixes (shipped inside the phases)

1. **`_sharpness` pp-scale bug** (`core.py:10084`) — normalize share dicts; unit-pin Clacton
   at 0.67. (P1, one-liner + test.)
2. **Residual matcher** — prefix/classification matching in `OutcomePath.is_residual` so
   "Other official candidates" is a residual. (P1.)
3. **`HookContext` additions** — `is_candidate_share`, `share_named_unanchored(+mass)`,
   `candidate_interval_coverage`, `candidate_intervals_coherent`, `crux_count`,
   `cadence_overdue_ratio`, `has_linked_market`, `market_comparison_recorded` — populated in
   BOTH builders (`signals.py:build_commit_context` + `build_context_from_ledger`), commit
   path fed from values `create_snapshot` already has (the Wave-3 discipline: assemble once,
   no IO in checks). Every new field defaults to the PASSING state so a context that cannot
   compute it never false-fires (the `readiness_score=None` precedent).
4. **DSL vocabulary** — expose the new signals (`tail.named_unanchored_mass`,
   `intervals.candidate_coverage`, `cruxes.count`, `market.linked`,
   `market.comparison_recorded`, `cadence.overdue_ratio`) so lessons can compile against
   them; new lesson templates `require_outcome_anchor` and `require_market_engagement` in
   `lesson_templates.py` so a future miss auto-arms these without hand-authoring. (P3.)
5. **`applies_to` unknown-key hardening** — `validate_rule` does not police `applies_to`
   keys; a hand-written `question_type:` filter silently matches everything. Add a WARN
   issue listing the four valid keys (`origin/impact/domain/outcome_type`). (P3, closes the
   documented silent-kill gotcha at the author-time layer.)
6. **Thresholds registry** — add `named_outcome_anchor_share` (0.10),
   `interval_median_tolerance_pp` (2.0), `cadence_grace_ratio` (1.5); all per-question
   tunable via the existing settings modal, `is_looser` direction set so the TUI flags lax
   overrides.

---

## 5. Default-ON strategy

**Land as ERROR immediately** (blocks nothing on the books today, or is a structural
bug-catcher with an autofix/exploratory relief valve):

| rule | why immediate |
|---|---|
| `require_tail_base_rates` | fires only on future commits of tail-carrying boards — the Clacton class is exactly what must never pass again; 19 boards hit it at next re-forecast, which is the correct moment to collect the anchor |
| `candidate_intervals_coherent` | 0 live failures; same class as `uncertainty_well_formed` |
| G6 coherence extensions | 0 live failures; rides existing ERROR rules + autofix |
| G3 first-commit anchor tier | 0 retroactive failures (new questions only); the brick vector was re-commits, which stay un-gated at ERROR |

**WARN-first, then promote** (the `require_outside_view_anchor` precedent: land WARN, read
the observed fire rate off the adherence scorecard for one review cycle (~1 week of the
weekly default cadence), then promote in a small commit that cites the numbers):

| rule | promote to | precondition |
|---|---|---|
| `candidate_intervals_present` | ERROR (standard) | fire rate confirms the protocol nudge + quorum elicitation get compliance up; `no_interval_reason` escape verified in-flow |
| `crux_named` | ERROR (standard, high-impact scope) | `forecast crux backfill --apply` run (203 candidates); auto-promotion observed filling new panels |
| `market_anchor_engaged` | ERROR for high-impact | first scored deviation-bet cohort exists (the edge report needs ≥10) |
| `outside_view_refresh` | stays WARN | its job is visibility; promotion would re-create the has_prior brick |
| `update_cadence_honored` | ERROR in strict only | sweep-side; "ERROR" means red badge + alert priority, commits are never touched |
| `granularity_disciplined` | never | hard-gating precision teaches fabricated precision |

**Non-negotiables preserved:** exploratory origin stays the universal relief valve (never
scored, never blocked); programmatic paths keep autofix + escalation instead of blocks; the
kill-switch `FORECAST_DISABLE_HOOK_BLOCKING` still disables the blocking pass wholesale; all
new rules are ordinary builtins, overridable per-question — except that promotions land in
the `standard` profile itself, so silence is strictness, and loosening requires a visible,
`is_looser`-flagged override.

**Migration for the open book (387 active; 175 live-origin currents):** gates bind at the
NEXT commit, never retroactively — the ledger is untouched. The drain is the existing
machinery: the weekly scheduled reviews + the autonomous cycle re-forecast on cadence, so
within roughly one cadence cycle every live question passes through the new gates with the
agent (not the operator) doing the remediation, teaching messages in hand. One-shot assists
before the P3 promotions: crux backfill (CLI exists), a `forecast lint --by-rule` pass to
print the per-rule debt table (§7), and the G1/G2 debt is worked naturally by the 19 share
boards' next quorum cycle.

---

## 6. Migration reality — the live counts (read-only, 2026-07-08)

Denominators: 387 active questions; 380 with a current snapshot; **175 live-origin** (205
`market_nightly` arms are out of scope for live gates); 94 binary; 19 candidate-share;
63 high-impact; 7 with watched market sources.

| proposed gate | would fail today | blocks when |
|---|---|---|
| G1 `require_tail_base_rates` | **19/19** share boards (incl. Clacton) | next commit of each |
| G2 `candidate_intervals_present` | **18/19** | next commit (WARN first) |
| G2 `candidate_intervals_coherent` | **0** | — |
| G3 first-commit anchor (ERROR) | **0** retroactive | new questions only |
| G3 `outside_view_refresh` (WARN) | **93/175** questions with zero reference classes (171/175 snapshots link none) | never blocks |
| G4 `granularity_disciplined` | **≤16/94** binaries (0.05-multiples; 2 at exactly 0.5) | never blocks |
| G5 `update_cadence_honored` | **44/175** past cadence×1.5 | never blocks commits (badge+alert) |
| G6 coherence extensions | **0/175** | next commit |
| G7 `crux_named` | **60/63** high-impact (14/63 under the change_my_mind proxy); collapses after crux backfill | next commit (WARN first) |
| G8 `market_anchor_engaged` | **6/7** market-watched; `deviation_bets` rows ever: **0** | next commit (WARN first) |

Honest reading: the WARN debt is large (93 anchor-less questions, 44 stale) — that is the
point. It becomes a visible, per-rule number on the doctor scorecard that trends to zero via
the autonomous cycle, instead of an invisible norm.

---

## 7. Anti-regression — how this can't silently rot

1. **The Clacton canary** — a permanent fixture test reconstructing `fs_526baa283165`'s
   commit context; asserts `SaturationBlocked` naming Binface under the standard profile.
   The pass-when-it-shouldn't class gets a pinned regression the same way the byte-identical
   legacy messages did.
2. **Profile-pin test** — `tests/forecasting/test_profile_pins.py` asserts the exact
   severity map of the `standard` profile (all 27+new rules). Today only `lesson:*` rules
   resist demotion; a refactor could silently drop `require_tail_base_rates` to WARN. The
   pin makes any severity change a deliberate, reviewed diff.
3. **Docgen staleness gate** — new rules must appear in `docs/reference/hooks-rules.md`
   (`python -m scripts.docgen --check` already fails CI on drift).
4. **Doctor adherence scorecard** (the operator's glanceable trust surface) — extend
   `finish_sweep`/doctor to tally `{rule_id: {checked, passed, failed_warn, failed_block}}`
   across active questions from the STORED `metadata['saturation']` verdicts (no recompute,
   no schema change — confirmed feasible against `sweep.py:85` + `alerts.py:292`), surfaced
   as `forecast lint --by-rule` and a `doctor` section with trend arrows. The lazy operator's
   whole check becomes: the failed_block column is zero and the failed_warn columns are
   falling.
5. **Both context builders or it didn't happen** — every new signal lands in
   `build_commit_context` AND `build_context_from_ledger` with a shared helper (the
   quorum-signals pattern), plus a parity test, so lint/sweep/doctor can never disagree with
   the commit gate.
6. **E2E journeys** — the stale-rerun e2e (the one that caught the has_prior brick) plus a
   new share-board journey (onboard → quorum → anchored commit) run in CI; the gates are
   only trustworthy if the happy path stays commit-able end to end.

---

## 8. Phasing

**P1 — the Clacton class (one focused arc):**
`hooks/distribution.py` (share extraction + interval parse + G6 checks), `tail_audit.py`
(base_rate fields + residual matcher), `hooks/spec.py` + `hooks/signals.py` (new fields),
`hooks/builtins.py` + `hooks/profiles.py` (G1 ERROR, G2 coherence ERROR, G2 presence WARN),
`ledger/snapshots.py` (stamp tail_audit for share payloads; `no_interval_reason` /
`outcome_paths` base-rate plumbing), `ledger/core.py` (`_sharpness` fix),
`hooks/thresholds.py` (2 new keys), tests incl. the Clacton canary, docgen. Exit: the
canary blocks; all existing tests green; the 19 boards re-lint with visible G1/G2 verdicts.

**P2 — intervals complete:** whisker glyphs (`forecastCharts.ts`), quorum share-vector
interval elicitation (`quorum.py`), resolution interval-coverage scoring
(`ledger/scoring.py`), stale comments deleted, `candidate_intervals_present` promoted to
ERROR with the observed fire rate cited.

**P3 — the rest of the lattice:** G3 two-tier anchor, G4 granularity + G5 cadence rule +
alert reason, G7 crux rule + backfill --apply + DSL signal, G8 market fields + rule + lesson
templates, DSL/`applies_to` hardening, doctor `--by-rule` scorecard + profile-pin test,
then the scheduled promotions (§5) as their preconditions land.

---

## 9. Honest costs

- **Next-commit friction on share boards is real and intended:** all 19 will block at G1
  until each named tail is anchored or compressed — roughly one research call per named
  candidate, done by the agent in-flow with the teaching message. That is the practice.
- **First-commit anchor (G3) adds one `add_reference_class` call to every new question** —
  the cheapest possible moment, and `research_adequate` already asks for it softly.
- **WARN volume rises sharply at first** (93 + 44 + 60 across G3/G5/G7). Without the §7
  scorecard this would be noise; the scorecard is what converts it into a burn-down. Ship
  the scorecard in P3 *before* the promotions, and run the crux backfill first.
- **The gates bind the agent path only** (`enforce_resolved_hooks`): raw `create_snapshot`
  callers and programmatic autofix paths stay lenient by design, covered by observe-mode +
  escalation. That is the existing, deliberate trust boundary — this plan widens what is
  enforced, not who.
- **What this plan does not do:** no payload schema change (nested share dicts stay
  incompatible with the validator and scorers — confirmed), no new inline gates, no
  retroactive re-scoring, no hard gate on precision or on disagreeing with markets.
