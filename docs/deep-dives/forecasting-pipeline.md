# Deep dive: the commit pipeline

How a belief becomes a durable, scoreable snapshot, in full mechanical detail.
This goes deeper than [forecasting-methodology.md](../forecasting-methodology.md)
(the desk-process overview) and [architecture.md](../architecture.md) (Arc D, the
ledger). Read those first; this page is the mechanism under the "commit gate" box
in the methodology diagram, and the exhaustive rule table lives in the generated
[reference/hooks-rules.md](../reference/hooks-rules.md) — this page explains what
*fires* each rule and in what order, not just what it checks.

The whole commit path is one function: `create_snapshot` in
`forecasting/ledger/snapshots.py` (a ~870-line gated body, delegated from the
`ForecastLedger` façade in `core.py`). Everything below happens inside it, in the
order shown.

---

## 0. Before the snapshot: the question must be scoreable

A snapshot is always *about* a question, and a question is refused unless it is
scoreable. Two layers enforce this.

**The staging object** (`forecasting/question_spec.py`, `QuestionSpec`) is the
plan-before-commit surface the agent fills in during onboarding — the forecasting
analogue of a clarify loop. `QuestionSpec.validate()` returns a list of
`SpecIssue`s at three severities:

- `error` — refuses to commit (empty/generic title, vague/placeholder criteria
  (`tbd`/`unclear`/…), criteria under 5 words, bad outcome space, numeric/
  distribution with no units, duplicate categorical choices, out-of-range
  base rates, a trigger operator with no numeric threshold, a malformed
  auto-resolver rule).
- `gap` — blocks *convergence* (readiness) but not creation: no close time, no
  decision owner, no action threshold, no update triggers.
- `warn` — advisory: no watched sources means re-runs have nothing to refresh.

`spec_quality()` folds those into a 0-100 score (start at 100, subtract 25 per
error / 8 per gap / 3 per warn). `infer_close_time()` reads free text for a
horizon phrase ("Q4 2026", "by September 2026", "next 12 months", "EOY") and
proposes a concrete ISO deadline, never fabricating precision (a bare ambiguous
month like "may"/"march" is ignored without a year). `apply_recommended_defaults`
turns the ~8-question onboarding interrogation into one pass for a lazy prompter,
but conservatively: free-text errors (criteria, triggers) are left to surface and
block.

`QuestionSpec.commit()` fans out — question + watched sources + reference classes
+ decision card + optional auto-resolver rule + a scheduled review + the default
nightly cron — all inside `allow_ledger_writes(reason="question_spec.commit")`
(see the write gate below). A question is thus *born* with sources to refresh, a
review cadence, and (optionally) a rule that can propose its own resolution.

**The ledger's own hard gate** (`_scoreability_issues`, mirrored by the spec's
`_VAGUE_MARKERS` / `_BARE_CRITERIA` / `_GENERIC_TITLES`) is the backstop: even a
direct `create_question` call refuses an unscoreable ask.

---

## 1. The write gate: who is even allowed to write a forecast

Before any gate battery runs, the ledger answers a different question: *is this
writer allowed to produce a forecast at all?* The desk agent has, in the past,
fabricated forecasts by scripting `ForecastLedger` directly — importing it and
calling `create_snapshot` / `create_question` / `record_panel_run` (or raw
`INSERT` via `_connect()`) from an ad-hoc script, bypassing every calibration/
panel/evidence gate. The write gate (`forecasting/ledger/gate.py`) closes that
hole with two layers:

1. **Method-level** (`_enforce_write_gate`) — each of the three forecast-producing
   methods calls it first; outside a recognised commit context it raises
   `ForecastingError`.
2. **Connection-level SQLite authorizer** (`_ledger_write_authorizer`, installed
   by `_connect`) — the real backstop. A raw `led._connect().execute("INSERT INTO
   forecast_snapshots …")` is denied `SQLITE_DENY` at *query* time, because method-
   name gating alone is trivially side-stepped by grabbing a connection.

```
                 write attempt on a gated table
                          │
             action == INSERT ?  ──no──▶ SQLITE_OK  (reads, DDL, UPDATE/DELETE,
                          │yes                        PRAGMA all pass — resolve,
             table ∈ GATED_LEDGER_TABLES ? ──no──▶ OK   config edits, migrations)
                          │yes
             commit context active (contextvar) ? ──yes──▶ OK
                          │no
             FORECAST_GATE_DIRECT_WRITES == "on" ? ──no──▶ OK (warn/off)
                          │yes
                      SQLITE_DENY
```

- **Gated tables** (`GATED_LEDGER_TABLES`): `forecast_questions`,
  `forecast_snapshots`, `panel_runs`, `watched_sources`. Only `INSERT` (row
  *creation*) is gated — the three forecast-producing methods are exactly the
  row-creators. `UPDATE`/`DELETE` stay open because many legitimate ops touch
  these tables outside a commit (resolving, editing config/title, setting
  `current_forecast_id`, thesis re-aggregation). Reads are *never* gated so
  audits/migrations script freely.
- **The context** is opened by `allow_ledger_writes()` (a re-entrant context
  manager) or the `allow_ledger_writes_decorator`. Legitimate writers — the
  forecast tool's commit flow, market-nightly + cron jobs, the autonomous cycle,
  schema migrations, the CLI forecast commands, `QuestionSpec.commit` — open it.
  The flag is a `contextvars.ContextVar`, so a gateway thread-pool worker and an
  asyncio worker each see their own state.
- **Mode** is `FORECAST_GATE_DIRECT_WRITES`: `on` (default, refuse) / `warn`
  (allow + log, a doctor signal) / `off` (legacy no-op). Unknown values fail safe
  to `on`.

---

## 2. The gate battery inside `create_snapshot`

Once a writer is authorised, the snapshot runs a fixed sequence of checks. Two
things run in parallel throughout: the **inline gates** (the byte-identical legacy
gates that own their rules, first-failing-wins) and the **hook engine** (the
config-resolved framework that scores saturation and enforces the rules with *no*
inline gate). They are deduplicated by rule id so nothing is evaluated as blocking
twice.

### The inline gates, in evaluation order

Each raises `single_block(rule_id, message, action=…)` — a `SaturationBlocked`
(subclass of `ValidationError`) carrying a one-verdict report, whose message is
**byte-identical** to the legacy string (the test suite asserts on these
substrings). All key on `forecast_origin == "live"`; an `exploratory` snapshot
sets `calibration_eligible = False` and skips every formality (it is scratchpad
thinking, never scored).

1. **`forecast_origin` valid** and payload validated against the outcome space;
   non-empty rationale; `confidence ∈ [0,1]`; `calibration_weight ≥ 0`.
2. **`require_structured_reasoning`** — `reasons_up` / `reasons_down` /
   `change_my_mind` all present.
3. **`require_components`** — non-empty `ensemble_components` (the pooled drivers:
   base rate, mechanism, market/crowd, case-specific factors).
4. **`require_fresh_evidence`** (re-run discipline) — only fires for a live
   *re-run* (a prior snapshot exists) that did **not** `acknowledge_stale_evidence`.
   "Fresh" is measured tie-proof by comparing `evidence_count_at_commit` on the
   prior snapshot's metadata (timestamp fallback for older snapshots). Escape
   hatches: `forecast refresh <id>`, per-driver import, `--ack-stale-evidence`, or
   `forecast_origin='exploratory'`.
5. **`require_decision_readiness`** — the decision card has no missing fields
   (`decision_owner`, `action_threshold`, `update_triggers`).
6. **`require_panel`** — a high-impact **or** re-committed live forecast needs a
   linked panel run (`panel_run_ref`) or a recorded `panel_skipped_reason`. A
   first-forecast panel on a lower-impact question is only *recommended*
   (stamped `panel_recommended` in metadata), never blocked. Gating comes from
   `forecasting.panel.should_run_panel` (high impact, or no prior snapshot); a
   re-commit binds the panel just like high impact because it is the highest-risk
   path for silently inheriting the prior's biases.
7. **`require_citations`** — at least one of evidence/model/reference/source/
   assumption/lesson refs.
8. **Categorical tail audit** — `forecasting.tail_audit.audit_outcomes` routes
   every material outcome through a named mechanism; the audit is *always*
   recorded in `metadata['tail_audit']`, and `require_outcome_paths` blocks a live
   categorical with unearned tail mass on no-path outcomes.
9. **Stale-evidence-days acknowledgement** — a plain `ValidationError` (not a
   hook) when `stale_evidence_days` finds stale refs unacknowledged.
10. **Scoped-ref validation** — assumptions / reference classes / model runs must
    belong to this question; calibration-lesson refs must be active + non-invalidated.
11. **`style_clean`** — the rationale prose must be house-clean (no em-dashes /
    formatting). The interactive agent path **blocks** (rewrite to conform);
    programmatic system paths pass `style_autofix=True` and mechanically clean via
    `sanitize_writeup_text`; config can downgrade it to warn/off.
12. **Distribution structure** (`output_renderable` / `uncertainty_well_formed`) —
    a live distribution must be renderable + well-formed; the agent path blocks,
    programmatic paths pass `distribution_autofix=True`. See §6.

### The resolved-policy blocking pass (the non-inline builtins)

After the inline gates, a second pass evaluates the built-in rules that have **no
inline gate** — `require_evidence`, `require_outside_view_anchor`,
`quorum_*`, `tails_justified`, `reasoning_composition`, `research_adequate`,
`calibration_bias_applied`, `confidence_committed`, `lessons_applied`,
`terminal_calibration_applied`, `thesis_aggregate_fresh`, `uncertainty_width_sane`
— under the fully **resolved** severities (profile + impact/origin scaling +
overrides, §3). This is what makes `require_evidence` (ERROR by default) a real
floor and lets the `strict` profile actually block.

Scope (all must hold): `forecast_origin == "live"`; `enforce_resolved_hooks=True`
(the opt-in the agent's `update_forecast` sets — direct callers, seeds, migrations
stay lenient so a raw `create_snapshot` never retroactively hard-blocks); neither
autofix flag set (the programmatic exemption); and the kill-switch
`FORECAST_DISABLE_HOOK_BLOCKING` unset. The block is computed inside the fail-open
`try` (`run_hooks` returns a report, never raises) and *raised outside* it so
`SaturationBlocked` escapes the observe guard.

### The user-rule + compiled-lesson pass

When the desk has authored custom rules **or** an active in-scope calibration
lesson carries a compiled `rule`, `run_hooks` evaluates them against the candidate
context. A failing ERROR-severity user/lesson rule blocks. Fail-**open** on any
evaluation error (a buggy rule engine must never brick a commit), but a
legitimately-failing rule *does* block — that is the point. This is how a
**structural** lesson (not just a numeric bias) bites at commit; see the
[learning loop](learning-loop.md).

### Observe-mode scoring (always runs, never blocks)

Finally the full `SaturationReport` is computed and stamped into
`metadata['saturation']` — the 0-100 score, per-rule verdicts, blocking list, and
warnings. This is best-effort inside a fail-open `try`: observe-mode must never
break a commit.

---

## 3. The hook engine, profiles, and severity resolution

The engine (`forecasting/hooks/`) is a git-hook-style framework. A `SimpleRule`
bundles an id, a `Category`, a default `Severity`, a `weight`, a pure `check_fn`,
and an `applies_fn` scope predicate. The `HookContext` (a frozen dataclass) is
assembled **once** per commit so rules stay pure and cheap (no IO in `check`).
`Severity` is `OFF` (not evaluated) / `WARN` (scored + surfaced, no block) /
`ERROR` (scored + **blocks**).

**Scoring** (`run_hooks`): `score = 100 * (1 - failed_weight / applicable_weight)`
over every applicable non-OFF rule. `passed` iff no ERROR verdict failed. Per-rule
fail-**soft**: a throwing rule degrades to a non-passing WARN (never blocks) but
stays visible in `engine_errors`, so one buggy rule cannot silently disable the
whole batch.

**Severity resolution** (`resolve_severities`) precedence, highest wins:

```
per-question override  >  config override  >  profile (after impact + origin
scaling)  >  default profile
```

- **Profiles** (`forecasting/hooks/profiles.py`) are a strictness ladder:
  `exploratory-lenient` (everything advisory) → `standard` (the default,
  byte-equal to the pre-hooks enforcement) → `strict` (advisories promoted to
  blocking). `REASONING_REQUIRED` sets the required reasoning-method set + minimum
  distinct count per profile (standard: `outside_view` + `base_rate`, ≥3; strict
  adds `pre_mortem` + `disconfirmation`, ≥5).
- **Impact scaling** — a question's `impact` bumps the profile up/down the ladder
  via `scaled_profile` (config `impact_scaling.<impact>.delta`).
- **Origin scaling** — a hard floor: any non-live origin whose `origin_scaling` is
  `off` collapses every rule to WARN (mirrors the legacy `forecast_origin=="live"`
  guard).
- **The `lesson:*` override floor** — a compiled calibration-lesson rule enforces
  a learning the desk already paid for in a miss; it is **not** silently
  demotable by a per-question or global override (that would re-open the
  "acknowledge then ignore" hole at the config layer). Lesson rules keep their own
  declared severity.
- **Per-question thresholds** — `metadata['forecast_hooks']['thresholds']` lets a
  gate's floor (min perspectives, max width ratio, min sharpness, null-excess
  tolerance) be per-forecast; the gate reads `ctx.threshold(key)` first and falls
  back to the constant.

The 25 built-in rules, their categories, default severities, weights, and *what
they check* are the generated table in
[reference/hooks-rules.md](../reference/hooks-rules.md). The value this page adds
is the **`applies_fn` trigger** — the difference between "checks X" and "fires":
`require_panel`/`quorum_required` only apply when high-impact or re-committed;
`require_fresh_evidence` only on a live re-run without stale-ack;
`terminal_calibration_applied` only when a panel run is linked; `require_outcome_paths`/
`tails_justified` only on live categoricals; the distribution rules only on a live
continuous distribution; `thesis_aggregate_fresh` only on thesis/factor aggregates.
`_modeled` (live and *not* a thesis/factor aggregate) gates the LLM-forecast-quality
rules off deterministic aggregates, whose quality lives in their members + the
aggregation math.

---

## 4. Preview mode

`create_snapshot(..., preview=True)` runs every gate + observe scoring **identically
up to the first ledger write**, then returns a record instead of inserting. A gate
that would refuse surfaces as `{"preview": True, "would_commit": False, "blockers":
[...]}` rather than raising; a clean preview returns `{"would_commit": True,
"saturation": …, "probability_or_distribution": payload, "metadata": …}`. This
kills the commit-then-remediate churn a real batch audit surfaced — the caller
sees the score, advisories, and blockers, fixes them, and commits **once**. The
write gate is skipped (preview writes nothing; the connection authorizer is the
backstop against an accidental INSERT).

---

## 5. Provenance stamping

A commit that consumed context and discarded it cannot be audited from the record
itself. Several markers close that gap:

- **`panel_run_ref`** is stamped into `metadata['panel_run_ref']` (the panel that
  underwrote the commit) and the panel run is attached to the snapshot via
  `attach_panel_to_snapshot`.
- **`stale_evidence_reason`** / **`acknowledge_stale_evidence`** are recorded so a
  freshness bypass is auditable even when no reason was given (the WARN state).
- **`annotate_snapshot`** is the blessed post-commit provenance writer: it merges
  a small metadata patch (e.g. the auto-quorum started/skipped record) inside
  `allow_ledger_writes("annotate_snapshot")`, UPDATE-only, never touching the
  probability, rationale, or any gated field.
- **Quorum auto-run skip records** — `maybe_autorun_quorum` returns an auditable
  `{"skipped": True, "reason": …}` for a by-design decline ("panel attached",
  "origin not live", "quorum.default_enabled is off", "not auto-indicated"), so a
  *non-run* is on the record too, not just a run. See
  [quorum-and-panels.md](quorum-and-panels.md).
- **The templated-batch detector** (`detect_templated_batches`) flags clusters of
  recent live forecasts that share an identical structural skeleton — same
  `method` + `reasoning_methods` + a name-stripped rationale tail (digits and
  Capitalized tokens dropped, then SHA-1'd). That is the tell of a "one template ×
  N" batch (a script substituting a name into a fixed shell). It is **read-only, a
  heuristic flag for review, never a block** — a shared standardized footer can
  also cluster, so member titles let a human dismiss a false hit. It fingerprints
  only rationale tails with ≥6 skeleton words (too-thin prose is skipped).

---

## 6. Uncertainty bands

Continuous distributions are assessed by `assess_distribution`
(`forecasting/hooks/distribution.py`), which wraps the same
`dashboard._distribution_view` parser the Desk charts use — so the gate and the
chart agree on what is renderable.

- **Central-in-band invariant** — the central tendency (median, else mean) **must**
  lie inside its own widest band (ci90 preferred, else ci50). A point outside its
  band (the "disconnected-band" bug, e.g. mean 44.7 with ci90 [-4.7, 5]) is never a
  valid forecast; this was previously uncaught. Alongside it, `well_formed`
  requires ordered (`lo ≤ hi`), nested (ci50 inside ci90), finite, non-degenerate,
  in-bounds intervals; `renderable` requires a central tendency **and** ≥1 ordered
  interval.
- **Vote-share PMFs** — a candidate-share payload (≥2 named numeric shares summing
  to ~1 or ~100, keys not in the distribution-stat set) is recognised as a PMF and
  is **renderable as bars over candidates**, a categorical-style distribution, not
  a continuous band. This is what lets a vote-share forecast commit **live** (and
  engage its lessons) instead of being forced exploratory, which would bypass every
  gate.
- **Per-candidate intervals** — chosen but not yet built; a vote-share PMF today
  renders as bar shares, not per-candidate confidence intervals.
- **Autofix** — `autofix_distribution` mechanically repairs (reorder inverted,
  clamp to bounds, nest ci50 inside ci90, derive a mean from the median) and writes
  back canonical `interval_50_*`/`interval_90_*` keys; a still-malformed remainder
  is recorded in `distribution_autofix_incomplete` rather than silently committed.

---

## 7. After the write: saturation reports, sweeps, write-ups

- **Programmatic escalation** — a programmatic commit (refresh / aggregate /
  autopilot, the lenient autofix paths) whose recorded saturation is under the
  sweep bar escalates the same deduped WARN under-saturation alert the scheduled
  sweep raises (`enqueue_saturation_alert`), so leniency stays but under-saturation
  becomes visible. Disable with `FORECAST_DISABLE_SATURATION_ESCALATION`.
- **The finish sweep** (`forecasting/hooks/sweep.py`) re-lints each touched
  forecast **read-only** at the end of a session/pipeline run and summarises the
  under-saturated ones. `lint_forecast` runs the engine against a question's
  *current* snapshot (freshness re-run discipline treated as satisfied — a lint
  assesses the stored forecast, not the act of re-committing). The default under-
  saturation bar is 60/100 (`sweep_alert_threshold`, config-overridable). The sweep
  is read-only: it surfaces gaps, it never persists anything under-saturated — the
  `create_snapshot` chokepoint remains the only writer.
- **Analyst write-ups** (`forecasting/writeup.py`) — a `brief` is generated on
  every probability-bearing update (and evidence-only thinking updates), a
  `retrospective` once the question resolves, both in a FiveThirtyEight desk voice
  over four fixed angles (how it feels / thinks / looking-for-next / be-aware).
  Generation is **always best-effort** (`generate_writeup` returns `None` on any
  failure; a note can never roll back a snapshot). `sanitize_writeup_text` strips
  banned dashes mandatorily (models leak them despite the prompt) — the same
  function the `style_clean` gate uses. A failing categorical tail audit is injected
  into the brief so the note *flags* unearned tail mass instead of contradicting the
  audit the desk shows.

---

## The commit, end to end

```
 update_forecast (agent)  /  forecast update (CLI)  /  refresh / cron / cycle
        │                        (each opens allow_ledger_writes)
        ▼
 create_snapshot(...)  ── preview=True? ──▶ run gates, return {would_commit,…}, no write
        │ (preview=False)
        ▼
 _enforce_write_gate("create_snapshot")          ← method + SQLite authorizer
        │
        ▼   forecast_origin=="live"?  ──exploratory──▶ calibration_eligible=False, skip formalities
   ┌────┴─────────────── inline gates (first-failing-wins, byte-identical) ───────────┐
   │ structured_reasoning → components → fresh_evidence → decision_readiness → panel  │
   │ → citations → tail-audit(require_outcome_paths) → stale-days → scoped-refs        │
   │ → style_clean → distribution(output_renderable / uncertainty_well_formed)         │
   └────┬──────────────────────────────────────────────────────────────────────────────┘
        │            each failure ▶ SaturationBlocked (ValidationError), message byte-identical
        ▼
   user-rule + compiled lesson:* pass  ── ERROR fail ▶ SaturationBlocked  (fail-open on error)
        ▼
   resolved-policy blocking pass (non-inline builtins, if enforce_resolved_hooks)
        ▼   staged, RAISED outside the fail-open try
   observe-mode SaturationReport ▶ metadata['saturation']   (best-effort, never blocks)
        ▼
   INSERT forecast_snapshots  +  UPDATE current_forecast_id
        ▼
   attach_panel_to_snapshot · cascade re-aggregate parents · record_lesson_applications
        ▼
   (programmatic) enqueue_saturation_alert if under-saturated
        ▼
   return ForecastSnapshot
```

---

## Honest limits

- **Observe-mode is best-effort.** The full saturation score is computed inside a
  fail-open `try`; a failure logs and skips, so a recorded `saturation` can be
  absent. The inline gates and the resolved-policy block are what actually enforce.
- **`enforce_resolved_hooks` is opt-in.** Only the agent's `update_forecast`
  path enforces the resolved policy for non-inline builtins; a raw
  `create_snapshot` (seeds, migrations, internal recompute) stays observe-only, so
  `require_evidence` and the strict profile do not retroactively hard-block those.
- **Many rules are WARN, not ERROR.** In `standard`, only structured reasoning,
  components, fresh evidence, panel, evidence-floor, style, and the two structural
  output rules block. Citations, outside-view anchor, quorum participation/judged,
  tails-justified, reasoning composition, research adequacy, lessons applied,
  terminal calibration, and thesis freshness are advisory by default.
- **The templated-batch detector and the finish sweep never block** — both are
  review/observability surfaces. A shared footer can trip the batch heuristic.
- **Per-candidate vote-share intervals are chosen but unbuilt.**
- **The write gate can be turned off** (`FORECAST_GATE_DIRECT_WRITES=off`) and
  observes only in `warn` mode; `off` restores the legacy fabricate-by-script hole.

---

## Sources

Derived from and verified against:

- `forecasting/ledger/snapshots.py` — `create_snapshot` (the full gate battery,
  preview, provenance, observe-mode), `annotate_snapshot`, `_validate_evidence_refs`,
  `_committed_winner_prob`, `_machine_scoreable_payload`.
- `forecasting/ledger/gate.py` — `_ledger_write_authorizer`, `allow_ledger_writes`,
  `_enforce_write_gate`, `ledger_write_gate_mode`, `GATED_LEDGER_TABLES/WRITES`.
- `forecasting/ledger/core.py` — `create_snapshot` delegate + signature,
  `detect_templated_batches`, `resolve_question`.
- `forecasting/hooks/` — `spec.py` (`HookContext`, `Severity`, `Category`,
  `SimpleRule`, `SaturationReport`, `SaturationBlocked`, `single_block`),
  `builtins.py` (`BUILTIN_RULES`, `RULE_DOCS`, all 25 rules + applies predicates),
  `engine.py` (`run_hooks`, `resolve_severities`, `policy_from_require_flags`),
  `profiles.py` (ladder, `REASONING_REQUIRED`), `signals.py`
  (`build_commit_context`, `build_context_from_ledger`, `detect_style_offenders`),
  `sweep.py` (`finish_sweep`, `lint_forecast`, `sweep_alert_threshold`),
  `distribution.py` (`assess_distribution`, `autofix_distribution`), `__init__.py`.
- `forecasting/question_spec.py` — `QuestionSpec.validate/commit`, `spec_quality`,
  `infer_close_time`, `apply_recommended_defaults`, `suggest_resolution_rule`.
- `forecasting/writeup.py` — `write_brief`, `write_retrospective`,
  `generate_writeup`, `sanitize_writeup_text`, `tail_audit_summary`.
- `docs/reference/hooks-rules.md` — the generated rule table (source of truth
  `forecasting/hooks/builtins.py`).
