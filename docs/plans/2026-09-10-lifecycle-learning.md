# Lifecycle and learning follow-up

The deployed instance already contained an extensive forecasting experiment.
This work uses its operational gaps to strengthen shared runtime behavior.
The original instance was inspected read-only; recovery was exercised on a
private SQLite backup with an isolated agent home and no copied credentials.

## Evidence from the existing book

At inspection: 2,233 questions, 7,403 snapshots, 1,806 resolutions,
5,216 scores, 1,718 postmortems, and 24 lessons (20 active).

- 98 resolved questions lacked a current score or postmortem. 96 had no durable
  finalization task; the other two had no current forecast to score.
- 121 active questions were past close. Another 58 had overdue review dates.
  These counts prioritize settlement review over review cadence when both apply.
  A close date does not establish an outcome.
- 2,776 historical lesson application rows lacked a stored per-lesson verdict.
  Successful commits had previously counted warning rules as applied even when
  they failed. Historical rows are now reported as unverified, without rewriting
  the historical ledger.
- The original market-nightly cohort contained 292 forecasts and 103 verified
  score pairs. Exact snapshot/baseline/resolution joins reproduced agent Brier
  0.0642762 versus market 0.1058556. The remaining 189 records have no verified
  resolved pair. These are descriptive results, not a new claim of skill or of
  causal benefit from lessons; settlement quality, shared events, information
  availability, and unresolved-cohort selection still require review.

## Shared ownership

- `forecasting/lifecycle.py` inspects incomplete transitions and recovers missing
  handoffs into the existing `operational_tasks` queue. It uses the existing
  lease, retry, idempotency, and finalization implementation. It does not reset
  exhausted retries, infer resolutions, or change forecast probabilities.
- CLI `forecast lifecycle status|run`, the scheduled review sweep, and the warning
  worker use that coordinator. The TUI review sweep checks finalization work as
  well as due reviews, including when a recent nightly run would otherwise defer
  it. Newly finalized work triggers the scheduled sweep's guarded lesson
  synthesis. Failure messages remain visible.
- `forecasting/learning.py` remains the selection owner for context, numeric
  adjustment, and compiled rules. Explicit supersession takes effect where both
  lessons match; inactive replacements cannot suppress active guidance. Cyclic
  supersession is rejected. Conditional prose is surfaced for review rather
  than guessed into a numerical rule.
- Each new live snapshot records per-lesson decisions, source references, the
  lesson version timestamp, and actual rule verdicts. Numeric overlap skips are
  distinguished from ignored adjustments. `forecast lessons audit` separates
  verified coverage from historical assertions; `forecast lessons explain <id>`
  exposes current guidance and the snapshot's recorded decisions.
- `forecasting/evaluation.py` owns exact market-study pairing for the standard
  report and the analysis script. New baseline records identify their agent
  snapshot explicitly; legacy records require an unambiguous baseline. Scores
  must match the original probability, baseline snapshot, question, and
  resolution, and must not be invalidated or quarantined. Outcomes are read from
  resolutions, never reverse-engineered from Brier. Frozen baselines remain a
  separate diagnostic stratum.

## Operator entry points

```sh
superforecasting-agent forecast lifecycle status
superforecasting-agent forecast lifecycle run --limit 100 --json
superforecasting-agent forecast lessons audit
superforecasting-agent forecast lessons explain <question-id>
```

Inside the installed TUI, the same commands are available as
`/forecast lifecycle status`, `/forecast lifecycle run`, and
`/forecast lessons audit`. The existing `forecast.command` RPC dispatches the
same Python CLI; no second forecast workflow or transcript was added.

`lifecycle run` only completes already-confirmed score/postmortem work. Inspect
settlement evidence through `forecast protocol <id> --stage resolve` and use the
existing explicit resolution command when the criteria are satisfied. A missing
forecast is surfaced for operator review; recovery does not invent one after
knowing the outcome.

## Verification

The private backup recovery completed all 96 missing handoffs, adding 12 scores
and 96 postmortems. Snapshot and resolution counts remained exactly 7,403 and
1,806. Repeated recovery left completed work unchanged. Two unscoreable lifecycle
entries remained visible. The live instance was not changed.

A wheel installed in a new Python 3.11 environment outside the checkout booted
the real TUI, rendered lifecycle status and historical lesson coverage through
slash commands, and exited with code 0. The terminal ran with an isolated home,
no production credentials, and its background ticker disabled. Local artifacts
include before/after JSON, conservation checks, and terminal screen captures;
private question content is not included in this repository.

Regression tests cover missing handoff recovery, repeat execution, failures and
retry state, preservation of unresolved outcomes, finalization with no due TUI
reviews, synthesis after finalization, failed warning rules, supersession,
unverified historical coverage, and exact evaluation after a later forecast.
Validation results:

- Full default Python run: 30,157 passed, 141 skipped, five failures (621.25s).
  All five were inherited compatibility gaps: four minimal CLI test instances
  lacked `config` after the prior alias extraction, and one branding assertion
  omitted the extracted PTY connection helper from its inspected source list.
  Both causes were fixed; the complete affected test files then passed
  (174 passed, one skipped). The full 30k suite was not repeated after those
  fixes; final focused regressions were run instead.
- Final lifecycle/learning/evaluation/TUI-sweeper regression run: 109 passed.
- Source-change workflow and learning regression run: 94 passed (overlapping
  coverage; do not sum suite totals as unique tests).
- Ruff, whitespace checks, generated-reference freshness, and protocol checks
  passed. No paid-provider calls were needed for these deterministic changes.

The implementation commit is `40928ffc6`. The compact artifact manifest in
`docs/verification/2026-09-10-lifecycle-learning.json` binds the installed wheel
and isolated recovery results to that source. Installation used Python 3.11;
the Python regression runner used Python 3.13 on macOS.
