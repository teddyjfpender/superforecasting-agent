---
name: apply-lesson
description: "Turn a calibration LESSON into an enforced hook rule so it actually changes future forecasts instead of sitting as prose. The system auto-compiles a recognized lesson at creation; use this to apply/strengthen one, pick its enforcement pattern, and verify it bites. Invoke after a postmortem produces a lesson, or when `forecast lessons audit` shows a lesson is ADVISORY or DORMANT, e.g. /apply-lesson cl_9ebae9c3280f"
version: 1.0.0
author: Superforecasting Agent
license: MIT
platforms: [linux, macos, windows]
aliases: [apply-lesson, enforce-lesson, lesson-to-hook]
metadata:
  hermes:
    tags: [forecasting, calibration, lessons, hooks, enforcement, postmortem, superforecasting]
    category: forecasting
    related_skills: [forecasting-loop, forecast-rerun, forecast-onboard]
---

# Apply a lesson — make a learning enforce, don't just file it

A postmortem that produces a beautifully-worded lesson is worthless if the next
forecast never consults it. A lesson only counts when it **changes the next
in-scope forecast or is visibly flagged as not doing so**. This skill turns a
lesson into a hook rule that bites at commit. The operator is assumed lazy: the
system does the compiling — you only confirm the pattern and the severity.

## The model (read once)

- A calibration lesson lives in the ledger with a `scope` (domain / topic /
  `domain_topic:domain:topic` / `question_type`) and a `recommended_adjustment`.
- The desk **auto-compiles** a lesson into a `lesson:<id>` hook rule **at creation**
  when it recognizes an enforcement pattern (WARN by default — observe-then-flip).
  So most lessons need no manual step.
- "Applied" means the lesson's **compiled rule passes by the candidate forecast's
  own substance** — never that a ref was stapled on. The rule's scope is
  force-stamped from the lesson's own scope (it can't be widened) and its severity
  can't be demoted by a per-question/config override.
- A lesson with no recognizable pattern stays **advisory** (surfaced in the agent
  context + the TUI, but it does not block). That is honest, not a failure.

## Enforcement patterns (the library)

A lesson maps to ONE pattern, each backed by a real commit signal:

| Pattern | Bites when… | Signal |
|---|---|---|
| `tail_cap` | unearned lower-tier / no-path mass is too fat (crowded-field compression) | `tails.null_excess` |
| `born_scoreable` | a vote-share forecast isn't machine-scoreable (no numeric candidate shares) | `outcome.machine_scoreable` |
| `require_reference_class` | a forecast lacks an outside-view anchor | `reference_classes.count` |
| `require_winner_backing` | a confident winner call (> ~65%) has no linked vote-share / derived model | `confidence.winner_prob` + `links.derived_child_present` |

Some lessons are genuinely modeling-judgment (e.g. "treat movement-field effects as
turnout shocks", "decay incumbency after a late challenger signal"). These have **no
robust signal** and stay advisory by design — do not force them into a checkbox.

## How to apply a lesson

### 1. Let creation do it (preferred — lazy operator)

When you record a lesson, give its `recommended_adjustment` either an explicit
pattern or a descriptive `process_rule`; the desk auto-compiles it:

```
recommended_adjustment: {
  "enforcement_pattern": "tail_cap",          # explicit (best), OR
  "process_rule": "add_top_two_consolidation_layer",  # inferred by keyword
  "candidate_tail_cap": "cap non-viable lower-tier near 5-10%",
  ... (any prose you want to keep) ...
}
```

A lesson created this way is already a WARN hook rule — verify with the audit (step 3).

### 2. Apply / strengthen an existing lesson

For a lesson that is still prose (older lessons, or `lessons audit` shows ADVISORY):

```
forecast lessons apply <lesson_id>              # compile to a WARN rule
forecast lessons apply <lesson_id> --severity error   # make it BLOCK at commit
```

It prints the pattern + the compiled check, or tells you no pattern matched (then
declare `enforcement_pattern` explicitly on the lesson and re-run).

### 3. Verify it actually bites

```
forecast lessons audit
```

Read the status per lesson:
- **enforced** — compiled to a rule; it bites on in-scope commits.
- **ADVISORY** — prose only; it will NOT bite. Apply a pattern (step 2) or accept
  it as judgment-only.
- **DORMANT** — never encountered an in-scope forecast since creation. Either no
  matching forecast has committed yet, or the **scope is wrong** — re-scope it (e.g.
  a `domain_topic:politics:nyc-primaries` lesson only fires on questions tagged
  `nyc-primaries`; broaden to `domain:politics`, or tag the questions canonically).

## Severity discipline

Ship every lesson rule at **WARN first** (it records on the saturation report +
shows in the audit without blocking). Watch it bite on a real forecast or two, then
`forecast lessons apply <id> --severity error` to make it block. A blocking lesson
rule refuses a commit that violates it unless the forecast is recorded
`forecast_origin=exploratory` (an audited escape, not a silent one).

## Bottom line

After this, a learning is one of exactly two things, both visible in `lessons
audit`: an **enforced rule** that shapes the next in-scope forecast, or an
explicitly **advisory** note that surfaces but doesn't block. Never a dead memo.
