---
sidebar_position: 12
title: "Kanban (Forecast Work Board)"
description: "Durable task board for coordinating forecast research, modeling, review, and backtesting work."
---

# Kanban

Kanban is the durable task board for the command-line forecasting desk. Use it to coordinate forecast research, source-adapter work, model scripts, resolver packets, benchmark maintenance, scheduled self-checks, and reviewer-gated updates across profiles.

Kanban does not replace the forecast ledger. The board records tasks, comments, runs, retries, and handoffs. The ledger records forecast questions, probabilities, evidence, assumptions, model runs, resolutions, scores, postmortems, calibration lessons, and domain error profiles. A worker summary can recommend a ledger action; it is not the ledger action itself.

For walkthroughs and worker contracts, see:

- [Kanban tutorial](./kanban-tutorial)
- [Kanban worker lanes](./kanban-worker-lanes)
- [Forecast scheduling and cron](./cron)

## Core Model

Kanban is a SQLite-backed work queue shared by forecast profiles.

| Object | Purpose |
|---|---|
| Board | Isolated task queue for a project, domain, or benchmark stream. |
| Task | Work item with title, body, assignee, status, priority, tenant, and optional idempotency key. |
| Link | Parent-child dependency. A child can wait until parents are done. |
| Comment | Human or worker note, usually with structured metadata. |
| Run | One worker attempt with status, timings, summary, metadata, log path, and exit information. |
| Workspace | Directory where the worker operates. |
| Dispatcher | Loop that promotes, claims, spawns, retries, and reclaims tasks. |

The default board stores its database at:

```text
~/.superforecasting-agent/kanban.db
```

Named boards use:

```text
~/.superforecasting-agent/kanban/boards/<slug>/kanban.db
```

Migrated installs may still read and write `~/.hermes/kanban.db` and `~/.hermes/kanban/boards/<slug>/kanban.db`.

## Two Surfaces

The board has two front doors:

- Workers use the `kanban_*` tools: `kanban_show`, `kanban_list`, `kanban_create`, `kanban_link`, `kanban_comment`, `kanban_complete`, `kanban_block`, `kanban_unblock`, and `kanban_heartbeat`.
- Humans and automation use `superforecasting-agent kanban ...`, `/kanban ...`, or the dashboard.

Both surfaces route through the same board database. Worker profiles should not shell out to the CLI for normal task lifecycle operations; they call the tools directly after the dispatcher injects the current task context.

The inherited `hermes kanban ...` command remains a compatibility alias for migrated installs.

## When To Use Kanban

Use Kanban when forecast work needs durable coordination:

- research refreshes across many active forecasts
- scheduled source-watch sweeps
- model or source-adapter implementation with review
- resolver packet preparation before a question resolves
- backtesting fixture maintenance
- calibration-review tasks after resolved forecasts
- domain self-checks that should trigger learning updates
- human-in-the-loop review before a probability update is recorded

Use `delegate_task` when a running model needs a short answer immediately and the parent can continue only after the result returns. Kanban is for work that can survive restarts, hand off between roles, or wait for review.

## Auto vs Manual Orchestration

Kanban can be driven manually or through an orchestrator profile.

Manual orchestration means you create each task, dependency, assignee, and review gate yourself with `superforecasting-agent kanban ...`. Use manual mode for forecast updates, resolver decisions, calibration learning, and any work where the decomposition itself affects forecast quality.

Auto orchestration means a profile decomposes a larger goal into child tasks with `kanban_create` and `kanban_link`. Use auto orchestration for bounded support work such as source sweeps, benchmark fixture refreshes, adapter test matrices, or broad stale-forecast scans. Review the generated tasks before allowing them to write anything into the forecast ledger.

## How Workers Interact With The Board

Workers interact with the board through `kanban_*` tools, not by running CLI commands. The dispatcher injects task context, enables the worker toolset, and expects the worker to call `kanban_show()` before acting.

The usual worker flow is:

1. Read the assigned task with `kanban_show()`.
2. Inspect parent summaries, comments, block reasons, and metadata.
3. Do the assigned work in the task workspace.
4. Add any useful notes with `kanban_comment(...)`.
5. End with `kanban_complete(...)` or `kanban_block(...)`.

Forecast-relevant outputs should be handed off as metadata or recorded through explicit forecast tools after review. A worker should not hide a probability update inside a task summary.

## Kanban Slash Command

Interactive sessions can use `/kanban ...` as a slash-command wrapper around the same board operations exposed by `superforecasting-agent kanban ...`.

Use slash commands for quick inspection, comments, or unblocking while already inside a session. Use the CLI for scripts, cron jobs, repeatable setup, and idempotent automation.

## Status Lifecycle

Kanban uses these task states:

| State | Meaning |
|---|---|
| `triage` | Rough idea or undecomposed work. |
| `todo` | Created but waiting on dependencies or assignment. |
| `ready` | Eligible for dispatch. |
| `running` | Claimed by a worker. |
| `blocked` | Waiting for review, input, credentials, or failure recovery. |
| `done` | Completed. |
| `archived` | Hidden from normal active views. |

Child tasks move from `todo` to `ready` when all parent tasks are `done`. Workers should finish by calling exactly one terminal tool:

```python
kanban_complete(summary="...", metadata={...})
kanban_block(reason="review-required: ...")
```

If a worker exits, crashes, times out, or trips the retry circuit without a terminal tool call, the dispatcher records the failure and may retry or block the task.

## Quick Start

```bash
superforecasting-agent kanban init
superforecasting-agent gateway start
superforecasting-agent kanban create "Review stale macro forecasts" \
    --assignee forecast-reviewer \
    --tenant weekly-self-check \
    --priority 2
superforecasting-agent kanban watch
superforecasting-agent kanban list
```

When the dispatcher picks up the task, it spawns the assigned profile as a worker. The worker reads the task through `kanban_show()`, performs the work, then completes or blocks through the worker toolset.

## Forecast Workflow Example

```bash
CRITERIA=$(superforecasting-agent kanban create "Review forecast 142 criteria" \
    --assignee forecast-researcher \
    --tenant election-2026 \
    --priority 2 \
    --body "Check resolution criteria, close time, ambiguity, and unresolved assumptions." \
    --json | jq -r .id)

SOURCES=$(superforecasting-agent kanban create "Gather fresh evidence for forecast 142" \
    --assignee source-analyst \
    --tenant election-2026 \
    --priority 2 \
    --parent "$CRITERIA" \
    --body "Find timestamped primary sources and note reliability, relevance, and stance." \
    --json | jq -r .id)

MODEL=$(superforecasting-agent kanban create "Run base-rate model for forecast 142" \
    --assignee quant-researcher \
    --tenant election-2026 \
    --priority 2 \
    --parent "$SOURCES" \
    --body "Produce a reviewed model-run packet with inputs, assumptions, parameters, and output." \
    --json | jq -r .id)

superforecasting-agent kanban create "Review ledger update for forecast 142" \
    --assignee forecast-reviewer \
    --tenant election-2026 \
    --priority 2 \
    --parent "$MODEL" \
    --body "Compare current forecast, evidence, and model output. Record a ledger update only if warranted."
```

The last task should not silently change forecast state just because earlier tasks completed. A reviewer or forecast workflow should write the probability update, evidence import, or model run explicitly through the ledger.

## Boards

Boards isolate unrelated streams of work. Use one board per forecast domain, tournament, client, repo, or benchmark stream when you want separate task queues and logs.

```bash
superforecasting-agent kanban boards list
superforecasting-agent kanban boards create macro-2026 \
    --name "Macro 2026" \
    --description "Macro forecasts, source watches, and calibration review" \
    --switch

superforecasting-agent kanban --board macro-2026 list
superforecasting-agent kanban boards show
superforecasting-agent kanban boards switch default
```

Board resolution order is:

1. Explicit `--board <slug>` on the CLI call.
2. `HERMES_KANBAN_BOARD`, set by the dispatcher for worker processes.
3. The current-board pointer under the profile home.
4. `default`.

`HERMES_KANBAN_BOARD` is an inherited runtime variable name, not a product name.

## Workspaces

Each task can run in one of these workspace modes:

| Mode | Use |
|---|---|
| `scratch` | Fresh per-task workspace under the board workspace tree. |
| `dir:<absolute-path>` | Existing trusted directory for shared project work. |
| `worktree` | Git worktree for code tasks such as source adapters, benchmark fixtures, or model scripts. |

Relative `dir:` paths are rejected because worker dispatch should not depend on the dispatcher's current directory. Kanban is still a trusted-local-user system; worker processes run with your user permissions.

## Dispatcher

The dispatcher normally runs inside the gateway:

```yaml
kanban:
  dispatch_in_gateway: true
  dispatch_interval_seconds: 60
```

Start it with:

```bash
superforecasting-agent gateway start
```

The dispatcher:

- promotes tasks whose dependencies are complete
- atomically claims ready tasks
- spawns assigned profile lanes
- sets inherited `HERMES_KANBAN_*` runtime variables
- records heartbeats, run status, logs, and failures
- reclaims stale or crashed workers
- blocks tasks that exceed retry or failure limits

Running a standalone `kanban daemon` is a legacy debugging path. Prefer the gateway-hosted dispatcher so one loop owns board dispatch.

## Worker Context

When a worker starts, the dispatcher provides task context through inherited runtime variables:

| Variable | Carries |
|---|---|
| `HERMES_KANBAN_TASK` | Current task id. |
| `HERMES_KANBAN_DB` | Board SQLite path. |
| `HERMES_KANBAN_BOARD` | Board slug. |
| `HERMES_KANBAN_WORKSPACE` | Absolute task workspace path. |
| `HERMES_KANBAN_WORKSPACES_ROOT` | Board workspace root. |
| `HERMES_KANBAN_RUN_ID` | Current run id. |
| `HERMES_KANBAN_CLAIM_LOCK` | Claim lock token. |
| `HERMES_PROFILE` | Worker profile name. |
| `HERMES_TENANT` | Optional tenant namespace. |

These names remain `HERMES_*` for runtime compatibility. New docs and user-facing commands should still use the fork-native product name.

## Structured Handoffs

A useful worker handoff includes a short summary and structured metadata:

```python
kanban_complete(
    summary="reviewed four primary sources and one market-implied estimate; two evidence imports recommended",
    metadata={
        "forecast_id": "142",
        "source_ids": ["sec:2026-05-21-8k", "fred:DGS10"],
        "evidence_candidates": [
            {"url": "https://example.com/source", "stance": "raises_probability", "reliability": "primary"}
        ],
        "assumptions_to_review": ["baseline turnout denominator"],
        "recommended_ledger_actions": ["import_evidence", "forecast_update_review"],
    },
)
```

Good metadata for forecast work includes:

- forecast ids
- source ids or URLs inspected
- evidence candidates requiring ledger import
- model files, inputs, parameters, tests, and output
- assumptions needing review
- resolver or scoring notes
- recommended next ledger action

Do not treat Kanban metadata as final forecast state. It is a handoff channel.

## Review Gates

Use `review-required` blocks when a task changes code, model assumptions, source import logic, resolver packets, or forecast state.

```python
kanban_comment(
    body="review-required",
    metadata={
        "changed_files": ["models/forecast_142_base_rate.py"],
        "tests_run": ["pytest tests/forecasting/test_models.py"],
        "forecast_ids": ["142"],
        "proposed_ledger_action": "record_model_run",
    },
)
kanban_block(reason="review-required: model script ready for leakage and assumption review")
```

After review, unblock the task:

```bash
superforecasting-agent kanban unblock <task-id>
```

The next run sees prior comments, block reasons, parent summaries, and metadata through `kanban_show()`.

## Scheduled Self-Checks

Cron jobs can create Kanban tasks for recurring learning loops:

- refresh evidence watches for active questions
- find stale forecasts by domain
- prepare resolver packets for questions near resolution time
- run backtesting fixture refreshes
- schedule calibration reviews for recently resolved questions
- open domain-error review tasks after scoring

The cron trigger should create or dispatch work. The forecast ledger still owns the eventual evidence import, score update, postmortem, and calibration-memory write.

## Dashboard

The dashboard Kanban tab reads the same board database as the CLI and worker tools. Use it to inspect active tasks, runs, comments, retry failures, and blocked review items.

The dashboard is a support surface around the CLI product. It should not become a separate forecast-writing interface unless those writes go through the same forecast ledger commands and audit trail.

## Useful Commands

```bash
superforecasting-agent kanban init
superforecasting-agent kanban list
superforecasting-agent kanban show <task-id>
superforecasting-agent kanban create "Task title" --assignee source-analyst
superforecasting-agent kanban comment <task-id> "Needs resolver review"
superforecasting-agent kanban block <task-id> "waiting for credentials"
superforecasting-agent kanban unblock <task-id>
superforecasting-agent kanban complete <task-id> --result "done"
superforecasting-agent kanban runs <task-id>
superforecasting-agent kanban tail <task-id>
superforecasting-agent kanban watch --kinds completed,gave_up,timed_out
superforecasting-agent kanban stats
superforecasting-agent kanban diagnostics
```

For automation, use `--idempotency-key` to avoid duplicate recurring tasks:

```bash
superforecasting-agent kanban create "Weekly macro stale-forecast review" \
    --assignee forecast-reviewer \
    --tenant weekly-self-check \
    --idempotency-key "macro-stale-review-2026-05-22"
```

## Relationship To Forecast Quality

Kanban helps the system become a better forecaster only when it feeds the closed loop:

```text
forecast -> observe -> update -> resolve -> score -> diagnose -> recalibrate
```

Use Kanban to make the work durable and reviewable. Use the forecast ledger to make beliefs auditable, scoreable, and learnable.
