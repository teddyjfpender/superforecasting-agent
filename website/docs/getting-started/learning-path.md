---
sidebar_position: 3
title: "Learning Path"
description: "Choose a path through the Superforecasting Agent docs."
---

# Learning Path

Superforecasting Agent is a CLI-first forecasting desk. Start with the forecast lifecycle, then add inherited runtime features only when they improve evidence quality, modeling, review cadence, or calibration.

:::tip Start Here
New users should install from the fork, run the [Quickstart](./quickstart.md), and create one scoreable forecast before exploring integrations.
:::

## By Experience Level

| Level | Goal | Recommended Reading | Time |
|---|---|---|---|
| Beginner | Create and maintain one auditable forecast | [Installation](./installation.md) -> [Quickstart](./quickstart.md) -> [CLI Interface](../user-guide/cli.md) -> [Configuration](../user-guide/configuration.md) | ~1 hour |
| Intermediate | Maintain a live book of questions with self-checks | [Features Overview](../user-guide/features/overview.md) -> [Cron](../user-guide/features/cron.md) -> [Tools](../user-guide/features/tools.md) -> [MCP](../user-guide/features/mcp.md) | ~2 hours |
| Advanced | Build forecast adapters, benchmarks, or plugins | [Architecture](../developer-guide/architecture.md) -> [Adding Tools](../developer-guide/adding-tools.md) -> [Creating Skills](../developer-guide/creating-skills.md) -> [Plugins](../user-guide/features/plugins.md) | ~4 hours |

## By Use Case

### "I want to keep a book of forecasts"

Use the forecast ledger as the primary artifact.

1. [Installation](./installation.md)
2. [Quickstart](./quickstart.md)
3. [Tester Pilot Runbook](./tester-pilot.md)
4. [CLI Interface](../user-guide/cli.md)
5. [Configuration](../user-guide/configuration.md)

Focus on `forecast new`, `forecast evidence add`, `forecast base-rate`, `forecast model`, `forecast update`, `forecast review`, `forecast resolve`, `forecast score`, and `forecast postmortem`.

### "I want the agent to learn from errors"

Build the closed feedback loop:

```text
forecast -> observe -> resolve -> score -> diagnose -> recalibrate -> forecast better
```

1. [Quickstart](./quickstart.md)
2. [Features Overview](../user-guide/features/overview.md)
3. [Cron Scheduling](../user-guide/features/cron.md)
4. [Tools](../user-guide/features/tools.md)

Use `forecast calibration`, `forecast errors`, `forecast lessons`, `forecast backtest --benchmarks`, `forecast readiness`, and scheduled self-checks with explicit `--auto-score` or `--auto-postmortem` only when those writes are intended.

### "I want to monitor domains or topics"

Schedule reviews and watched-source alerts rather than relying on memory.

1. [Quickstart](./quickstart.md)
2. [Cron Scheduling](../user-guide/features/cron.md)
3. [MCP Integration](../user-guide/features/mcp.md)
4. [Browser Automation](../user-guide/features/browser.md)

Useful commands:

```bash
forecast watch add --question <id> gdelt:"policy committee vote"
forecast watch add --question <id> fred:UNRATE
forecast watch add --question <id> wikipediapageviews:en.wikipedia.org/Topic
forecast schedule add --domain policy --cadence 1d --auto-score --auto-postmortem
forecast alerts
```

### "I want to import external priors or baselines"

Treat platforms as adapters, not as the center of the product.

1. [Quickstart](./quickstart.md)
2. [Features Overview](../user-guide/features/overview.md)
3. [Tools](../user-guide/features/tools.md)

Supported adapter surfaces include generic URL/file ingest, CSV/JSON data evidence, RSS/Atom, GDELT, FRED, EIA, U.S. Treasury Fiscal Data, BLS, World Bank, IMF DataMapper, SEC EDGAR, arXiv, OpenAlex, Wikipedia, Wikimedia pageviews, GitHub, Hacker News, Reddit, Federal Register, NVD, Open-Meteo, USGS, NASA EONET, NWS alerts, OWID, Metaculus, Manifold, Polymarket, and Kalshi.

### "I want to build a connector or plugin"

Extend the desk with new research inputs, monitors, scoring helpers, or benchmark corpora.

1. [Plugins](../user-guide/features/plugins.md)
2. [Tools Overview](../user-guide/features/tools.md)
3. [MCP Integration](../user-guide/features/mcp.md)
4. [Architecture](../developer-guide/architecture.md)
5. [Adding Tools](../developer-guide/adding-tools.md)

For most new integrations, prefer plugins or MCP servers before editing core. Built-in tools should be reserved for capabilities that belong in the base forecast desk.

### "I need inherited support surfaces"

General chat, messaging gateways, voice, skills, image generation, the embedded Forecast Desk, and IDE surfaces remain available for compatibility. Use them when they support forecasting work, but keep durable beliefs and learning in the forecast ledger.

1. [Features Overview](../user-guide/features/overview.md)
2. [Messaging](../user-guide/messaging/)
3. [Skills](../user-guide/features/skills.md)
4. [Voice Mode](../user-guide/features/voice-mode.md)
5. [IDE Integration](../user-guide/features/acp.md)

## Feature Map

| Feature | Forecasting role | Link |
|---|---|---|
| Forecast ledger | Durable questions, probabilities, evidence, scores, and postmortems | [Quickstart](./quickstart.md) |
| Cron/self-checks | Recurring review, alert, scoring, and learning jobs | [Cron](../user-guide/features/cron.md) |
| Tools | Research, source capture, modeling, and ledger operations | [Tools](../user-guide/features/tools.md) |
| MCP | External data and internal systems | [MCP](../user-guide/features/mcp.md) |
| Browser | Source inspection when adapters are unavailable | [Browser](../user-guide/features/browser.md) |
| Plugins | Custom forecast connectors and workflow extensions | [Plugins](../user-guide/features/plugins.md) |
| Skills | Specialized procedures or domain guides | [Skills](../user-guide/features/skills.md) |
| Memory | Compatibility context; not the forecast learning ledger | [Memory](../user-guide/features/memory.md) |
| Dashboard | Forecast review and observability | [Features](../user-guide/features/overview.md) |

## What To Read Next

- Finished installing: go to the [Quickstart](./quickstart.md).
- Preparing external testers: run the [Tester Pilot Runbook](./tester-pilot.md).
- Created a forecast: read the [CLI Interface](../user-guide/cli.md).
- Tracking many questions: configure [Cron](../user-guide/features/cron.md) and watched sources.
- Building integrations: start with [Plugins](../user-guide/features/plugins.md) and [MCP](../user-guide/features/mcp.md).
- Contributing to the fork: read [Architecture](../developer-guide/architecture.md) and the PRD under `docs/plans/`.
