# Deep dive: the learning loop

This is the system's soul: the machinery that makes the desk more than a logger.
A forecast that never resolves teaches nothing; the loop only turns when questions
get resolved and scored, and the whole point is that a measured mistake becomes a
gate the next forecast must clear. This goes deeper than the "how to let it learn"
half of [forecasting-methodology.md](../forecasting-methodology.md); how the
compiled lessons enforce at commit is in
[forecasting-pipeline.md](forecasting-pipeline.md).

```
 resolve ─▶ auto-score (Brier / log / bucket / trend)
              │
              ▼
        synthesize_bias_lessons  (signed bias, FDR + ESS gated)
              │
        ┌─────┴──────────────┐
        ▼                    ▼
  numeric lesson       structural lesson
  (logit_scale…)       (compiled lesson:* rule)
        │                    │
        ▼                    ▼
  applied to next      enforced at commit
  live commit          (the gate battery)
        │                    │
        └────────┬───────────┘
                 ▼
        coverage audit (in-scope / applied / dormant)
                 ▼
        track-record weighting  ·  operator practice loop
```

---

## 1. Resolution → scoring

`resolve_question` (`forecasting/ledger/core.py`) records the resolution and, on a
**confirmed, criteria-satisfied, scoreable** resolution, auto-scores the current
snapshot (`auto_score=True` by default). A committed forecast therefore cannot
resolve without a Brier/log score — the loop closes automatically. Exploratory
scratchpad snapshots are never scored; scoring is idempotent so a later explicit
`score` is a no-op.

`score_snapshot` (`forecasting/ledger/scoring.py`) writes one `score_records` row:
`brier_score`, `log_score`, `proper_score` + `score_rule`, a `calibration_bucket`,
the horizon, domain, `forecast_origin`, and `calibration_eligible` / weight. A
live, calibration-eligible score also updates the question's domain error profile.
`calibration_summary` aggregates these into per-type stats, per-bucket mean Brier,
an overall mean, baseline comparisons, and **time-bucketed trend windows** — each
`{period, n, brier, sce}` over the scored points in that window (`_calibration_trend`).
Crucially, live / backtest / baseline strata are kept separate so a replay never
contaminates the real track record.

---

## 2. Auto bias-lesson synthesis on resolve

A fresh **live** score can shift the signed-bias picture, so `resolve_question`
re-synthesises the corrective lesson for the resolved question's scope family right
after auto-scoring. This is guarded three ways so a bulk backtest or a thin desk
pays nothing:

- **Live-only** — the synthesis measures the `forecast_origin="live"` stratum only,
  so firing it on a backtest/imported resolution would rescan the same live data
  for no new signal (pure waste, and the scan is O(live-scores)).
- **A cheap COUNT pre-gate** — the signed estimator emits nothing until a scope
  clears its ESS floor (12 domain / 20 global). A single `COUNT` of live scores in
  the domain skips the whole scan when the scope is obviously too thin. Count is a
  necessary condition (ESS ≤ count), so skipping below it can never suppress a
  lesson that would fire.
- **A debounce** — `_bias_synth_last` per scope, so rapid resolutions don't re-run
  the O(live-scores) synthesis repeatedly.

`synthesize_bias_lessons` scans the scope family (global + each domain with scores),
computes the global estimate first so domains shrink toward it (empirical Bayes),
applies Benjamini-Hochberg FDR across the whole family, then writes / activates /
leaves-tentative / retires each scope's lesson per `decide_disposition`. It is
best-effort — a synthesis hiccup never breaks the resolution.

### The signed-bias measurement (built not to teach over-biasing)

`forecasting/calibration_bias.py` is engineered, above all, **not** to teach the
model to hedge or to run away with itself. Every constant is a safeguard:

- **Signed Calibration Error on the P(yes) axis**, not a `max(p,1-p)` confidence
  fold. The naive fold mechanically manufactures over-confidence near 0.5 (a
  perfectly-calibrated 55% reads as over-confident), which would teach hedging.
  Instead each resolved binary scores `c_i = sign(p_yes - 0.5) · (p_yes - outcome)`,
  dropping a `_NEUTRAL_BAND` (0.05) around 0.5 where the leaned side is arbitrary.
  `SCE = weighted_mean(c_i)`; **SCE < 0 ⇒ under-confident**, **SCE > 0 ⇒
  over-confident**. Because each `c_i` is per-observation, the CI and the H0:SCE=0
  p-value are a plain weighted-mean test, and `|SCE| ≤ ECE` holds by the triangle
  inequality.
- **Fail-safe under thin/noisy data** — every threshold is in **Kish effective
  sample size** (so recency decay cannot silently defeat a raw-n gate). Below the
  floor the verdict is `insufficient_evidence` and nothing is emitted. A scope must
  clear its CI (exclude 0 by a margin), survive the H0 p-test, **and** survive
  Benjamini-Hochberg FDR across the family — scanning a dozen domains at 95% would
  otherwise emit a spurious lesson roughly every other cycle.
- **Advisory by default, mechanical only on opt-in** — the lesson is bounded,
  shape-specific, symmetric *text* the agent reasons about; the numeric nudge is
  empty unless `enable_mechanical`. When enabled the nudge is a base-rate-neutral
  `logit_scale` (sharpen > 1 / flatten < 1 around 0.5, **never** an additive shift
  that would chase the realized yes/no base rate), empirical-Bayes shrunk, damped by
  a partial gain (0.5), magnitude-capped (0.20), and hysteretically dead-banded
  (`_MECH_DEADBAND_ENTER`/`EXIT`, so a correction is never abruptly withdrawn into a
  limit cycle).
- **Convergence is monitored, not proved** — the actuator is a language model
  reading prose, so "gain < 1 ⇒ contraction" does not hold. `decide_disposition`
  suppresses/demotes a lesson when `|SCE|` grew for two consecutive cycles or
  flipped sign against an active lesson (the overshoot/oscillation signature).
  Derivation runs on the **lesson-free stratum** (`lesson_active=False` observations
  excluded) so the loop never measures its own advice.

The disposition ladder: `none` (no detectable bias, or failed FDR — retire any
prior active lesson) → `suppressed` (trajectory diverging — retire + audit marker)
→ `tentative` (detectable but below the strong-activation gates) → `active`
(ESS ≥ 30 **and** |shrunk SCE| ≥ 0.08). Lessons never accumulate — a new one
supersedes the prior.

---

## 3. Lesson compilation → enforced `lesson:*` rules

A numeric bias nudges the next number; a **structural** lesson (a process rule)
must *bite* at commit. `forecasting/lesson_templates.py` is the auditable pattern
library that turns a lesson's intent into a hook `RuleSpec` **without anyone
hand-authoring a rule** (the lazy-operator pattern):

- **`tail_cap`** — compress unearned tail mass (`tails.null_excess ≤ 0.15`).
- **`born_scoreable`** — a vote-share forecast must carry numeric candidate shares
  keyed to the choices (`outcome.machine_scoreable is_true`).
- **`require_reference_class`** — attach an outside-view anchor
  (`reference_classes.count ≥ 1`).
- **`require_winner_backing`** — a >65% winner call needs a linked vote-share /
  derived model (`confidence.winner_prob ≤ 0.65` OR `links.derived_child_present`).

`resolve_enforcement_pattern` picks the lesson's explicit `enforcement_pattern`, or
infers one from its `process_rule` / text keywords (most-specific first:
scoreable → tail → winner → reference-class). `apply_lesson` (the CLI
`forecast lessons apply`) resolves the pattern, attaches the built rule to the
lesson's `recommended_adjustment['rule']`, and reports it — a lesson with no
recognised pattern **stays advisory, never silently no-ops**. Severity defaults to
**WARN** (observe-then-flip). At commit, `compile_lesson_rules` (called inside
`create_snapshot`) turns every active in-scope lesson carrying a `rule` into a
`SimpleRule` id-namespaced `lesson:<id>`, and — the security property — **force-
stamps its `applies_to` from the lesson's own scope**, never from author-supplied
`applies_to`, so a `domain:politics` lesson can only ever match politics forecasts
(no scope-widening attack). A rule that fails validation is skipped (a broken
lesson must never brick a commit).

> **Warning — the `lesson:*` override floor.** A compiled lesson rule is **not**
> demotable by a per-question or global config override (`resolve_severities` skips
> any `rid.startswith("lesson:")`). This is deliberate: the desk already paid for
> that learning in a miss, and a silent config demote would re-open the "acknowledge
> then ignore" hole. Lesson rules keep their own declared severity.

---

## 4. Retrieval — how a lesson finds a forecast

`active_lessons_for_question` (`forecasting/learning.py`) walks the scope family in
order: `global` → `domain` → each `topic` → each **`domain_topic`** (stored
colon-joined, e.g. `politics:nyc-primaries`, so a lesson scoped to a domain **and**
a topic matches a question carrying both) → `question_type` → the **canonical**
question type. Deduplicated by lesson id.

> **Warning — the `question_type` `applies_to` mismatch (a silent-kill gotcha).**
> A vote-share forecast has outcome type `distribution`, but the share-compression
> and scoreability lessons target the *sub-type* vote-share, not continuous
> distributions. Retrieval surfaces it as an extra `question_type:vote-share-
> distribution` scope (`_canonical_question_type`), and `lesson_scope_to_applies_to`
> maps that canonical name **back** to the real outcome type `distribution` when it
> force-stamps the compiled rule's `applies_to`. Miss either half and the retrieved
> lesson's compiled rule silently never matches the commit context's `outcome_type`
> — the lesson retrieves but never enforces. Continuous distributions never retrieve
> it (they carry no choices), so it never over-applies.

---

## 5. Bite, audit, apply

Two mechanisms make a lesson bite, plus an audit that proves it is actually biting:

**Applied to the next commit.** `apply_active_lesson_adjustments` attaches the
active lessons for a question and applies their supported numeric adjustments —
`probability_delta` (direct), `logit_shift` (additive in log-odds), and
`logit_scale` (the base-rate-neutral confidence rescale via the same `platt_scale`
kernel). The **raw** pre-adjustment probability is preserved on the audit trail
(`calibration_adjustment['raw_probability']`); `should_apply_active_lessons` makes
it default-**on for live commits only** (a live-derived correction folded into a
backtest would contaminate the very benchmark that grounds live-superforecasting
claims; those origins apply lessons only on explicit opt-in; exploratory is never
adjusted). `--no-use-active-lessons` opts out.

**The application audit.** `_audit_unapplied_lessons` counts active in-scope
**numeric** lessons the committed forecast did **not** actually apply — "applied"
means the committed number *net-moved* from the recorded raw payload, **not** that a
lesson ref was stapled on. Citation-stapling no longer satisfies the gate; an
in-scope lesson the agent simply ignored is counted unapplied, feeding the
`lessons_applied` (WARN) and `calibration_bias_applied` hook rules.
`_record_lesson_applications` then writes one `lesson_applications` coverage row per
active in-scope lesson at a successful commit (kind = rule / numeric / advisory;
applied 0/1 — a `rule` lesson that let the commit succeed is recorded applied, since
an ERROR-severity rule would otherwise have blocked).

**The coverage report.** `lesson_coverage` answers the honest question — *is this
learning actually being used?* — per active lesson: how often it has been in scope
since creation, how often applied, its application rate, last-seen, and whether it
is **dormant** (never encountered). A dormant or rarely-applied lesson is a review
trigger, not silently-trusted machinery. `calibration_correcting_lessons` layers
scope-aware retrieval on top so the desk can say which learning is adjusting the
numbers *here* and whether it is biting (`forecast lessons audit`).

---

## 6. Track-record feedback into weighting

The same resolved scores that drive lessons also drive **who gets a vote**. Panel
perspectives, ensemble components, and panelist models are each scored on their
measured Brier edge and mapped to an advisory weight (shrunk toward 1.0, minimum-
sample-gated, magnitude-clipped) so consistently-good sources count for more over
time. This is the feedback edge from the learning loop into the deliberation layer;
the mechanics — and the `component_track_record` vs `model_track_record` vs
`model_skill` distinction — are in
[quorum-and-panels.md](quorum-and-panels.md#4-track-record-weighting-s7--s75).
Weighting is always advisory and opt-in; a cold-start desk is equal-weighted.

---

## 7. The practice loop — the desk scores *you* too

The desk does not only grade itself. The operator practice loop (R2) records the
**operator's own** estimates in a table that is deliberately **not** forecast-
producing (so it never trips the write gate). Turn on practice mode
(`forecasting.practice.estimate_first: true`) and the agent asks for your
probability before revealing its own; `forecast drill --n 5` replays already-
resolved binaries and returns your Brier on the spot. On a confirmed resolution
`resolve_question` scores the operator's estimates against the same realized
outcome — fail-open, exactly like auto-score, and independent of the system's
scoreable flag. `forecast calibration --operator` then shows the operator's
reliability curve, trend, and how their Brier stacks up against the system's on the
same questions (`_operator_vs_system`).

---

## 8. Cross-pollination — related-forecast context, flag don't merge

A forecast should stay coherent with correlated ones without double-counting their
evidence. `related_forecast_views` surfaces the **world-views** of related / parent
/ child forecasts (auto-matched same-domain + explicitly linked via `forecast
link`) into the context packet (`forecasting/protocol.py`): their probability,
stance, headline, be-aware, and top reasons up/down. The discipline is **flag,
don't merge**:

- **World-views only.** A related forecast's *number and reasoning* inform this
  one; its **evidence is never folded in**.
- **Shared sources are flagged for independence** — "shares X with related
  forecasts; weigh as possibly non-independent, do not double-count."
- **Evidence-ownership warning** — a question with no watched sources of its own is
  told, explicitly, that a sibling's evidence does not cover it: collect evidence
  directly, never borrow a sibling's readings.

`build_cross_refs` records server-side provenance (which related forecasts informed
this one) in the snapshot's `metadata['cross_refs']['informed_by']`, so the
influence is auditable rather than invisible.

---

## 9. Path-driven methodology

The reasoning stance the loop rewards is baked into the prompts and the re-run
guidance. Panelists (and the quorum judge) are instructed to **anchor on the status
quo and the horizon**, reason along causal **paths** (named links, not vibes), and
forecast strictly from the **information frontier** — never using information they
could not have known as of the evidence cutoff, and treating any single number (a
market, a poll, a model) as a **prior to check, not the answer**. On a re-run the
context packet's guidance reinforces it: a re-run is not a retrieval — refresh
evidence first, treat the prior probability and its tails as a prior to re-check
(never a number to carry forward), and as the horizon shortens conviction should
generally rise and the distribution concentrate toward the path the evidence
supports rather than inherit the prior's hedge. The categorical tail audit is the
enforcement arm of "paths not vibes": mass on an outcome with no named path is
unearned.

---

## Honest limits

- **The loop only turns on resolved, scored, live questions.** No resolutions, no
  lessons; a backtest resolution deliberately synthesizes nothing.
- **Auto-synthesis is best-effort and heavily gated.** ESS floors (12 domain / 20
  global), FDR control, and a debounce mean an ordinary small desk emits nothing for
  a long time — by design (a spurious lesson is worse than none).
- **The mechanical numeric nudge is off by default.** A lesson ships as *advisory
  prose*; `enable_mechanical` (and a higher ESS floor of 60) is required before any
  `logit_scale` is emitted, and it is capped, shrunk, gained-down, and dead-banded.
- **Convergence is monitored, not guaranteed.** The actuator is an LLM reading
  prose; the trajectory guard suppresses a diverging lesson but cannot prove
  contraction.
- **`lessons_applied` and `calibration_bias_applied` are WARN by default** — an
  ignored numeric lesson surfaces but does not block on the `standard` profile.
- **Two silent-kill gotchas** documented above: a config override cannot demote a
  `lesson:*` rule (the override floor), and the vote-share `question_type` scope
  must map back to the real `distribution` outcome type or the compiled rule never
  matches.
- **Exploratory forecasts bypass the whole loop.** They set
  `calibration_eligible=False`, are never scored, never adjusted, and every hook
  keys on `forecast_origin=="live"` — so exploratory is the escape hatch from *both*
  the gate battery and the learning feedback.

---

## Sources

Derived from and verified against:

- `forecasting/ledger/core.py` — `resolve_question` (auto-score + the guarded auto-
  synthesis), `synthesize_bias_lessons`, `_apply_bias_disposition`, `apply_lesson`,
  `lesson_coverage`, `calibration_correcting_lessons`, `list_calibration_lessons`,
  the operator practice-loop tables.
- `forecasting/ledger/scoring.py` — `score_snapshot`, `score_question`,
  `calibration_summary`, `_calibration_trend`, `_audit_unapplied_lessons`,
  `_record_lesson_applications`, `_operator_vs_system`.
- `forecasting/calibration_bias.py` — `assess_bias`, `signed_calibration_error`,
  `decide_disposition`, `benjamini_hochberg`, `effective_sample_size`,
  `extremization_alpha_gate`, `diagnose_hedging`, all safeguard constants.
- `forecasting/learning.py` — `active_lessons_for_question`,
  `apply_active_lesson_adjustments`, `should_apply_active_lessons`,
  `compile_lesson_rules`, `lesson_scope_to_applies_to`, `_canonical_question_type`.
- `forecasting/lesson_templates.py` — `LESSON_ENFORCEMENT_PATTERNS`,
  `resolve_enforcement_pattern`, `build_lesson_rule`.
- `forecasting/hooks/engine.py` — `resolve_severities` (the `lesson:*` override
  floor, origin scaling).
- `forecasting/protocol.py` — the cross-pollination "Related Forecasts" context +
  independence/evidence-ownership flags, the re-run path-driven guidance.
- `forecasting/writeup.py` — the resolution retrospective (the honest self-grade).
