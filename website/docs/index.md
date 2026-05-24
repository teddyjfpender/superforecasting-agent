---
slug: /
sidebar_position: 0
title: "Superforecasting Agent Documentation"
description: "A CLI-first forecasting desk that keeps scoreable forecasts, evidence, backtests, calibration memory, and self-checks in an auditable ledger."
hide_table_of_contents: true
displayed_sidebar: docs
---

# Superforecasting Agent

Superforecasting Agent is a command-line forecasting desk built around one durable primitive: the scoreable forecast.

It keeps a standing book of probabilistic beliefs, stores append-only forecast snapshots, links every update to timestamped evidence, runs base-rate and model workflows, scores resolved questions, writes postmortems, and turns past errors into calibration memory.

<div style={{display: 'flex', gap: '1rem', marginBottom: '2rem', flexWrap: 'wrap'}}>
  <a href="/getting-started/quickstart" style={{display: 'inline-block', padding: '0.6rem 1.2rem', backgroundColor: '#FFD700', color: '#07070d', borderRadius: '8px', fontWeight: 600, textDecoration: 'none'}}>Start Forecasting -></a>
  <a href="https://github.com/NousResearch/superforecasting-agent" style={{display: 'inline-block', padding: '0.6rem 1.2rem', border: '1px solid rgba(255,215,0,0.2)', borderRadius: '8px', textDecoration: 'none'}}>View on GitHub</a>
</div>

## Install

```bash
git clone <this-fork-url> superforecasting-agent
cd superforecasting-agent
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[all,dev]"
```

Then open the desk:

```bash
forecast
superforecasting-agent
```

The legacy `hermes` entrypoint remains available during the fork transition, but bare invocation routes to the forecast desk instead of generic chat.

## What It Does

| Capability | Forecast-first behavior |
|---|---|
| Forecast ledger | Create, research, update, resolve, score, postmortem, and export scoreable questions. |
| Evidence trail | Capture sources with availability time, publication time, stance, reliability, relevance, and snapshot metadata. |
| Base rates and models | Store reference classes, Bayesian updates, model runs, ensemble components, and calibration adjustments. |
| Calibration memory | Track Brier/log scores, calibration buckets, sharpness, horizon/domain performance, error profiles, and reusable lessons. |
| Backtesting | Replay held-out resolved questions under evidence cutoffs and compare against market, crowd, base-rate, and naive baselines. |
| Self-checks | Schedule question/domain/topic reviews, watch sources, flag stale assumptions, detect resolved questions, and queue postmortems. |
| Adapters | Import context from RSS/Atom, GDELT, FRED, BLS, World Bank, SEC EDGAR, arXiv, OpenAlex, PubMed, Wikipedia, Wikimedia pageviews, GitHub releases/issues/commits, PyPI, npm, Hacker News, Reddit, Federal Register, CourtListener, NVD, CISA KEV, Open-Meteo, USGS, NASA EONET, NWS alerts, OWID, Metaculus, Manifold, Polymarket, Kalshi, CSV/JSON, and generic URLs. |

## Quick Links

| | |
|---|---|
| **[Quickstart](/getting-started/quickstart)** | Create a question, add evidence, update probability, review, resolve, score, and postmortem. |
| **[Installation](/getting-started/installation)** | Runtime setup and inherited installer details. |
| **[Tester Pilot Runbook](/getting-started/tester-pilot)** | Run a small CLI alpha without confusing smoke evidence for performance proof. |
| **[CLI Reference](/reference/cli-commands)** | Full command inventory, including inherited compatibility commands. |
| **[Configuration](/user-guide/configuration)** | Config files, providers, models, and runtime options. |
| **[Tools & Toolsets](/user-guide/features/tools)** | Tool execution and forecast-desk default tool exposure. |
| **[MCP Integration](/user-guide/features/mcp)** | Connect external tools and data sources. |
| **[Cron Scheduling](/user-guide/features/cron)** | Runtime scheduler used by forecast self-checks. |
| **[Architecture](/developer-guide/architecture)** | Inherited runtime architecture and fork context. |
| **[FAQ & Troubleshooting](/reference/faq)** | Common setup and runtime issues. |

## Core CLI

```bash
forecast status
forecast new "Will X happen?" --resolution-criteria "Resolved by ..."
forecast evidence add <id> <url-or-note>
forecast research <id> <source...>
forecast base-rate <id> ...
forecast model <id> --type bayesian_update ...
forecast update <id> --probability 0.63 --rationale "..."
forecast review --stale
forecast resolve <id> --outcome yes --confirmed
forecast score <id>
forecast postmortem <id>
forecast calibration --by-origin --all
forecast backtest --benchmarks
forecast performance --last 5 --json
```

## TUI Shortcuts

The Ink TUI opens with forecast desk context and routes common workflows directly:

```text
/forecast
/new-forecast
/base-rate
/update-forecast
/resolve
/score
/postmortem
/review
/alerts
/calibration
/lessons
/backtest
/schedule
/performance
```

## Compatibility Notes

This fork still carries substantial inherited runtime code and documentation. Generic chat, skills, messaging gateways, voice, dashboard chat, and broad platform integrations remain available when useful, but they are subordinate to the forecast lifecycle.

Runtime state defaults to `~/.superforecasting-agent` for new installs. Existing `~/.hermes` homes are reused during the fork transition.

## For LLMs and Coding Agents

Machine-readable entry points to this documentation:

- **[`/llms.txt`](/llms.txt)** — curated index of doc pages with short descriptions.
- **[`/llms-full.txt`](/llms-full.txt)** — all doc pages concatenated for one-shot ingestion.
