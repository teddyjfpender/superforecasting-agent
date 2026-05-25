---
title: Fallback Providers
description: Configure model failover for forecast-runtime continuity.
sidebar_label: Fallback Providers
sidebar_position: 8
---

# Fallback Providers

Superforecasting Agent has several resilience layers for model outages, quota exhaustion, and provider-specific failures:

1. **[Credential pools](./credential-pools.md)** rotate keys for the same provider.
2. **Primary model fallback** switches to another provider/model for the current turn.
3. **Auxiliary task fallback** gives side tasks their own provider chains.
4. **Per-job overrides** let scheduled forecast work use a fixed provider/model.

Fallback keeps research and review workflows moving, but it can also change output quality and calibration. Important model/provider switches should be captured in forecast snapshots, model runs, backtests, or postmortems when they influence a probability.

## Primary Model Fallback

When the main provider fails, the runtime can switch to a configured backup provider/model for the current turn without losing research-session context.

Configure interactively:

```bash
superforecasting-agent fallback
```

The inherited `hermes fallback` command remains available where compatibility entry points are installed.

Or edit `~/.superforecasting-agent/config.yaml`:

```yaml
fallback_model:
  provider: openrouter
  model: anthropic/claude-sonnet-4
```

Both `provider` and `model` are required. Legacy `~/.hermes/config.yaml` is still readable during migration.

### `fallback_model` vs. `fallback_providers`

`fallback_model` is the inherited single-fallback key. `fallback_providers` supports a list tried in order:

```yaml
fallback_providers:
  - provider: openrouter
    model: anthropic/claude-sonnet-4
  - provider: gemini
    model: gemini-3-pro
```

The interactive fallback manager writes `fallback_providers`. When both keys are set, the runtime merges them with `fallback_providers` taking priority.

## Trigger Conditions

Fallback activates after the primary model fails with conditions such as:

- rate limits after retries
- server errors after retries
- authentication or permission failures
- model-not-found errors
- repeated malformed or empty responses

When triggered, the runtime resolves fallback credentials, builds a new client, swaps provider/model for that turn, resets retry state, and continues.

Fallback is **turn-scoped**. The next user message starts with the primary model again. This protects comparability and avoids silently turning a whole forecasting session into a different model run.

## Forecasting Guidance

Use fallback deliberately:

- For interactive research, fallback is usually fine.
- For saved forecast updates, record the actual model/provider in snapshot provenance.
- For benchmark runs, prefer fixed provider/model settings so results are comparable.
- For scheduled self-checks, prefer explicit provider/model choices on the job when repeatability matters.
- For postmortems, note provider switches if they may have affected judgment quality.

## Examples

### OpenRouter Fallback for Native Anthropic

```yaml
model:
  provider: anthropic
  default: claude-sonnet-4-6

fallback_model:
  provider: openrouter
  model: anthropic/claude-sonnet-4
```

### Local Model Fallback

```yaml
fallback_model:
  provider: custom
  model: llama-3.1-70b
  base_url: http://localhost:8000/v1
  key_env: LOCAL_API_KEY
```

### Multiple Fallbacks

```yaml
fallback_providers:
  - provider: openrouter
    model: anthropic/claude-sonnet-4
  - provider: custom
    model: local-qwen
    base_url: http://localhost:8000/v1
    key_env: LOCAL_API_KEY
```

## Supported Provider Values

Common values include:

| Provider | Value | Typical setup |
|----------|-------|---------------|
| OpenRouter | `openrouter` | `OPENROUTER_API_KEY` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` or Claude Code credentials |
| Google AI Studio | `gemini` | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| Nous Portal | `nous` | `superforecasting-agent auth` OAuth |
| OpenAI Codex | `openai-codex` | `superforecasting-agent model` OAuth |
| GitHub Copilot | `copilot` | GitHub/Copilot token |
| xAI | `xai` or `grok` | `XAI_API_KEY` |
| xAI OAuth | `xai-oauth` or `grok-oauth` | `superforecasting-agent model` OAuth |
| AWS Bedrock | `bedrock` | Standard boto3 auth |
| Microsoft Foundry | `azure-foundry` | `AZURE_FOUNDRY_API_KEY` and `AZURE_FOUNDRY_BASE_URL` |
| Local/custom | `custom` | `base_url` and optional `key_env` |

The provider registry also supports additional plugin-backed providers listed in [AI Providers](/integrations/providers).

## Where Primary Fallback Applies

| Context | Primary fallback |
|---------|------------------|
| CLI sessions | Yes |
| TUI sessions | Yes |
| Messaging gateway sessions | Yes |
| API server research sessions | Yes |
| Subagent delegation | No; use delegation provider overrides |
| Cron jobs | No; use per-job provider/model overrides |
| Auxiliary tasks | No; use auxiliary fallback chains |

## Auxiliary Task Fallback

Auxiliary tasks have independent provider resolution. These tasks support `auxiliary.<task>` config:

| Task | Purpose | Config key |
|------|---------|------------|
| Vision | Image analysis and screenshots | `auxiliary.vision` |
| Web Extract | Web page extraction/summarization | `auxiliary.web_extract` |
| Compression | Context compression summaries | `auxiliary.compression` |
| Skills Hub | Skill search/discovery | `auxiliary.skills_hub` |
| MCP | MCP helper operations | `auxiliary.mcp` |
| Approval | Command-approval classification | `auxiliary.approval` |
| Title Generation | Session titles | `auxiliary.title_generation` |
| Goal Judge | `/goal` done/continue verdicts | `auxiliary.goal_judge` |
| Triage Specifier | Kanban triage/spec expansion | `auxiliary.triage_specifier` |

Example:

```yaml
auxiliary:
  web_extract:
    provider: openrouter
    model: google/gemini-3-flash-preview

  compression:
    provider: main
    model: google/gemini-3-flash-preview
```

For custom endpoints:

```yaml
auxiliary:
  vision:
    base_url: "http://localhost:1234/v1"
    api_key: "local-key"
    model: "qwen2.5-vl"
```

`base_url` bypasses provider resolution. It uses the configured `api_key`, falling back to `OPENAI_API_KEY`; it does not reuse `OPENROUTER_API_KEY`.

## Auxiliary Capacity Fallback

If an explicit auxiliary provider cannot serve a request because of payment, daily-quota exhaustion, or connection failure, the runtime can fall back through:

1. the configured auxiliary provider
2. `auxiliary.<task>.fallback_chain`, if set
3. the main provider/model
4. warning and re-raising the original error

Example:

```yaml
auxiliary:
  vision:
    provider: gemini
    model: gemini-3-flash-preview
    fallback_chain:
      - provider: openrouter
        model: google/gemini-3-flash-preview
      - provider: anthropic
        model: claude-sonnet-4-6
```

Transient `Retry-After` rate limits are treated as request constraints, not capacity exhaustion.

## Context Compression

Context compression uses `auxiliary.compression`:

```yaml
auxiliary:
  compression:
    provider: "auto"
    model: "google/gemini-3-flash-preview"
```

Older `compression.summary_model`, `compression.summary_provider`, and `compression.summary_base_url` keys are migrated to `auxiliary.compression.*` on config load.

If no compression provider is available, the runtime drops middle research-session turns without generating a summary rather than failing the session. Forecast state remains in the ledger.

## Delegation and Cron

Delegated subagents do not use primary fallback. Route them explicitly:

```yaml
delegation:
  provider: "openrouter"
  model: "google/gemini-3-flash-preview"
```

Cron jobs also do not use primary fallback. Set provider/model on the job when you need a specific forecast-review runtime:

```python
cronjob(
    action="create",
    schedule="every 2h",
    prompt="Run stale forecast review for the macro profile",
    provider="openrouter",
    model="google/gemini-3-flash-preview"
)
```

For ledger-native recurring reviews, prefer `forecast schedule`.

## Summary

| Surface | Fallback mechanism | Config |
|---------|--------------------|--------|
| Main model | Per-turn primary fallback | `fallback_model` / `fallback_providers` |
| Auxiliary auto tasks | Auto provider chain | `auxiliary.<task>.provider: auto` |
| Auxiliary explicit tasks | `fallback_chain` -> main model -> error | `auxiliary.<task>.fallback_chain` |
| Compression | Auxiliary compression chain, then no-summary degradation | `auxiliary.compression` |
| Delegation | Provider override only | `delegation.provider` / `delegation.model` |
| Cron | Per-job provider/model only | job `provider` / `model` |
