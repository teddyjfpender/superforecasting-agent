---
title: "Features Overview"
sidebar_label: "Overview"
sidebar_position: 1
---

# Features Overview

Superforecasting Agent is organized around one durable object: the scoreable forecast. The inherited agent runtime is still useful, but the default product path is a forecasting desk that keeps probabilities, evidence, assumptions, models, scores, postmortems, and calibration memory in one auditable loop.

## Forecasting Desk

- **Forecast ledger** - Create, update, resolve, score, export, and postmortem questions with append-only probability history.
- **Evidence log** - Attach notes, URLs, files, CSV/JSON rows, news articles, economic data, filings, research papers, and market/crowd baselines with timestamps and source metadata.
- **Base rates and models** - Store reference classes, model runs, Bayesian updates, ensemble components, and calibration adjustments beside the question they influenced.
- **Calibration memory** - Track Brier score, log score, sharpness, domain/topic error patterns, horizon performance, and active lessons from resolved forecasts.
- **Backtesting** - Replay resolved questions under evidence cutoffs and compare the forecast engine against naive, market, crowd, base-rate, and imported baselines.
- **Self-checks and alerts** - Schedule reviews by question, domain, topic, or portfolio; watch sources; detect stale assumptions; and create alerts without silently overwriting probabilities.

## Research Inputs

- **[Tools & Toolsets](tools.md)** - The default forecast desk toolset narrows broad tool exposure toward research, evidence capture, source inspection, modeling, and ledger writes.
- **[MCP Integration](mcp.md)** - Connect databases, data vendors, internal tools, and external APIs through Model Context Protocol servers.
- **[Browser Automation](browser.md)** - Inspect web sources and collect context when a structured adapter is not available.
- **[Context References](context-references.md)** - Inject files, directories, diffs, and URLs into a forecasting workflow with `@` references.
- **[Code Execution](code-execution.md)** - Run local analysis scripts or small probability models that call agent tools through the sandboxed execution path.

## Workflow Automation

- **[Scheduled Tasks (Cron)](cron.md)** - Run recurring self-checks, benchmark reports, stale-forecast reviews, or source-watch scans.
- **[Event Hooks](hooks.md)** - Add observability, policy checks, logging, or custom forecast-review hooks at lifecycle points.
- **[Batch Processing](batch-processing.md)** - Run structured prompts or benchmark cases in bulk for evaluation and regression data.
- **[Subagent Delegation](delegation.md)** - Use parallel workers for bounded research tasks when a forecasting workflow needs independent source review.

## Compatibility Runtime

- **[Skills System](skills.md)** - Skills remain available when they improve research, modeling, source handling, or report production.
- **[Persistent Memory](memory.md)** - Generic memory is inherited; durable learning for forecasting should live in the forecast ledger, scores, postmortems, and calibration lessons.
- **[Memory Providers](memory-providers.md)** - External memory backends can still be used for user/project context, but forecast learning should remain provenance-aware.
- **[Provider Routing](provider-routing.md)** - Route model calls by cost, latency, and quality for research, summarization, structured judgment, and auxiliary tasks.
- **[Fallback Providers](fallback-providers.md)** - Fail over across providers so scheduled reviews and forecast workflows can keep running.
- **[Credential Pools](credential-pools.md)** - Rotate provider credentials for reliability under rate limits.

## Interfaces

- **CLI desk** - `forecast` and `superforecasting-agent` open the forecast lifecycle rather than generic chat.
- **TUI** - Common desk actions are available through shortcuts such as `/new-forecast`, `/base-rate`, `/update-forecast`, `/resolve`, `/score`, `/postmortem`, `/calibration`, `/lessons`, `/backtest`, and `/schedule`.
- **Dashboard** - The web shell lands on the Forecasts page first; embedded chat is a supporting surface.
- **[API Server](api-server.md)** and **[IDE Integration (ACP)](acp.md)** - Inherited surfaces remain available for compatibility and specialized workflows.

## Customization

- **[Plugins](plugins.md)** - Add forecast-specific tools, data connectors, source monitors, scoring helpers, or model adapters without modifying core code.
- **[Skins & Themes](skins.md)** - Customize terminal visual presentation while keeping the forecast desk workflow intact.
- **[Personality & SOUL.md](personality.md)** - New profiles default to a forecasting-desk role; custom identities should preserve evidence discipline, scoring, and calibration behavior.
