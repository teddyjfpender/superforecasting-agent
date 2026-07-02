---
name: forecast-onboard
description: "Curate a NEW forecast question with the user before committing it — propose a complete typed spec, ask only the gap-closing questions (with recommended defaults), then commit the whole setup (question + watched sources + reference classes + decision card) in one shot. Invoke when the user wants to start/track a new question, e.g. /forecast-onboard Will the Fed cut in September?"
version: 1.0.0
author: Superforecasting Agent
license: MIT
platforms: [linux, macos, windows]
aliases: [onboard, new-question, curate-forecast]
metadata:
  hermes:
    tags: [forecasting, onboarding, question, curation, clarify, watched-sources, superforecasting]
    category: forecasting
    related_skills: [forecasting-loop, forecast-rerun, path-driven-forecast]
---

# Onboard a new forecast question (curate, then commit)

The user wants to start tracking a new question. Do NOT silently call
`create_question` with guessed fields. Curate it WITH them first — like a plan
review — so the question is born scoreable AND with the sources, reference
classes, and decision card it needs. A question that leaves onboarding with
watched sources is one that re-runs can actually refresh (see
[forecast-rerun]); one without them perpetually hedges on stale evidence.

This is a **plan-before-commit** loop, single-threaded, on a typed `QuestionSpec`.

## 0. Fast path — a vague/casual ask? Accept the defaults, don't interrogate

Every clarification carries a recommended default, so a lazy one-liner ("track
whether the Fed cuts in September", "keep an eye on CPI") does **not** need an
eight-question interview. Pass `accept_defaults=true` to `propose_spec` /
`commit_spec`:

```
forecast_ledger commit_spec { spec: <your best-effort draft>, accept_defaults: true }
```

It auto-applies the first `(recommended)` choice of every gap/error clarification
(the S1-inferred `close_time`, `decision_owner=you`, action threshold ≥70%, the
binary outcome shape) into `spec.clarifications` and commits in **one shot**. Only
**error-severity** issues still surface and block — a genuinely unscoreable
title/criteria is refused just as strictly as on the slow path (nothing is
fabricated to slip past the gate). A `full`-`autonomy` spec implies
`accept_defaults` automatically.

The result carries an `applied_defaults` list. Echo it as a **single line**, e.g.
"created with these defaults — deadline 2026-09-30, owner you, act ≥70% — say the
word to change any", then proceed to run the first forecast (see the last
section). Reserve the full curation loop below for high-stakes questions or when
the user clearly wants to shape the spec themselves.

## 1. Draft the spec, then ask the gateway to structure it

From the user's prompt, infer a COMPLETE first draft: a specific title,
auditable resolution criteria (a measurable threshold + a source), the outcome
type, at least one watched source, at least one reference class with a base
rate, and a decision card. Then call:

```
forecast_ledger propose_spec { spec: <your draft QuestionSpec> }
```

It returns the normalized `spec`, the `issues` (error / gap / warn), and
`recommended_clarifications` — the exact questions to ask, in priority order,
each with a recommended default. You supply the content (you are the analyst);
the tool stays deterministic — it validates and tells you what is missing.

## 2. Clarify ONLY the true gaps — act, don't interrogate

Fire the `recommended_clarifications` as `clarify` prompts, but **only when the
field is genuinely ambiguous**. If the user's prompt already pins a field, keep
your draft value and skip that question (act_dont_ask). Each option you present
should carry a recommended default so the user can one-key accept. The priority
order the tool returns is:

1. **Outcome shape** — binary / numeric+units / categorical / distribution.
2. **Resolution criteria** — if too vague to score, get the measurable
   threshold + source (free text).
3. **Decision owner** — who acts on this.
4. **Action threshold** — at what probability the action changes.
5. **Update triggers** — the executable observation (source + operator +
   threshold) that forces a re-look.
6. **Evidence-gathering permission** — may you autonomously fetch evidence on
   each run, or is it manual-only? (Sets `allow_evidence_gathering`.)
7. **Watched sources by default** — propose concrete sources (markets, FRED,
   RSS) and confirm; this is what makes re-runs refreshable.
8. **Per-source confidence** — for any source the user is unsure about, capture
   a `reliability_prior` / `confidence_weight` so its evidence is weighted right.
9. **Panel default** — run a multi-model panel by default? (Sets
   `panel_by_default`.)
10. **Reference-class seed** — confirm a candidate base rate.

Patch the spec with each answer and append the Q+A to `spec.clarifications`.

## 3. Converge, confirm, commit

Stop clarifying when `propose_spec` reports no `error`-severity issues and the
decision-readiness gaps are closed (or the user explicitly waives one —
"track only / no threshold"). Surface a one-line confirmation of what will be
created ("3 watched sources, 1 reference class, evidence auto-fetch ON, panel
OFF"), then:

```
forecast_ledger commit_spec { spec: <finalized QuestionSpec> }
```

`commit_spec` refuses on any `error`-severity issue (returning the list, writing
nothing), so an underspecified question never lands. On success it creates the
question, registers the watched sources with their priors, seeds the reference
classes, and stashes the toggles under `metadata.onboarding` — which the run /
re-run paths read (evidence permission, panel default, per-source reliability).

## 4. After commit, run the first forecast — do not stop at a bare question

A committed question with no forecast is a dead entry, not a desk. The moment
`commit_spec` succeeds, keep going and produce the first live estimate — do not
hand back a bare "created question <id>" and wait to be asked again. Run the
opening pass of the loop end-to-end:

- **research** — pull the watched sources you just registered
  (`import_source_evidence` / `refresh_forecast`) and record timestamped evidence;
- **base_rate** — establish the outside view from the reference class(es) seeded
  at commit;
- **update** — pool the drivers into `ensemble_components` and commit the first
  live snapshot.

The one-call form is `forecast_ledger full_forecast { question_id: <id> }`, which
sequences research → base_rate → update for you; drive the stages individually
only when you need to intervene between them. Then hand back the number with its
decomposition, not just the question id. Continue into the full loop with the
[forecasting-loop] skill.

## Guardrails

- **Never commit on `error`s** (even with `accept_defaults` — the gate is
  identical). Repair via one scoped `clarify`, don't abort.
- **No watched sources is a `warn` you should fix**, not ignore — re-runs need
  something to refresh.
- **Honor the toggles afterward**: if `allow_evidence_gathering` is false, do
  not autonomously fetch on later runs; consume only evidence the user adds.
- CLI equivalents for humans: `forecast onboard "<question>"` to propose,
  `forecast onboard --spec spec.json --commit` to commit.
