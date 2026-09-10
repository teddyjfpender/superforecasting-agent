---
sidebar_position: 1
title: "Architecture"
description: "Superforecasting Agent internals, forecast ledger, and inherited runtime surfaces."
---

# Architecture

Superforecasting Agent is a fork of Hermes Agent, but the fork is organized around one product primitive: the scoreable forecast. The inherited agent runtime, tools, gateway, TUI, dashboard, and plugin systems remain useful infrastructure; the primary product flow is the creation, maintenance, review, resolution, scoring, and calibration of forecast questions.

Use this page to orient yourself before editing the codebase. When a decision is ambiguous, prefer the forecast desk over the general assistant surface.

## System Overview

```text
┌──────────────────────────────────────────────────────────────────────┐
│                         Product Entry Points                          │
│                                                                      │
│  forecast CLI     superforecasting-agent     TUI     Dashboard       │
│                                                                      │
│  API server, gateway, ACP, plugins, and cron remain supporting        │
│  surfaces when they improve evidence capture, review, or alerts.      │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         Forecasting Core                              │
│                                                                      │
│  ForecastLedger    Dashboard Summary    Protocol Prompts             │
│  Evidence Log      Source Adapters      Model Runs                   │
│  Snapshots         Schedules/Alerts     Benchmarks                   │
│  Resolutions       Scoring              Calibration Lessons          │
│  Postmortems       Domain Error Memory  Extension Registry           │
└───────────────┬───────────────────────────────┬──────────────────────┘
                │                               │
                ▼                               ▼
┌──────────────────────────────┐    ┌──────────────────────────────────┐
│ Agent-Facing Forecast Tool    │    │ Inherited Runtime Infrastructure │
│ tools/forecasting_tool.py     │    │ run_agent.py, superforecasting_agent/tooling/runtime.py,    │
│                               │    │ cli.py, tui_gateway/, gateway/,  │
│ create/update/research/score  │    │ cron/, plugins/, superforecasting_agent/tooling/toolsets.py     │
│ resolve/postmortem/backtest   │    │                                  │
│ schedule/watch/review         │    │ provider routing, tools, auth,   │
│                               │    │ sessions, approvals, MCP, files  │
└──────────────────────────────┘    └──────────────────────────────────┘
```

The main architectural change from upstream Hermes is persistence. A general assistant can answer and move on. This fork has to maintain standing beliefs, detect stale beliefs, update from new evidence, score itself after resolution, and turn misses into calibration lessons.

## Directory Structure

```text
superforecasting-agent/
├── forecasting/                  # Forecast desk domain package
│   ├── cli.py                    # `forecast ...` lifecycle commands
│   ├── ledger.py                 # durable forecast ledger and review state
│   ├── models.py                 # forecast/question/evidence/scoring models
│   ├── scoring.py                # Brier/log/proper-score helpers
│   ├── calibration.py            # calibration reports and buckets
│   ├── learning.py               # active lessons and update adjustments
│   ├── dashboard.py              # shared CLI/TUI/web forecast summaries
│   ├── protocol.py               # forecast-scoped agent prompt protocol
│   ├── source_adapters.py        # market/news/economic/fiscal/research adapters
│   ├── benchmarks.py             # replay datasets and baseline comparison
│   ├── extensions.py             # adapter/importer extension registry
│   └── data/                     # packaged benchmark corpora
│
├── superforecasting_agent/       # fork-native public package namespace
│   ├── __main__.py               # `python -m superforecasting_agent`
│   └── cli.py                    # fork-native command dispatch
│
├── tools/
│   ├── forecasting_tool.py       # model-callable forecast ledger tool
│   ├── registry.py               # inherited tool registry
│   └── environments/             # terminal backends
│
├── run_agent.py                  # inherited AIAgent conversation loop
├── superforecasting_agent/tooling/runtime.py                # inherited tool schema and dispatch plumbing
├── superforecasting_agent/tooling/toolsets.py                   # forecast-desk default plus compatibility toolsets
├── cli.py                        # classic interactive CLI, forecast-scoped by default
├── superforecasting_agent/constants.py           # fork-native home aliases plus legacy compatibility
├── superforecasting_agent/storage/session.py               # inherited SQLite session store
│
├── superforecasting_agent/runtime/                   # runtime subcommands, setup, auth, profiles
├── ui-tui/                       # Ink TUI, with forecast dashboard/status panels
├── tui_gateway/                  # Python JSON-RPC backend for the TUI
├── web/                          # browser dashboard, Forecasts-first routing
├── gateway/                      # messaging/API gateway, secondary surface
├── cron/                         # inherited scheduler, used for self-check bridges
├── plugins/                      # provider, memory, context, and general plugins
├── skills/                       # bundled inherited skills
├── optional-skills/              # opt-in inherited skills
├── website/                      # Docusaurus docs
└── tests/                        # pytest, Vitest, and docs guards
```

Names such as `superforecasting_agent.runtime`, `HERMES_HOME`, and `X-Hermes-*` still exist because large parts of the runtime are inherited and external clients already depend on those identifiers. User-facing docs and commands should prefer `superforecasting-agent`, `forecast`, `SUPERFORECASTING_AGENT_HOME`, and `~/.superforecasting-agent`, while documenting legacy names as compatibility.

## Forecast Data Flow

### CLI Forecast Lifecycle

```text
forecast new
  → ForecastLedger.create_question()
  → durable ForecastQuestion with resolution criteria and review cadence

forecast research
  → evidence/source adapters or manual notes
  → timestamped evidence records and optional source snapshots

forecast base-rate / forecast model
  → reference classes or quantitative model runs
  → auditable model-run records

forecast update
  → append-only forecast snapshot
  → cited rationale, assumptions, evidence cutoff, model/source provenance

forecast resolve / score / postmortem
  → resolution provenance
  → score records
  → calibration lessons and domain/topic error memory
```

### Agent-Assisted Forecasting

```text
User prompt in CLI/TUI/API
  → forecast-scoped system prompt from forecasting.protocol
  → inherited AIAgent loop in run_agent.py
  → narrowed forecast-desk toolset by default
  → forecast_ledger tool calls
  → append-only ledger writes
  → final response summarizes ledger-backed state
```

The LLM should be useful for decomposition, evidence search, argument generation, source synthesis, and postmortems. It should not silently become the final probability engine. Probabilities should be auditable through ledger snapshots, model runs, base rates, market baselines, calibration adjustments, and cited evidence.

### Scheduled Self-Checks

```text
forecast schedule add --domain economics --topic inflation --auto-score --auto-postmortem
  → durable review schedule
  → cron/no-agent bridge or forecast schedule run
  → stale forecast and watched-source checks
  → alerts, optional scoring, optional postmortems
  → active lessons and error profiles update
```

This is the closed feedback loop the fork needs:

```text
forecast → observe → update → resolve → score → diagnose → recalibrate → forecast better
```

## Main Subsystems

### Forecast Ledger

`forecasting/ledger.py` is the durable source of truth. It stores questions, evidence, assumptions, reference classes, forecast snapshots, model runs, watched sources, schedules, alerts, resolutions, scores, postmortems, calibration lessons, and domain/topic error profiles.

Important properties:

- Forecast snapshots are append-only.
- Every probability display carries an `as_of` timestamp.
- Evidence can carry source type, reliability, publication time, availability time, relevance, stance, claim type, and source snapshots.
- Resolution and scoring can be gated by trusted resolver policies and criteria satisfaction.
- Postmortems are first-class learning records, not chat summaries.

### Forecast CLI

`forecasting/cli.py` is the primary product surface. The top-level `forecast` command opens the shared forecast dashboard by default, then exposes lifecycle commands such as:

```text
forecast new
forecast research
forecast base-rate
forecast model
forecast update
forecast review
forecast alerts
forecast resolve
forecast score
forecast postmortem
forecast calibration
forecast performance
forecast backtest
forecast schedule
forecast self-check
```

The `superforecasting-agent` command delegates forecast shorthand to this CLI while preserving inherited runtime commands for setup, auth, profiles, dashboard, gateway, tools, plugins, and similar surfaces.

### Forecast Dashboard Summary

`forecasting/dashboard.py` produces shared summary data for the CLI, TUI, and browser dashboard. It covers active forecasts, stale review queues, alerts, calibration health, learning memory, domain/topic error profiles, recent backtests, and paired baseline wins/losses.

The browser dashboard and TUI should reuse this shared summary rather than inventing separate forecast state.

### Forecast Protocol

`forecasting/protocol.py` defines the forecast-scoped system prompt that is injected into classic chat, oneshot, and TUI agent construction. It keeps free-form chat tied to evidence, base rates, assumptions, model runs, probability updates, scoring, and postmortems.

When extending chat behavior, preserve the rule that forecast state belongs in the ledger. Chat memory and session recall are supporting context, not the learning system.

### Forecast Tool

`tools/forecasting_tool.py` exposes the ledger to the agent loop. It lets model calls create questions, add evidence, update forecasts, manage assumptions/reference classes, record model runs, resolve, score, write postmortems, run backtests, inspect calibration/error memory, schedule reviews, watch sources, and acknowledge alerts.

This is the main bridge between the inherited tool-calling runtime and the forecast desk.

### Source Adapters and Extensions

`forecasting/source_adapters.py` contains read-only import and watch surfaces for market priors, economic and fiscal data, news, research papers, generic URLs, generic CSV/JSON, and benchmark datasets. `forecasting/extensions.py` registers those adapters so the CLI can list and use them without making Metaculus or any single platform the product center.

Adapters should timestamp what they saw, preserve source provenance, and distinguish imported baselines from the agent's own forecasts.

### Scoring, Calibration, and Learning

Scoring and calibration are the fork's feedback engine:

- binary and categorical Brier scores
- numeric/distributional proper scores
- log score where applicable
- calibration reports by bucket, domain, horizon, and origin
- domain/topic error profiles
- structured postmortems
- active calibration lessons
- benchmark and baseline comparison

The important invariant is that learning is scoreable. A lesson should point back to a resolved forecast, score, postmortem, or correction.

### Inherited Agent Runtime

`run_agent.py`, `superforecasting_agent/tooling/runtime.py`, `superforecasting_agent/tooling/toolsets.py`, `cli.py`, `superforecasting_agent/runtime/`, `gateway/`, `tui_gateway/`, and the plugin system are inherited runtime infrastructure. They still provide:

- provider and model routing
- tool schemas and dispatch
- terminal, browser, file, web, MCP, and process tools
- credential handling
- sessions and transcripts
- approvals and callbacks
- profiles
- plugins and skills
- messaging/API/ACP surfaces

Treat these as supporting capabilities. Default exposure should stay narrow through the `forecast-desk` toolset; broad assistant behavior should be explicit opt-in compatibility.

## Recommended Reading Order

If you are new to the fork:

1. `docs/plans/2026-05-20-superforecasting-agent-fork-prd.md`
2. `docs/plans/2026-05-20-superforecasting-agent-fork-context.md`
3. `forecasting/ledger.py`
4. `forecasting/cli.py`
5. `tools/forecasting_tool.py`
6. `forecasting/protocol.py`
7. `forecasting/dashboard.py`
8. `superforecasting_agent/tooling/toolsets.py`
9. `run_agent.py`
10. `tui_gateway/server.py`, `ui-tui/src/app/forecastPanel.ts`, and `web/src/pages/ForecastsPage.tsx`

Then read inherited subsystem docs as needed:

- [Agent Loop Internals](./agent-loop.md)
- [Prompt Assembly](./prompt-assembly.md)
- [Provider Runtime Resolution](./provider-runtime.md)
- [Tools Runtime](./tools-runtime.md)
- [Session Storage](./session-storage.md)
- [Gateway Internals](./gateway-internals.md)
- [Context Compression & Prompt Caching](./context-compression-and-caching.md)
- [ACP Internals](./acp-internals.md)

## Design Principles

| Principle | What it means in this fork |
|-----------|----------------------------|
| **Ledger first** | Durable forecast state belongs in the forecast ledger, not only in chat/session memory. |
| **Append-only belief history** | Probability updates create snapshots with rationale, citations, provenance, and `as_of` timestamps. |
| **Strict source handling** | Evidence records track time, source, reliability, relevance, stance, claim type, and snapshots where possible. |
| **Scoreable learning** | Resolutions lead to scores, postmortems, lessons, and calibration/error-memory updates. |
| **Baseline discipline** | Imported crowd/market/model priors are labeled as baselines and compared against agent forecasts. |
| **Forecast-desk defaults** | CLI/TUI/chat defaults should expose forecasting tools first and keep broad inherited tools opt-in. |
| **Compatibility is explicit** | Legacy Hermes command names, headers, env vars, and paths may remain, but should be documented as compatibility. |
| **Shared renderers** | CLI, TUI, and web should reuse shared forecast summary state wherever practical. |

## File Dependency Chain

```text
tools/registry.py
       ↑
tools/*.py, including tools/forecasting_tool.py
       ↑
superforecasting_agent/tooling/runtime.py
       ↑
run_agent.py, cli.py, tui_gateway/server.py, gateway/, superforecasting_agent/trajectories/batch.py
```

Tool registration still happens at import time, before any agent instance is created. Adding a new forecast-facing tool action normally means editing `tools/forecasting_tool.py`, the ledger or adapter it calls, and focused tests under `tests/forecasting/`.

For most new forecast behavior, prefer a ledger method, CLI command, source adapter, or plugin extension before changing the inherited general assistant runtime.
