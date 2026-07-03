---
name: ledger-interaction
description: "How to read and write the forecast ledger correctly. WRITES (questions, forecasts, evidence, panels, lessons, resolutions) go through the forecast tool's gated, per-question flow — NOT through scripts that import ForecastLedger or hit its SQLite file. Scripting is for read-only audits and rare one-off migrations only. Invoke before any bulk or batch ledger work, or whenever you are tempted to write a Python script that touches the ledger, e.g. /ledger-interaction"
version: 1.0.0
author: Superforecasting Agent
license: MIT
platforms: [linux, macos, windows]
aliases: [ledger-interaction, ledger-discipline, no-ledger-scripts]
metadata:
  hermes:
    tags: [forecasting, ledger, discipline, tools, bulk, migration, superforecasting]
    category: forecasting
    related_skills: [forecasting-loop, apply-lesson, forecast-rerun]
---

# Interacting with the ledger — the tool writes, scripts only read

The forecast ledger is the immutable record your forecasts are scored on. The
fastest-looking path — a Python script that does `from forecasting.ledger import
ForecastLedger` and loops `create_snapshot` — is the wrong one. It skips the
deliberate, gated, one-question-at-a-time flow the desk is built around, and it
collapses into a single template stamped across many questions. That looks
productive and reads as faulty. This skill is the rule for staying on the gated path.

## The read/write boundary (read once)

- **WRITES go through the `forecast` tool / CLI**, never raw DB or a direct
  `ForecastLedger` import. Use the actions, not the internals:
  `create_question`, `update_forecast`, `record_panel` / `aggregate_panel`,
  `add_evidence` / `import_source_evidence`, `add_reference_class`, `resolve`,
  `score`, `postmortem`, `update_calibration_lesson`. Each runs the commit gates
  (evidence, panel, freshness, structure, style, uncertainty, lessons) and records a
  real deliberation.
- **READS may use scripts** — analysis, audits, exports, sanity checks. A read-only
  script that imports the ledger is fine. `ledger._connect()` and raw SQL are a smell
  even for reads: prefer `search_questions`, `list_*`, `show_question`,
  `calibration_summary`, `doctor_report`, `detect_templated_batches`.
- **Never** reach into `_connect()` to mutate rows. There is no forecast you can
  write correctly with raw SQL that the tool can't write better.

## Don't script forecasts — the tells you're off the path

If a script you're writing does any of these, stop and use the tool instead:

- imports `ForecastLedger` and calls `create_snapshot` / `record_panel_run` / a
  write method in a loop;
- uses `ledger._connect()` to `INSERT` / `UPDATE` / `DELETE`;
- hand-builds a panel as a fixed list of perspectives with the same rationale text
  and only a name swapped — that is a fake panel, not a deliberation;
- sets `acknowledge_stale_evidence=True` to get past the freshness gate without
  having actually checked the drivers.

The one legitimate write-script is a **rare, one-off migration** (e.g. a schema
back-fill). Even then it calls the gated ledger methods, never raw SQL, and you say
plainly that it's a migration.

## Watch management is tool-native

Watched sources (the refresh/autopilot/alert fuel) are WRITES: use the
`forecast` tool's `add_watched_source` — and for anything bulk, ONE
`add_watched_sources` call takes up to 400 `{question_id, source, ...}`
entries with per-row results (a whole thesis in one call — never a script
loop). `list_watched_sources` / `check_watched_sources` cover the reads.
Raw `INSERT INTO watched_sources` from a script is refused by the
connection-level gate, same as scripted forecasts.

## Bulk work without templating

Bulk is fine — many primaries, a whole tracker. The discipline is per-item, not
batch:

1. Find existing questions with `search_questions` (free-text / title); keep the ids
   `create_question` returns. Do **not** re-derive ids with raw SQL by title.
2. Forecast each question on its own substance: its own fresh evidence
   (`import_source_evidence`), its own panel (real, distinct perspectives), its own
   reasoning. Two races are never the same forecast with a name swapped.
3. Self-check with `detect_templated_batches` (also in `forecast doctor`): it flags
   clusters of recent live forecasts that share an identical method +
   reasoning-methods + rationale skeleton — the "one template ×N" pattern. A cluster
   there means redo those as real per-question forecasts.

## Escape hatches are explained, not free

The gates have audited exits — use them honestly, never to fake compliance:

- **Stale evidence**: if you truly checked and nothing material changed, set
  `stale_evidence_reason="…"` (CLI `--stale-evidence-reason`) alongside
  `acknowledge_stale_evidence`. Acknowledging **without** a reason raises the
  `stale_evidence_justified` WARN on the saturation report.
- **Skipped panel**: record `panel_skipped_reason="…"` rather than silently omitting
  a required panel.
- **Genuinely exploratory**: record `forecast_origin=exploratory` — unscored, not
  gated, the right home for scratch work and side models.

## Your workspace, and the harness wall

There is a clean separation between WHERE you may write code and WHAT that code
may do to the ledger.

- **Write code in your workspace.** `~/.superforecasting-agent/workspace`
  (and the sibling `~/.superforecasting-agent/scripts`) is your sanctioned
  write zone for forecasting models, backtests, research, and scratch
  calculations. Your terminal / code-execution tools default into it. Anything
  under the agent home or the system temp dir is allowed too. Write and run
  data-science code there as freely as the problem needs.
- **You cannot edit the harness.** The code that implements this desk — the
  installed package and its repo (`tools/`, `hermes_cli/`, `agent/`, the
  gateway) — is immutable from inside the agent. `write_file` and `patch` will
  **hard-reject** any write whose resolved target lands in the harness source
  tree, returning an error that points you back to the workspace. This is a
  deliberate guardrail: a self-modifying forecasting desk is a footgun. If you
  believe the harness should change, write the proposed patch plus your
  rationale into the workspace and flag it for human review — do not apply it
  yourself. (The wall is a config flag, `harness_wall.enabled`, default on.)

What's airtight and what isn't — be honest with yourself:

- The forecast **ledger** is *fully* gated. Every forecast-producing write
  (new question, snapshot, panel run) is enforced at the database-connection
  level by a SQLite authorizer in `forecasting.ledger`. Even a script you write
  and run in the terminal that imports `ForecastLedger` or opens a raw
  connection **cannot** fabricate a forecast outside the tool's commit flow — it
  is denied at query time. There is no terminal back door to the ledger.
- The **file-write tools** (`write_file` / `patch`) are *enforced*: a harness
  target is hard-rejected, full stop.
- The **terminal tool** is *best-effort only*, and you should know it: it is not
  a sandbox. Its default working directory is moved out of the harness into your
  workspace, and it refuses the obvious shell write patterns (`echo … >
  tools/x.py`, `tee` into the tree). But it cannot stop every way of writing a
  file (Python `open()`, `cp`, `dd`, an env trick). Do not treat the absence of
  a block as permission: the rule is "don't edit the harness," not "edit it if
  you can find a hole." If you need a harness change, propose it for review.

Note the rules compose: scripting forecasts is wrong (use the tool — and the
ledger now enforces it), and editing the harness is off-limits — but building a
backtest or a side model in the workspace and running it is exactly what the
workspace is for.

## Bottom line

Reads can be scripts; writes are the tool's. Bulk means many real forecasts, not one
template ×N. If a gate is in your way, satisfy it or take an explicit, reasoned
exit — never script around it. `forecast doctor` will show a templated batch if you
slip; fix it by forecasting those questions for real.
