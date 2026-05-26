---
title: Credential Pools
description: Pool API keys or OAuth tokens for same-provider rotation and rate-limit recovery.
sidebar_label: Credential Pools
sidebar_position: 9
---

# Credential Pools

Credential pools let Superforecasting Agent register multiple API keys or OAuth tokens for the same provider. When one credential hits a rate limit, quota, billing, or auth issue, the runtime rotates to the next healthy credential before falling back to a different provider.

This is same-provider resilience. [Fallback providers](./fallback-providers.md) are cross-provider failover. Pools are tried first; if every credential in the pool is exhausted, fallback can activate.

## How It Works

```text
request
  -> select credential from pool
  -> send provider request
  -> 429 rate limit?
       retry once, then rotate
  -> 402 billing/quota?
       rotate and cool down key
  -> 401 expired OAuth?
       refresh token, then rotate if refresh fails
  -> all credentials exhausted?
       use fallback provider if configured
```

For forecast work, pools are useful for long forecast sessions, scheduled self-checks, domain alert jobs, and batch backtests that need stable same-provider behavior without stopping at the first rate limit.

## Quick Start

If you already have an API key in `.env`, the runtime auto-discovers it as a one-key pool. Add more credentials with `superforecasting-agent auth`:

```bash
superforecasting-agent auth add openrouter --api-key sk-or-v1-your-second-key
superforecasting-agent auth add anthropic --type api-key --api-key sk-ant-api03-your-second-key
superforecasting-agent auth add anthropic --type oauth
```

List pools:

```bash
superforecasting-agent auth list
```

Example:

```text
openrouter (2 credentials):
  #1  OPENROUTER_API_KEY   api_key env:OPENROUTER_API_KEY <-
  #2  backup-key           api_key manual

anthropic (3 credentials):
  #1  superforecasting_pkce oauth   pkce <-
  #2  claude_code          oauth   claude_code
  #3  ANTHROPIC_API_KEY    api_key env:ANTHROPIC_API_KEY
```

The inherited `hermes auth ...` command remains a compatibility alias.

## Interactive Management

```bash
superforecasting-agent auth
```

The wizard can add/remove credentials, reset cooldowns, and set a rotation strategy. Providers that support both API keys and OAuth prompt for the credential type.

## Commands

| Command | Description |
|---------|-------------|
| `superforecasting-agent auth` | Interactive pool manager |
| `superforecasting-agent auth list` | Show all pools |
| `superforecasting-agent auth list <provider>` | Show one provider's pool |
| `superforecasting-agent auth add <provider>` | Add a credential |
| `superforecasting-agent auth add <provider> --type api-key --api-key <key>` | Add an API key non-interactively |
| `superforecasting-agent auth add <provider> --type oauth` | Add an OAuth credential |
| `superforecasting-agent auth remove <provider> <index>` | Remove by 1-based index |
| `superforecasting-agent auth reset <provider>` | Clear cooldown and exhaustion state |

## Rotation Strategies

Configure through the wizard or in `~/.superforecasting-agent/config.yaml`:

```yaml
credential_pool_strategies:
  openrouter: round_robin
  anthropic: least_used
```

| Strategy | Behavior |
|----------|----------|
| `fill_first` | Use the first healthy credential until exhausted |
| `round_robin` | Rotate evenly after each selection |
| `least_used` | Pick the credential with the lowest request count |
| `random` | Pick randomly among healthy credentials |

Legacy `~/.hermes/config.yaml` remains readable during migration.

## Error Recovery

| Error | Behavior | Cooldown |
|-------|----------|----------|
| 429 rate limit | Retry once, then rotate on second consecutive 429 | 1 hour |
| 402 billing/quota | Rotate immediately | 24 hours |
| 401 auth expired | Refresh OAuth token first, rotate if refresh fails | n/a |
| all keys exhausted | Fall through to fallback provider if configured | n/a |

Successful requests reset the transient 429 retry flag.

## Custom Endpoint Pools

Custom OpenAI-compatible endpoints get their own pools keyed by the endpoint name from `custom_providers`.

```bash
superforecasting-agent auth list
superforecasting-agent auth add "Together.ai" --api-key sk-together-second-key
```

Stored keys use a `custom:` prefix in `auth.json`:

```json
{
  "credential_pool": {
    "openrouter": [],
    "custom:together.ai": []
  }
}
```

## Auto-Discovery

Credential pools are seeded from:

| Source | Example | Auto-seeded |
|--------|---------|-------------|
| Environment variables | `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY` | Yes |
| OAuth tokens | Codex, Nous, Anthropic OAuth | Yes |
| Claude Code credentials | `~/.claude/.credentials.json` | Yes |
| Active auth store | `~/.superforecasting-agent/auth.json` | Yes |
| Legacy auth store | `~/.hermes/auth.json` | Yes during migration |
| Custom endpoint config | `model.api_key` | Yes |
| Manual entries | `superforecasting-agent auth add` | Persisted |

Auto-seeded entries update on each pool load. Manual entries are never auto-pruned.

## Delegation and Shared Pools

Delegated workers can receive the parent's credential pool:

- same provider: the child can rotate through the parent's pool
- different provider: the child loads that provider's own pool
- no pool: the child falls back to a single inherited credential

Per-task leasing reduces conflicts when concurrent workers rotate keys.

## Forecasting Guidance

- Use pools to keep same-provider forecast reviews, alert-triggered updates, and backtests running through transient quota issues.
- Use fallback providers when all same-provider credentials are exhausted.
- Record model/provider provenance in snapshots and model runs; credential id normally does not need to be exposed in forecast rationales.
- Avoid relying on pools to hide systematic provider capacity issues in benchmark comparisons.

## Storage

Pool state lives in `~/.superforecasting-agent/auth.json` under `credential_pool`. Legacy `~/.hermes/auth.json` remains readable during migration.

```json
{
  "version": 1,
  "credential_pool": {
    "openrouter": [
      {
        "id": "abc123",
        "label": "OPENROUTER_API_KEY",
        "auth_type": "api_key",
        "priority": 0,
        "source": "env:OPENROUTER_API_KEY",
        "access_token": "sk-or-v1-...",
        "last_status": "ok",
        "request_count": 142
      }
    ]
  }
}
```

Strategies live in `config.yaml`, not `auth.json`.

## Implementation

Key modules:

- `agent/credential_pool.py` — storage, selection, rotation, cooldowns
- `hermes_cli/auth_commands.py` — CLI commands and interactive wizard
- `hermes_cli/runtime_provider.py` — pool-aware credential resolution
- `run_agent.py` — error recovery and fallback handoff
