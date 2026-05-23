---
sidebar_position: 16
title: "Persistent Goals"
description: "Set a standing objective and let the runtime continue across turns."
---

# Persistent Goals (`/goal`)

`/goal` gives the inherited runtime a standing objective that survives across turns. After each turn, a lightweight judge model decides whether the objective is satisfied. If not, Superforecasting Agent appends a continuation prompt and keeps working until the goal is achieved, paused, cleared, or the turn budget is exhausted.

For forecasting, `/goal` is best for bounded work such as source-adapter fixes, benchmark cleanup, docs audits, or research report generation. It is **not** the same as forecast scheduled self-checks: standing beliefs, stale-forecast review, scoring, postmortems, and calibration learning belong in the forecast ledger and `forecast schedule`.

## When to Use It

Use `/goal` for tasks where you would otherwise have to say "keep going" several times:

- "Fix every failing `tests/forecasting/` test and verify the focused suite passes."
- "Audit this source adapter for timestamp leakage and add a regression test."
- "Review the benchmark import docs, patch stale examples, and run the docs build."
- "Investigate why scheduled review alerts are duplicated and write a short report."

Do not use `/goal` to maintain active forecast probabilities. Use `forecast schedule`, watched sources, alerts, and ledger postmortems for durable forecasting loops.

## Quick Start

```text
/goal Fix every failing test in tests/forecasting/ and make sure scripts/run_tests.sh passes for that directory
```

Typical flow:

1. `Goal set` with a turn budget.
2. The first turn runs immediately.
3. The judge returns `done` or `continue`.
4. If needed, the runtime appends a continuation prompt.
5. The loop ends with `Goal achieved` or pauses at the budget.

## Commands

| Command | What it does |
|---|---|
| `/goal <text>` | Set or replace the standing goal and start the first turn |
| `/goal` or `/goal status` | Show the current goal, status, and turns used |
| `/goal pause` | Stop auto-continuation without clearing the goal |
| `/goal resume` | Resume the loop and reset the turn counter |
| `/goal clear` | Drop the goal |

The command works in the CLI and gateway platforms that expose slash commands.

## Adding Criteria with `/subgoal`

While a goal is active, `/subgoal <text>` appends another acceptance criterion without resetting the loop. The continuation and judge prompts include the original goal plus every subgoal, so the goal is not marked done until all criteria are satisfied.

| Command | What it does |
|---|---|
| `/subgoal <text>` | Append a criterion to the active goal |
| `/subgoal` | Show the current subgoal list |
| `/subgoal remove <N>` | Remove a criterion by 1-based index |
| `/subgoal clear` | Drop every subgoal but keep the original goal |

Subgoals persist with the goal in `SessionDB.state_meta`, so `/resume` keeps them.

## Behavior Details

### Judge

After each turn, the `goal_judge` auxiliary task receives:

- the standing goal
- all subgoals
- the most recent final response
- instructions to return strict JSON with `done` and `reason`

The judge is conservative: it should mark done only when the response explicitly confirms completion, produces the requested deliverable, or reports a real blocker.

### Fail-Open Semantics

If the judge fails because of network, malformed output, or unavailable auxiliary runtime, the loop treats the verdict as `continue`. The turn budget is the hard stop.

### Turn Budget

Default budget is 20 continuation turns:

```yaml
goals:
  max_turns: 20
```

Configure this in `~/.superforecasting-agent/config.yaml`. Legacy `~/.hermes/config.yaml` remains readable during migration.

When the budget is reached, the goal pauses. Use `/goal resume` to continue in another chunk.

### User Messages Preempt

Any real user message takes priority over the queued continuation. The judge runs again after your turn, so manual intervention can complete, redirect, or pause the loop.

### Mid-Run Safety

While a turn is running, `/goal status`, `/goal pause`, and `/goal clear` are safe control-plane actions. Setting a new goal mid-run is rejected so the old continuation cannot race the new objective.

### Persistence

Goal state is stored in `SessionDB.state_meta` under the active session. `/resume` restores the goal as active, paused, or done.

### Prompt Cache

Continuation prompts are normal user-role messages. They do not mutate the system prompt or swap toolsets, so they preserve prompt-cache behavior.

## Judge Model

`goal_judge` is an auxiliary model task. By default it resolves through the normal auxiliary-model chain. To route it to a cheap fast model:

```yaml
auxiliary:
  goal_judge:
    provider: openrouter
    model: google/gemini-3-flash-preview
```

The judge call is small and runs once per turn.

## Example

```text
You: /goal Create four files /tmp/note_{1..4}.txt, one per turn, each containing its number

Goal set: Create four files...

Forecaster: Creating /tmp/note_1.txt now.
Continuing toward goal: only 1 of 4 files exists.

Forecaster: Created /tmp/note_2.txt.
Continuing toward goal: 2 of 4 files exist.

Forecaster: Created /tmp/note_3.txt.
Continuing toward goal: 3 of 4 files exist.

Forecaster: Created /tmp/note_4.txt.
Goal achieved: all four files were created.
```

## When the Judge Gets It Wrong

False negatives usually just spend extra budget. Clear or pause the goal when you can see the work is done.

False positives are more important: if the judge marks done too early, set a more specific goal or add a subgoal that names the missing deliverable.

## Forecasting Boundary

Use `/goal` for work execution. Use ledger-native workflows for forecasting state:

- `forecast schedule` for recurring self-checks
- watched sources for evidence alerts
- `forecast resolve`, `forecast score`, and `forecast postmortem` for feedback loops
- calibration lessons and domain error profiles for learning

This separation keeps long-running task automation from silently rewriting scoreable beliefs.

## Attribution

`/goal` follows the Ralph loop pattern popularized by Codex CLI 0.128.0. This implementation is independent and adapted to the inherited runtime's command registry, session metadata, auxiliary judge, and gateway continuation queues.
