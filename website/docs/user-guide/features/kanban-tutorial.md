---
title: Kanban Tutorial
description: Walk through forecast-desk Kanban workflows for research, modeling, review, and failure recovery.
---

# Kanban Tutorial

Kanban is task orchestration around the forecast desk. Use it to fan out research, source-adapter work, benchmark preparation, resolver packets, model scripts, and review tasks across profiles. It does not replace the forecast ledger. Worker summaries and task metadata are useful handoffs, but forecast evidence, model runs, probability updates, resolutions, scores, postmortems, and calibration lessons still need explicit ledger writes.

Start with the [Kanban overview](./kanban) if you have not used boards, tasks, runs, assignees, or the dispatcher before.

## Setup

```bash
superforecasting-agent kanban init
superforecasting-agent dashboard
```

Open the Kanban page from the dashboard. The dashboard, CLI, slash command, and worker tools all route through the same per-board SQLite database:

```text
~/.superforecasting-agent/kanban.db
~/.superforecasting-agent/kanban/boards/<slug>/kanban.db
```

Migrated profiles may still use `~/.hermes/kanban.db` and `~/.hermes/kanban/boards/<slug>/kanban.db`.

Throughout this tutorial:

- `bash` blocks are commands you run.
- Python-like blocks marked "worker tool calls" show what spawned workers call internally.
- Any `HERMES_KANBAN_*` name is an inherited runtime environment variable, not the product name.

## Board Columns

Kanban uses six columns:

- Triage: rough tasks or forecast-work ideas.
- Todo: created but blocked by dependencies or assignment.
- Ready: assigned and available for dispatch.
- In progress: claimed by a worker.
- Blocked: waiting for input or tripped by failure handling.
- Done: completed.

Triage can run the decomposer to fan a high-level goal into child tasks routed to specialist profiles. Use auto orchestration when you trust the decomposer; use manual mode when you want explicit control. See [Auto vs Manual orchestration](./kanban#auto-vs-manual-orchestration).

## Story 1: Forecast Research Pipeline

Suppose forecast `142` needs a research refresh before close. Break the work into question review, source search, base-rate modeling, and forecast update review:

```bash
QUESTION=$(superforecasting-agent kanban create "Review forecast 142 criteria" \
    --assignee forecast-researcher --tenant election-2026 --priority 2 \
    --body "Check resolution criteria, close time, ambiguity, and unresolved assumptions." \
    --json | jq -r .id)

SOURCES=$(superforecasting-agent kanban create "Gather fresh evidence for forecast 142" \
    --assignee source-analyst --tenant election-2026 --priority 2 \
    --parent "$QUESTION" \
    --body "Find timestamped primary sources and note reliability, relevance, and stance." \
    --json | jq -r .id)

MODEL=$(superforecasting-agent kanban create "Run base-rate and update model for forecast 142" \
    --assignee quant-researcher --tenant election-2026 --priority 2 \
    --parent "$SOURCES" \
    --body "Estimate base rates and produce a model-run packet for ledger review." \
    --json | jq -r .id)

superforecasting-agent kanban create "Review and update forecast 142" \
    --assignee forecast-reviewer --tenant election-2026 --priority 2 \
    --parent "$MODEL" \
    --body "Compare model output with current forecast, record update if warranted."
```

Only the first task starts as `ready`. Downstream tasks wait until their parents complete. This preserves ordering without forcing one monolithic worker to do every step.

When the first worker runs, it receives `HERMES_KANBAN_TASK=$QUESTION` and uses the worker toolset:

```python
# worker tool calls, not terminal commands
kanban_show()
kanban_complete(
    summary="criteria reviewed; outcome remains binary, close time unchanged, key ambiguity is turnout definition",
    metadata={
        "forecast_id": "142",
        "ledger_actions_needed": ["assumption_review"],
        "open_questions": ["confirm turnout denominator in resolver source"],
    },
)
```

The task handoff is not the ledger update. A follow-up worker or human should record the assumption review through the forecast workflow.

## Story 2: Parallel Evidence Sweep

For a weekly domain self-check, assign independent source checks to different profiles:

```bash
for source in sec fred gdelt arxiv; do
    superforecasting-agent kanban create "Refresh $source evidence watches" \
        --assignee source-analyst --tenant weekly-self-check \
        --body "Check watched $source sources, summarize changes, and identify ledger imports needed."
done

for domain in macro ai-policy public-health; do
    superforecasting-agent kanban create "Review stale forecasts in $domain" \
        --assignee forecast-reviewer --tenant weekly-self-check \
        --body "Find stale active forecasts, note evidence gaps, and propose ledger actions."
done
```

Start the gateway dispatcher:

```bash
superforecasting-agent gateway start
```

Each worker can complete independently. Use task metadata to record source ids, changed feeds, and recommended ledger actions. Use the forecast CLI or tool to actually import evidence, update forecasts, or record learning.

## Story 3: Reviewer-Gated Model Script

A quant worker writes a model script, but a reviewer must inspect it before the model run is trusted.

```python
# worker tool calls
kanban_show()
kanban_comment(
    body="review-required",
    metadata={
        "changed_files": ["models/forecast_142_base_rate.py"],
        "tests_run": ["pytest tests/forecasting/test_models.py"],
        "ledger_candidate": {
            "forecast_id": "142",
            "model_type": "base_rate",
            "requires_review": True
        },
    },
)
kanban_block(reason="review-required: model script ready, needs assumptions and leakage check")
```

The reviewer can add comments and unblock:

```bash
superforecasting-agent kanban unblock "$MODEL"
```

The next worker run sees the prior block reason and comments through `kanban_show()`. If approved, record the model run in the ledger with inputs, parameters, output, code version, and reviewer note.

## Story 4: Circuit Breaker and Crash Recovery

Workers fail. A profile can have missing credentials, a source can rate-limit, or a model script can run out of memory.

Create a task with bounded retries:

```bash
superforecasting-agent kanban create "Import SEC filings for forecast 188" \
    --assignee source-analyst --tenant credit-risk \
    --max-retries 3
```

If the worker cannot spawn or repeatedly fails, the circuit breaker moves the task to `blocked` with a failure outcome such as `gave_up`. Inspect attempts:

```bash
superforecasting-agent kanban runs <task-id>
```

If a worker process dies mid-flight, the dispatcher can reclaim the task and retry it. The next worker sees prior attempts in `kanban_show()` and can choose a safer approach.

## Structured Handoff

Every completed or blocked run should include useful summary and metadata. Downstream workers receive:

- prior attempts on the current task
- parent task summaries and metadata
- comments and block reasons
- relevant run status and errors

For forecast workflows, good metadata includes:

- `forecast_id`
- source ids or URLs inspected
- evidence candidates requiring ledger import
- model files, parameters, and tests
- assumptions needing review
- resolver or scoring notes
- recommended next ledger action

Avoid treating metadata as final forecast state. It is a handoff channel.

## Useful Commands

```bash
superforecasting-agent kanban show <task-id>
superforecasting-agent kanban runs <task-id>
superforecasting-agent kanban watch --kinds completed,gave_up,timed_out
superforecasting-agent kanban notify-subscribe <task-id> --platform telegram --chat-id <id>
```

The inherited `hermes kanban ...` command remains a compatibility alias for migrated installs.

## Next Steps

- [Kanban overview](./kanban) for the full data model, event vocabulary, and CLI reference.
- [Kanban worker lanes](./kanban-worker-lanes) for worker-lane contracts.
- [Forecast schedule and review commands](./cron) for scheduled self-checks that should write through the ledger.
