---
sidebar_position: 4
title: "Memory Providers"
description: "External recall plugins for user, project, and domain context."
---

# Memory Providers

Superforecasting Agent can use external memory provider plugins for persistent recall across sessions. These providers can remember user preferences, project context, domain notes, recurring workflows, and prior discussion context.

They are not the forecast ledger. Forecast questions, probabilities, evidence, assumptions, model runs, source snapshots, resolutions, scores, postmortems, calibration lessons, and domain error profiles must remain in the ledger so they are auditable, append-only, and scoreable.

Only one external memory provider can be active at a time. Built-in local memory can still run alongside it, but both are auxiliary to the forecast ledger.

## Quick Start

```bash
superforecasting-agent memory setup
superforecasting-agent memory status
superforecasting-agent memory off
```

You can also select the active memory provider through:

```bash
superforecasting-agent plugins
```

or configure it directly in `~/.superforecasting-agent/config.yaml`:

```yaml
memory:
  provider: openviking
```

Supported provider ids:

```text
honcho, openviking, mem0, hindsight, holographic, retaindb, byterover, supermemory
```

Legacy `hermes memory ...`, `hermes plugins`, and `~/.hermes/config.yaml` remain compatibility surfaces for migrated installs.

## Forecast-Ledger Boundary

Use memory providers for recall and context:

- user preferences and communication style
- domain-specific vocabulary and recurring sources
- project conventions and repository notes
- reminders about previous analysis approaches
- summaries of earlier research sessions

Do not use memory providers as the source of truth for:

- current probabilities
- evidence logs
- model-run provenance
- resolution criteria or resolver outcomes
- scoring records
- postmortems and calibration corrections
- backtest results
- domain error profiles

When recalled context matters to a forecast, convert it into an explicit ledger entry with timestamp, source, reliability, relevance, and rationale.

## How It Works

When a provider is active, the runtime can:

1. Prefetch relevant memories before a turn.
2. Inject provider context into the prompt.
3. Sync research-session turns after responses.
4. Extract memories at session end when the provider supports it.
5. Mirror built-in memory writes to the external provider.
6. Add provider-specific tools for search, store, and management.

This context can improve continuity, but it is probabilistically noisy. Treat recalled memories as prompts to investigate, not as verified evidence.

## Available Providers

### Honcho

Honcho provides AI-native cross-session user modeling, session-scoped context injection, semantic search, and persistent conclusions.

| | |
|---|---|
| Best for | Multi-profile context, user alignment, and dialectic recall |
| Requires | `honcho-ai` plus a Honcho Cloud API key or self-hosted Honcho |
| Storage | Honcho Cloud or self-hosted |
| Forecast role | Recall around workflows, preferences, domain notes, and prior discussion context |

Tools include `honcho_profile`, `honcho_search`, `honcho_context`, `honcho_reasoning`, and `honcho_conclude`.

Setup:

```bash
superforecasting-agent memory setup
```

Select `honcho`. The inherited `hermes honcho setup` command remains a compatibility redirect after Honcho is active.

Profile-local config is stored in the active forecast home, for example:

```text
~/.superforecasting-agent/honcho.json
```

Legacy config paths such as `$HERMES_HOME/honcho.json` and `~/.hermes/honcho.json` remain readable during migration because `HERMES_HOME` is still the inherited runtime variable.

See [Honcho](./honcho.md) for the forecast-specific setup and ledger-boundary guide.

#### Multi-Profile Honcho

Honcho models research-session interaction streams as peers in a workspace. A typical setup has one user peer plus one forecaster peer per profile. For example, a `macro` profile and a `software` profile can share a user workspace while building separate forecaster-peer context.

Create a cloned profile with a new peer:

```bash
superforecasting-agent profile create macro --clone
```

Backfill peer entries for existing profiles:

```bash
superforecasting-agent honcho sync
```

Legacy profile host keys such as `hermes` and `hermes.<profile>` may appear in existing `honcho.json` files. Keep them during migration unless you intentionally re-map server-side peer identity.

### OpenViking

OpenViking is a self-hosted context database with a filesystem-style knowledge hierarchy, tiered retrieval, and automatic extraction categories.

| | |
|---|---|
| Best for | Self-hosted structured knowledge browsing |
| Requires | `openviking` package plus a running OpenViking server |
| Storage | Self-hosted |
| Forecast role | Domain notes, source catalogs, and reusable reference material |

Tools include `viking_search`, `viking_read`, `viking_browse`, `viking_remember`, and `viking_add_resource`.

Setup:

```bash
pip install openviking
openviking-server
superforecasting-agent memory setup
```

Manual configuration:

```bash
superforecasting-agent config set memory.provider openviking
```

Set `OPENVIKING_ENDPOINT` in `~/.superforecasting-agent/.env`.

### Mem0

Mem0 provides server-side fact extraction, semantic search, reranking, and deduplication.

| | |
|---|---|
| Best for | Hands-off recall extraction |
| Requires | `mem0ai` plus a Mem0 API key |
| Storage | Mem0 Cloud |
| Forecast role | User preferences, recurring project facts, and non-ledger context |

Tools include `mem0_profile`, `mem0_search`, and `mem0_conclude`.

Setup:

```bash
superforecasting-agent memory setup
```

Manual configuration:

```bash
superforecasting-agent config set memory.provider mem0
```

Store `MEM0_API_KEY` in `~/.superforecasting-agent/.env`.

### Hindsight

Hindsight provides long-term memory with a knowledge graph, entity resolution, multi-strategy retrieval, and cross-memory synthesis through `hindsight_reflect`.

| | |
|---|---|
| Best for | Entity-rich recall and knowledge-graph workflows |
| Requires | Hindsight Cloud API key or local Hindsight dependencies |
| Storage | Hindsight Cloud or local embedded PostgreSQL |
| Forecast role | Relationship-heavy domain context and prior discussion recall |

Tools include `hindsight_retain`, `hindsight_recall`, and `hindsight_reflect`.

Setup:

```bash
superforecasting-agent memory setup
```

Manual configuration:

```bash
superforecasting-agent config set memory.provider hindsight
```

Store `HINDSIGHT_API_KEY` in `~/.superforecasting-agent/.env` for cloud mode.

### Holographic

Holographic is a local SQLite fact store with FTS5 search, trust scoring, and optional HRR algebra for compositional queries.

| | |
|---|---|
| Best for | Local-only recall with no cloud dependency |
| Requires | SQLite; NumPy optional for HRR algebra |
| Storage | Local SQLite |
| Forecast role | Local project facts and reusable non-ledger notes |

Tools include `fact_store` and `fact_feedback`.

Setup:

```bash
superforecasting-agent memory setup
```

Manual configuration:

```bash
superforecasting-agent config set memory.provider holographic
```

Local database paths are profile-scoped. New installs should prefer `~/.superforecasting-agent`; migrated configs may still refer to `$HERMES_HOME/memory_store.db`.

### RetainDB

RetainDB provides cloud memory with hybrid search, memory types, and compressed context deltas.

| | |
|---|---|
| Best for | Teams already using RetainDB infrastructure |
| Requires | RetainDB account and API key |
| Storage | RetainDB Cloud |
| Forecast role | Team recall and shared non-ledger context |

Tools include `retaindb_profile`, `retaindb_search`, `retaindb_context`, `retaindb_remember`, and `retaindb_forget`.

Setup:

```bash
superforecasting-agent memory setup
```

Manual configuration:

```bash
superforecasting-agent config set memory.provider retaindb
```

Store `RETAINDB_API_KEY` in `~/.superforecasting-agent/.env`.

### ByteRover

ByteRover provides persistent memory through the `brv` CLI with a hierarchical knowledge tree, tiered retrieval, and optional cloud sync.

| | |
|---|---|
| Best for | Portable local-first recall with a CLI |
| Requires | ByteRover CLI |
| Storage | Local by default, optional ByteRover Cloud sync |
| Forecast role | Project conventions, domain notes, and pre-compression recall |

Tools include `brv_query`, `brv_curate`, and `brv_status`.

Setup:

```bash
curl -fsSL https://byterover.dev/install.sh | sh
superforecasting-agent memory setup
```

Manual configuration:

```bash
superforecasting-agent config set memory.provider byterover
```

Knowledge trees are profile-scoped. New installs should prefer `~/.superforecasting-agent/byterover/`; migrated configs may still refer to `$HERMES_HOME/byterover/`.

### Supermemory

Supermemory provides semantic recall, profile context, explicit memory tools, and optional session-end ingest through the Supermemory graph API.

| | |
|---|---|
| Best for | Semantic recall with user profiling |
| Requires | `supermemory` package plus API key |
| Storage | Supermemory Cloud |
| Forecast role | Profile facts and reusable non-ledger research-session context |

Tools include `supermemory_store`, `supermemory_search`, `supermemory_forget`, and `supermemory_profile`.

Setup:

```bash
superforecasting-agent memory setup
```

Manual configuration:

```bash
superforecasting-agent config set memory.provider supermemory
```

Store `SUPERMEMORY_API_KEY` in `~/.superforecasting-agent/.env`.

Container tags can be profile-scoped. Existing tags such as `hermes` or `hermes-{identity}` may remain in migrated configurations; use new tags only when you intentionally migrate provider-side data.

## Provider Comparison

| Provider | Storage | Tools | Forecast-desk fit |
|----------|---------|-------|-------------------|
| Honcho | Cloud or self-hosted | 5 | User/profile modeling and dialectic recall |
| OpenViking | Self-hosted | 5 | Structured knowledge trees and source catalogs |
| Mem0 | Cloud | 3 | Hands-off fact extraction |
| Hindsight | Cloud or local | 3 | Entity graph recall and synthesis |
| Holographic | Local | 2 | Local fact store with trust scoring |
| RetainDB | Cloud | 5 | Team memory infrastructure |
| ByteRover | Local or cloud | 3 | Portable local-first project recall |
| Supermemory | Cloud | 4 | Semantic profile and research-session recall |

## Profile Isolation

Each provider should be scoped by forecast profile:

- Local providers store data under the active home, usually `~/.superforecasting-agent/`.
- Config-file providers store config in the active home.
- Cloud providers should use profile-specific workspace, project, bank, or container identifiers when supported.
- Env-var providers read credentials from the active profile's `.env`.

Legacy `$HERMES_HOME` and `~/.hermes` paths remain compatibility inputs. New forecast profiles should prefer `SUPERFORECASTING_AGENT_HOME`, `FORECAST_HOME`, and `~/.superforecasting-agent`.

## Building a Memory Provider

See [Developer Guide: Memory Provider Plugins](/developer-guide/memory-provider-plugin) to create a provider plugin.

Provider plugins should expose recall and context capabilities. They should not bypass the forecast ledger for evidence, forecasts, scores, resolutions, postmortems, or calibration learning.
