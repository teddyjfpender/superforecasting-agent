---
title: Kanban Worker Lanes
description: Worker-lane contracts for forecast-desk Kanban execution.
---

# Kanban Worker Lanes

A worker lane is a class of process the Kanban dispatcher can route tasks to. Each lane has an assignee identity, a spawn mechanism, and a lifecycle contract for closing or blocking the claimed task.

In the forecast desk, lanes are useful for specialist roles such as source analyst, quant researcher, forecast reviewer, resolver reviewer, benchmark maintainer, or source-adapter engineer. Lanes execute tasks; they do not own the forecast ledger.

## Hierarchy

```text
Kanban board    = task lifecycle and attempt audit trail
Worker lane     = executor for one assigned task
Reviewer        = human or review profile that gates completion
Forecast ledger = durable forecasts, evidence, models, scores, and learning
```

Kanban owns task lifecycle truth: `ready -> running -> blocked / done / archived`. The forecast ledger owns forecast truth. Worker lanes must write forecast-relevant outcomes through explicit forecast commands or tools after review.

## What a Lane Provides

### 1. Assignee String

The dispatcher matches `task.assignee` against either:

- a Superforecasting Agent profile name
- a registered non-spawnable identifier supplied by a plugin

Tasks whose assignee cannot be resolved stay on `ready` with a `skipped_nonspawnable` event. They are not silently executed by an arbitrary fallback.

### 2. Spawn Mechanism

For profile lanes, the dispatcher spawns a quiet chat process for the assignee profile inside the task workspace. The fork-native command shape is:

```bash
superforecasting-agent -p <assignee> chat -q <prompt>
```

Migrated installs may still use `hermes -p <assignee> chat -q <prompt>` or the equivalent module form.

The dispatcher sets inherited runtime environment variables:

| Variable | Carries |
|---|---|
| `HERMES_KANBAN_TASK` | task id the worker is operating on |
| `HERMES_KANBAN_DB` | absolute path to the per-board SQLite file |
| `HERMES_KANBAN_BOARD` | board slug |
| `HERMES_KANBAN_WORKSPACES_ROOT` | root of the board workspace tree |
| `HERMES_KANBAN_WORKSPACE` | absolute path to this task workspace |
| `HERMES_KANBAN_RUN_ID` | current run id |
| `HERMES_KANBAN_CLAIM_LOCK` | claim lock string |
| `HERMES_PROFILE` | worker profile name |
| `HERMES_TENANT` | tenant namespace, if present |

These names remain `HERMES_*` because they are inherited runtime identifiers.

For external lanes registered by plugins, the plugin supplies a `spawn_fn` callable that receives task, workspace, and board context and returns an optional pid for crash detection.

### 3. Lifecycle Terminator

Every claim must end in exactly one terminal path:

- `kanban_complete(summary=..., metadata=...)`
- `kanban_block(reason=...)`
- failure handling by the kernel when the worker exits, crashes, times out, or trips the retry circuit

Healthy workers should call `kanban_complete` or `kanban_block`. A worker that exits without either is treated as failed.

## Review-Required Convention

For code-changing or forecast-impacting tasks, completion often needs human review. The common convention is:

1. Add a `kanban_comment` with structured metadata.
2. Call `kanban_block(reason="review-required: ...")`.
3. Let a reviewer approve, comment, or unblock.
4. Record any forecast-relevant result through the forecast ledger after approval.

Useful review metadata:

- changed files
- tests run
- source ids inspected
- evidence candidates
- model parameters and output
- assumptions that need review
- forecast ids affected
- proposed ledger action

The block keeps the task out of `done` until review has happened.

## Logs and Audit Trail

The dispatcher writes worker stdout/stderr to the board logs directory. The board records:

- `task_runs` with outcome, worker, timings, summary, metadata, log path, and exit code where available
- `task_events` with transitions such as promoted, claimed, heartbeat, completed, blocked, gave_up, crashed, timed_out, reclaimed, and claim_extended
- `kanban_show` context with task history, parent handoffs, comments, and active run state

CLI users can inspect:

```bash
superforecasting-agent kanban tail <task-id>
superforecasting-agent kanban runs <task-id>
```

Legacy `hermes kanban tail` and `hermes kanban runs` remain compatibility aliases.

## Existing Lane Shapes

### Profile Lane

The default lane shape uses a forecast profile as the assignee. The worker loads the Kanban worker guidance, receives the task context, uses normal tools to do the work, and terminates through `kanban_*` tools.

Create profile names that match roles the decomposer should route to, for example:

- `source-analyst`
- `quant-researcher`
- `forecast-reviewer`
- `resolver-reviewer`
- `adapter-engineer`

The orchestrator discovers profile names through the profile list. It does not assume a fixed roster.

### Orchestrator Profile Lane

An orchestrator profile decomposes high-level tasks into child tasks with `kanban_create` and `kanban_link`. It should avoid implementation work unless explicitly configured for it.

For forecast work, the orchestrator should create tasks that end in explicit ledger actions or reviewed handoffs, not hidden probability changes.

## External CLI Worker Lanes

External CLI lanes, such as Codex CLI, Claude Code, OpenCode, or a local coding-model runner, are not yet a fully paved path. A plugin can provide a custom `spawn_fn`, but it must still satisfy the same lifecycle contract:

- map the CLI workspace and sandbox into the Kanban workspace
- report status through `kanban_complete` or `kanban_block`
- preserve run metadata and logs
- handle auth and per-CLI policies
- avoid writing forecast state outside the forecast ledger

The inherited issue references for this design are still useful background: `#19931` and the closed Codex-specific PR `#19924` in the upstream Hermes repository.

## Failure Modes

The dispatcher handles:

- stale claim TTL for dead workers
- crashed worker detection
- run-level retry after block, crash, or reclaim
- per-task max runtime
- stranded ready-task diagnostics
- consecutive-failure circuit breaker

Use diagnostics to find unresolved assignees or stalled pools:

```bash
superforecasting-agent kanban diagnostics
```

## Related

- [Kanban overview](./kanban)
- [Kanban tutorial](./kanban-tutorial)
- [Codex app-server runtime](./codex-app-server-runtime)
- [Forecast scheduling and cron](./cron)
