---
sidebar_position: 15
title: "Subscription Proxy"
description: "Expose OAuth-backed model access as a local OpenAI-compatible endpoint."
---

# Subscription Proxy

The subscription proxy is a local HTTP server for external apps that already speak the OpenAI-compatible API. It attaches a fresh OAuth or subscription credential from your Superforecasting Agent auth store, forwards the request to the upstream provider, and streams the raw model response back.

Treat it as infrastructure, not as the forecast desk. It does not run the agent loop, does not call tools, does not write the forecast ledger, and does not update calibration memory.

Use it when a separate app needs raw inference through a subscription credential. Use the CLI forecast workflow when the work needs evidence provenance, forecast snapshots, scheduled review, scoring, or postmortems.

## Proxy Versus Forecast Desk

| | Forecast CLI/API server | Subscription proxy |
|---|---|---|
| Main purpose | Forecast lifecycle, tools, ledger, review | Raw model inference for external clients |
| Typical command | `forecast research <id>` or `forecast update <id>` | `superforecasting-agent proxy start` |
| Ledger writes | Yes | No |
| Tool calls | Yes | No |
| Evidence snapshots | Yes, when run through forecast workflows | No |
| Calibration learning | Yes, after resolution/review | No |
| Client auth | Runtime/API configuration | Any bearer accepted by the proxy |

If an external app produces useful forecasting material through the proxy, import or summarize that material into the relevant forecast evidence log explicitly. The proxy will not do that automatically.

## Quick Start

### 1. Authenticate with the upstream provider

For Nous Portal:

```bash
superforecasting-agent auth add nous --type oauth
```

For xAI Grok OAuth:

```bash
superforecasting-agent auth add xai-oauth --type oauth
```

Tokens are stored in `~/.superforecasting-agent/auth.json`. Legacy `~/.hermes/auth.json` remains readable during migration.

Some inherited runtime paths still accept `superforecasting-agent login nous`; prefer `superforecasting-agent auth add nous --type oauth` in new forecast-desk setups.

### 2. Start the proxy

```bash
superforecasting-agent proxy start
```

Example startup output:

```text
Starting Superforecasting Agent proxy for Nous Portal
  Listening on:  http://127.0.0.1:8645/v1
  Forwarding to: (resolved per-request from your subscription)
  Use any bearer token in the client - the proxy attaches your real credential.
```

Select a provider explicitly when needed:

```bash
superforecasting-agent proxy start --provider xai
```

### 3. Point the external app at it

Use the local endpoint as the app's OpenAI-compatible base URL:

```text
Base URL:   http://127.0.0.1:8645/v1
API key:    any-non-empty-string
Model:      Hermes-4-70B
```

`Hermes-4-70B`, `Hermes-4.3-36B`, and similar names are upstream model names. They are not product identifiers for the forecast fork.

The proxy ignores the client's bearer token and attaches the real upstream credential. Refresh happens automatically when the stored bearer approaches expiry.

## Available Providers

```bash
superforecasting-agent proxy providers
```

Currently shipped adapters include:

| Provider | Purpose |
|----------|---------|
| `nous` | Nous Portal subscription access |
| `xai` | xAI Grok OAuth access |

Adapters live under `superforecasting_agent/runtime/proxy/adapters/`; that module path is inherited compatibility naming.

## Check Status

```bash
superforecasting-agent proxy status
```

Example:

```text
Superforecasting Agent proxy upstream adapters

  [nous    ] Nous Portal - ready (bearer expires 2026-05-15T06:43:21Z)
```

If a provider is not logged in, run the matching `superforecasting-agent auth add ...` command. If credentials need attention, the refresh token may have been revoked; authenticate again to clear the local quarantine state.

## Allowed Paths

The proxy forwards only the paths supported by the selected upstream adapter.

For Nous Portal:

| Path | Purpose |
|------|---------|
| `/v1/chat/completions` | Chat completions, streaming and non-streaming |
| `/v1/completions` | Legacy text completions |
| `/v1/embeddings` | Embeddings |
| `/v1/models` | Model list |

Other paths return `404` with the allowed path list. This keeps stray clients from sending unsupported requests to the upstream.

## Forecasting Use Cases

Good uses:

- Run a separate notebook, local summarizer, or context database through the same subscription credential.
- Generate embeddings or draft summaries for material that you will later import into a forecast evidence log.
- Give a local app temporary model access without copying long-lived upstream API keys into that app.

Poor uses:

- Producing the final probability for a forecast.
- Running scheduled self-checks without ledger writes.
- Backtesting without scoreable forecast snapshots.
- Letting an external app create evidence summaries that are never linked to a forecast.

For scoreable work, run the forecast CLI instead:

```bash
forecast research <id>
forecast update <id>
forecast review --stale
forecast backtest run <suite>
```

## Example External Clients

Any OpenAI-compatible client can use the same pattern:

```text
OPENAI_API_BASE_URL=http://127.0.0.1:8645/v1
OPENAI_API_KEY=any-non-empty-string
INFERENCE_TEXT_MODEL=Hermes-4-70B
```

This works for tools such as Open WebUI, Karakeep, local notebooks, or custom scripts. The client remains responsible for its own state; Superforecasting Agent only supplies the upstream credential and transport.

## Exposing on LAN

By default the proxy binds to localhost:

```bash
superforecasting-agent proxy start --host 127.0.0.1 --port 8645
```

To expose it to other machines:

```bash
superforecasting-agent proxy start --host 0.0.0.0 --port 8645
```

Anyone who can reach the proxy can spend the upstream subscription quota because the proxy accepts any bearer token from the client. Use a firewall, VPN, or authenticated reverse proxy before exposing it beyond a trusted machine.

## Rate Limits And Provenance

The upstream provider's rate limits apply to all traffic through the proxy. The proxy does not fan out across providers and does not perform forecast-aware credential selection.

For forecast audits, record proxy-produced material as external evidence or a model run only after importing it through the forecast workflow. Include the upstream provider, model, prompt or summary source, and the import time so later review can distinguish proxy output from forecast-desk reasoning.

## Architecture

Per request:

1. Receive a request under `/v1/...` from the external client.
2. Ask the selected adapter for a current credential, refreshing if needed.
3. Forward the request body with `Authorization: Bearer <upstream-token>`.
4. Stream the upstream response back unchanged.

There is no request-body logging, no forecast ledger write, no memory update, no tool dispatch, and no agent loop.

## Extending The Proxy

New upstreams implement `UpstreamAdapter` in `superforecasting_agent/runtime/proxy/adapters/<provider>.py` and register through `superforecasting_agent/runtime/proxy/adapters/__init__.py`.

Providers that are not OpenAI-compatible at the protocol level need a transformation layer before they can be used through this proxy. Keep that layer separate from forecast scoring and calibration logic so raw inference transport does not become an untracked forecast workflow.
