---
sidebar_position: 99
title: "Honcho Memory"
description: "Use Honcho for persistent recall without replacing the forecast ledger."
---

# Honcho Memory

[Honcho](https://github.com/plastic-labs/honcho) is an optional memory-provider plugin for persistent user and session context. In Superforecasting Agent, it is supporting infrastructure: it can remember preferences, communication style, recurring domains, and session continuity, but it is not the source of truth for forecasts.

The forecast ledger owns scoreable state:

- probabilities and forecast history
- evidence logs and source snapshots
- assumptions and reference classes
- model runs and ensemble components
- resolutions and scores
- postmortems, calibration lessons, and domain/topic error profiles

Honcho can help the forecast desk understand how you like to work. It must not silently replace ledger entries, probability updates, or calibration learning.

:::info Honcho is a Memory Provider Plugin
Honcho is integrated through the [Memory Providers](./memory-providers.md) interface. Enable it only when you want additional conversational recall around the forecast workflow.
:::

## What Honcho Adds

| Capability | Forecast Ledger | Honcho |
|-----------|-----------------|--------|
| Scoreable probabilities | Yes | No |
| Evidence provenance | Yes | No |
| Resolution scoring | Yes | No |
| Calibration lessons | Yes | No |
| User preferences | Limited notes | Yes |
| Session continuity | Transcript/context | Yes |
| Semantic recall | Forecast artifacts | Honcho conclusions |
| Peer/profile separation | Profiles and ledgers | Honcho peers |

Use Honcho for personalization and recall. Use the ledger for anything that must be auditable, scoreable, or learned from after resolution.

## Setup

Run the memory setup wizard and choose Honcho:

```bash
superforecasting-agent memory setup
```

Or configure manually:

```yaml
# ~/.superforecasting-agent/config.yaml
memory:
  provider: honcho
```

Add the API key:

```bash
echo 'HONCHO_API_KEY=***' >> ~/.superforecasting-agent/.env
```

Get an API key at [honcho.dev](https://honcho.dev).

Legacy `~/.hermes/config.yaml`, `~/.hermes/.env`, and `hermes memory setup` remain readable or callable during migration.

## Forecasting Boundary

Honcho memory may be useful for:

- remembering preferred forecast formats
- recalling recurring domains and terminology
- preserving operator preferences across sessions
- improving continuity during long research conversations
- finding prior discussion snippets that should be re-added to the ledger

Honcho memory is not enough for:

- changing a forecast probability
- resolving a question
- scoring a forecast
- updating calibration priors
- recording a domain learning
- proving why a probability changed

When Honcho surfaces useful context, convert it into an explicit ledger artifact before relying on it:

```bash
forecast evidence add <id> --source "honcho-recall" --summary "..."
forecast assumption add <id> "..."
forecast update <id>
```

## Architecture

Honcho assembles optional context for the inherited agent loop:

1. **Base context**: session summary, user representation, user peer card, agent self-representation, and identity card.
2. **Dialectic supplement**: LLM-synthesized reasoning about the user's current state and needs.

Both layers are truncated to the configured token budget before injection. They can guide conversation, but they do not mutate the forecast ledger.

## Configuration

Honcho is configured in `~/.honcho/config.json` globally or `$HERMES_HOME/honcho.json` for profile-local compatibility. `HERMES_HOME` is still the inherited runtime variable; new forecast profiles resolve it to the fork-native home.

Common knobs:

| Key | Default | Description |
|-----|---------|-------------|
| `contextTokens` | `null` | Token budget for injected context |
| `contextCadence` | `1` | Turns between base-context refreshes |
| `dialecticCadence` | `2` | Turns between dialectic refreshes |
| `dialecticDepth` | `1` | Number of dialectic passes, clamped to 1-3 |
| `dialecticReasoningLevel` | `low` | Base reasoning level |
| `recallMode` | `hybrid` | `hybrid`, `context`, or `tools` |
| `writeFrequency` | `async` | Background, turn, session, or every N turns |
| `saveMessages` | `true` | Whether to persist messages to Honcho |
| `sessionStrategy` | `per-directory` | How sessions map to working contexts |

Session strategy:

| Strategy | Behavior |
|----------|----------|
| `per-session` | Fresh Honcho session for each run |
| `per-directory` | One Honcho session per working directory |
| `per-repo` | One Honcho session per git repository |
| `global` | One shared session across directories |

Recall mode:

| Mode | Behavior |
|------|----------|
| `hybrid` | Inject context and expose Honcho tools |
| `context` | Inject context only |
| `tools` | Expose tools only; no automatic injection |

For benchmark runs, scheduled reviews, and calibration comparisons, prefer deterministic settings and document whether Honcho was enabled. Memory injection can change model behavior, so it matters for reproducibility.

## Tools

When Honcho is active as the memory provider, these tools become available:

| Tool | Purpose |
|------|---------|
| `honcho_profile` | Read or update peer cards |
| `honcho_search` | Semantic search over Honcho context |
| `honcho_context` | Session context, summary, representation, card, and messages |
| `honcho_reasoning` | Synthesized Honcho reasoning |
| `honcho_conclude` | Create or delete Honcho conclusions |

Tool output is recall, not evidence. If a Honcho result affects a forecast, copy the relevant claim into the forecast ledger with source and timestamp context.

## CLI Commands

The `honcho` subcommand is registered only when Honcho is the active memory provider.

```bash
superforecasting-agent honcho status
superforecasting-agent honcho setup
superforecasting-agent honcho strategy
superforecasting-agent honcho peer
superforecasting-agent honcho mode
superforecasting-agent honcho tokens
superforecasting-agent honcho identity
superforecasting-agent honcho sync
superforecasting-agent honcho peers
superforecasting-agent honcho sessions
superforecasting-agent honcho map
superforecasting-agent honcho enable
superforecasting-agent honcho disable
superforecasting-agent honcho migrate
```

Legacy `hermes honcho ...` commands remain compatibility aliases.

## Migration

If you previously used the standalone `hermes honcho setup`, no re-login should be required:

1. Keep the existing Honcho API key.
2. Set `memory.provider: honcho` in `~/.superforecasting-agent/config.yaml`.
3. Run `superforecasting-agent memory setup` if you want the wizard to verify the connection.
4. Review your forecast ledger separately; Honcho memory is not imported as scoreable forecast evidence automatically.

See [Memory Providers - Honcho](./memory-providers.md#honcho) for the broader memory-provider reference.
