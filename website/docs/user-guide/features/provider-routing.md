---
title: Provider Routing
description: Configure OpenRouter provider preferences for forecast-runtime reliability and comparability.
sidebar_label: Provider Routing
sidebar_position: 7
---

# Provider Routing

When OpenRouter is your LLM provider, Superforecasting Agent can pass **provider routing** preferences to OpenRouter. This controls which underlying providers handle requests for research, model runs, forecast updates, backtests, and scheduled review jobs.

Provider routing matters for forecasting because model/provider changes can affect calibration, latency, cost, and reproducibility. Record important model choices in forecast snapshots and model-run provenance when they influence probabilities.

## Configuration

Add `provider_routing` to `~/.superforecasting-agent/config.yaml`:

```yaml
provider_routing:
  sort: "price"
  only: []
  ignore: []
  order: []
  require_parameters: false
  data_collection: null
```

Legacy `~/.hermes/config.yaml` remains readable during migration.

Provider routing applies only to OpenRouter. Direct Anthropic, OpenAI, Google, local, or custom endpoints ignore this section.

## Options

### `sort`

Controls how OpenRouter ranks available providers.

| Value | Description |
|-------|-------------|
| `"price"` | Cheapest provider first |
| `"throughput"` | Fastest tokens-per-second first |
| `"latency"` | Lowest time-to-first-token first |

### `only`

Whitelist provider names:

```yaml
provider_routing:
  only:
    - "Anthropic"
    - "Google"
```

Use this when you want forecast runs to stay comparable across a known provider set.

### `ignore`

Blacklist provider names:

```yaml
provider_routing:
  ignore:
    - "Together"
    - "DeepInfra"
```

Use this for privacy, reliability, region, or data-retention constraints.

### `order`

Set a preferred provider order:

```yaml
provider_routing:
  order:
    - "Anthropic"
    - "Google"
    - "AWS Bedrock"
```

Listed providers are tried first; unlisted providers remain fallbacks.

### `require_parameters`

When `true`, OpenRouter uses only providers that support every request parameter, including tools and sampling options:

```yaml
provider_routing:
  require_parameters: true
```

This helps avoid silent behavior changes during forecast workflows.

### `data_collection`

Controls provider data-use preferences:

```yaml
provider_routing:
  data_collection: "deny"
```

Allowed values are `"allow"` and `"deny"`.

## Forecast-Oriented Examples

### Low-Cost Batch Research

```yaml
provider_routing:
  sort: "price"
  require_parameters: true
```

Good for high-volume evidence triage and benchmark exploration where cost matters.

### Low-Latency Review

```yaml
provider_routing:
  sort: "latency"
```

Good for interactive CLI/TUI forecast reviews.

### Provider-Consistent Backtests

```yaml
provider_routing:
  only:
    - "Anthropic"
  require_parameters: true
  data_collection: "deny"
```

Good when you want repeated model runs to be easier to compare.

### Preferred Order with Fallbacks

```yaml
provider_routing:
  order:
    - "Anthropic"
    - "Google"
  require_parameters: true
```

Good when you want a primary provider but still want the session to keep working during outages.

## How It Works

The config maps to OpenRouter's `extra_body.provider` field:

```text
providers_allowed             <- provider_routing.only
providers_ignored             <- provider_routing.ignore
providers_order               <- provider_routing.order
provider_sort                 <- provider_routing.sort
provider_require_parameters   <- provider_routing.require_parameters
provider_data_collection      <- provider_routing.data_collection
```

The same configuration is used by CLI and gateway processes loaded from the active agent home.

## Provider Routing vs. Fallback Models

Provider routing controls which sub-provider handles a request **inside OpenRouter**.

Fallback providers control which entirely different provider/model pair Superforecasting Agent tries when the primary runtime fails. See [Fallback Providers](/user-guide/features/fallback-providers).
