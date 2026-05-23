---
title: "Nous Tool Gateway"
description: "Route forecast-support tools through Nous Portal when available."
sidebar_label: "Tool Gateway"
sidebar_position: 2
---

# Nous Tool Gateway

The Tool Gateway routes selected forecast-support tools through Nous Portal
instead of requiring a separate vendor key for every backend. It can cover web
search and extraction, image generation, text-to-speech, and cloud browser
automation when those managed tools are available on your account.

The gateway is infrastructure. It does not create ledger records, change
probabilities, resolve questions, score forecasts, or write calibration lessons
by itself. Tool outputs still need to be captured through the forecast workflow
before they become durable evidence or model inputs.

## What It Supports

| Capability | Forecast-desk use |
| --- | --- |
| Web search and extraction | Find source material, inspect articles, collect timestamped evidence candidates. |
| Image generation | Produce secondary visual artifacts for reports or briefs. |
| Text-to-speech | Deliver spoken review alerts, summaries, or approvals. |
| Cloud browser automation | Inspect dynamic pages when structured adapters or static extraction are not enough. |

The exact managed provider list can change. Use `superforecasting-agent tools`
to see the live choices for the active profile.

## Why Use It

Forecasting work often needs several outside services: search, extraction,
browser automation, speech, and media providers. The Tool Gateway lets you use a
single Nous-authenticated managed route for supported tools while preserving
per-tool control.

It is useful when:

- a scheduled self-check needs web search without a local Firecrawl key
- a source-watch workflow needs managed browser automation
- a messaging gateway needs TTS for review alerts
- you want consistent tool provenance across backtests or repeated review jobs
- you want to avoid scattering vendor keys across profiles

Bring-your-own keys remain supported. The gateway is a managed route, not a
lock-in.

## Get Started

Pick Nous Portal as a provider:

```bash
superforecasting-agent model
```

When the selected account has Tool Gateway access, setup offers to enable it for
eligible tools.

You can also configure tools later:

```bash
superforecasting-agent tools
```

Check current routing:

```bash
superforecasting-agent status
```

Example status section:

```text
◆ Nous Tool Gateway
  Nous Portal     yes managed tools available
  Web tools       active via Nous subscription
  Image gen       active via Nous subscription
  TTS             active via Nous subscription
  Browser         active via direct provider key
```

Tools marked as active through the Nous subscription use the gateway. Other
tools use direct keys or local providers.

## Eligibility

Tool Gateway access depends on the active Nous Portal account and subscription
entitlements. If a managed tool is unavailable, configure a direct provider key
with `superforecasting-agent tools` or update the account in
[Nous Portal](https://portal.nousresearch.com).

## Mix And Match

The gateway is configured per tool:

- Route web search through Nous while keeping your own ElevenLabs TTS key.
- Route image generation through Nous while using direct Browserbase or Browser Use credentials.
- Disable the gateway for a tool when you want direct-provider comparability in a benchmark run.
- Keep direct keys in `.env` as fallbacks for profiles that do not use managed routing.

Switch any tool at any time:

```bash
superforecasting-agent tools
```

## Forecast Ledger Boundaries

Gateway tool calls are not scoreable forecast state. Treat them as inputs:

- A web result becomes forecast evidence only after `forecast evidence add`,
  `forecast import`, or an equivalent ledger write.
- A browser observation should include source URL, timestamp, claim type,
  relevance, reliability, and stance before it affects a probability.
- TTS output is delivery only.
- Generated images are report artifacts unless explicitly attached to an export
  or evidence packet.

For backtests, preserve evidence cutoffs. Do not use a live gateway lookup to
fill in facts that would not have been available at the simulated forecast time.

## Image Models

Image generation model availability is controlled by the active image provider.
When using the Tool Gateway, inspect the current managed image list in:

```bash
superforecasting-agent tools
```

Select Image Generation, then choose the managed provider and model for the
profile. The selected model persists in `config.yaml`.

## Configuration Reference

Most users should use `superforecasting-agent model` and
`superforecasting-agent tools`. Edit `config.yaml` directly only for scripted
setup or profile templates.

### Per-Tool `use_gateway`

Each supported tool block can set `use_gateway: true`:

```yaml
web:
  backend: firecrawl
  use_gateway: true

image_gen:
  use_gateway: true

tts:
  provider: openai
  use_gateway: true

browser:
  cloud_provider: browser-use
  use_gateway: true
```

When `use_gateway: true`, the runtime prefers the Nous managed route even if a
direct vendor key is also present. When `use_gateway: false` or absent, the
runtime uses direct keys or local providers according to the selected tool
configuration.

### Disabling The Gateway

```yaml
web:
  use_gateway: false
```

The interactive tools picker clears stale gateway flags when you choose a
direct provider.

### Self-Hosted Or Custom Gateway

Custom deployments can override managed endpoints in the active `.env`:

```bash
TOOL_GATEWAY_DOMAIN=your-domain.example.com
TOOL_GATEWAY_SCHEME=https
TOOL_GATEWAY_USER_TOKEN=your-token
FIRECRAWL_GATEWAY_URL=https://example.com/firecrawl
```

New forecast profiles store this under `~/.superforecasting-agent/.env`.
Legacy `~/.hermes/.env` remains readable during migration.

Regular Nous Portal users should not need these variables.

## FAQ

### Does It Work With Telegram, Discord, Slack, And The API Server?

Yes. Tool Gateway routing happens at the tool-execution layer. Any surface that
can call the configured tool can use the managed route: CLI, TUI, messaging
gateway, scheduled jobs, API server, or dashboard-triggered workflows.

### What Happens If Gateway Access Is Unavailable?

Tools configured with `use_gateway: true` fail until gateway access is restored
or the tool is switched to a direct provider. Use:

```bash
superforecasting-agent tools
```

to choose a direct provider or clear the gateway flag.

### Can I Keep Existing API Keys?

Yes. Keep direct keys in `.env`. `use_gateway: true` selects the managed route
for that tool. Setting `use_gateway: false` lets the direct key take over again.

### Can I See Usage Or Costs?

Use the [Nous Portal dashboard](https://portal.nousresearch.com) for account
usage. For forecast provenance, also record which provider or gateway route
produced evidence, model outputs, or report artifacts when they enter the
ledger.

### Is Modal Included?

Modal terminal execution is separate from the Tool Gateway's web, media, TTS,
and browser routing. Configure terminal backends with:

```bash
superforecasting-agent setup terminal
```

or by editing the terminal section in `config.yaml`.
