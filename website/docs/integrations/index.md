---
title: "Integrations"
sidebar_label: "Overview"
sidebar_position: 0
---

# Integrations

Superforecasting Agent connects to external systems so the forecast desk can gather current evidence, run domain models, preserve audit trails, and trigger review when beliefs go stale. The main product remains the CLI forecasting workflow; integrations are useful when they improve research quality, probability estimation, scoring, calibration, or alerting.

Not every inherited Hermes integration is equally central to the fork. AI providers, web/source acquisition, MCP data connectors, plugins, cron, and evaluation workflows are forecast-critical. Messaging, voice, IDE, API, and home automation integrations are secondary surfaces unless they support a forecasting workflow such as alerts, handoffs, or source capture.

## Forecast Integration Map

| Forecasting need | Primary integrations | Role |
|------------------|----------------------|------|
| Model inference and routing | AI providers, provider routing, fallback providers | Run decomposition, evidence synthesis, structured judgment, and auxiliary extraction reliably. |
| Current evidence | Web search, web extraction, browser automation, MCP servers | Pull timestamped source material, inspect pages, and collect facts that can be attached to the forecast ledger. |
| Domain data and models | MCP servers, plugins, browser automation, terminal tools | Connect to market data, APIs, databases, spreadsheets, notebooks, or custom model runners. |
| Review and alerting | Cron, messaging gateways, webhooks | Re-check stale forecasts, monitor source changes, and notify when assumptions need updates. |
| Learning loop | Memory providers, batch processing, plugins | Store reusable domain lessons, run backtests, and compare model variants against resolved questions. |

## AI Providers & Routing

Superforecasting Agent supports multiple inference providers out of the box. Use `superforecasting-agent model` to configure them interactively, or set them in `config.yaml`.

- **[AI Providers](/user-guide/features/provider-routing)** — OpenRouter, Anthropic, OpenAI, Google, and any OpenAI-compatible endpoint. The runtime auto-detects capabilities like vision, streaming, and tool use per provider.
- **[Provider Routing](/user-guide/features/provider-routing)** — Fine-grained control over which underlying providers handle your OpenRouter requests. Use routing to separate high-judgment forecast synthesis from cheaper extraction and summarization work.
- **[Fallback Providers](/user-guide/features/fallback-providers)** — Automatic failover to backup LLM providers when your primary model encounters errors. Includes primary model fallback and independent auxiliary task fallback for vision, compression, and web extraction.

## Evidence & Source Acquisition

The forecast CLI has a source-adapter inventory:

```bash
forecast sources
forecast sources --json
```

Use it to discover built-in imports and watched-source prefixes for news,
economic, fiscal, demographic, regional, and market price data, filings, papers, reference data, software releases, policy and legal
documents, CVEs, weather forecasts and alerts, geophysical and natural-hazard
event data, public datasets, markets, and generic files.

### Web Search Backends

The `web_search` and `web_extract` tools support four backend providers, configured via `config.yaml` or `superforecasting-agent tools`:

| Backend | Env Var | Search | Extract | Crawl |
|---------|---------|--------|---------|-------|
| **Firecrawl** (default) | `FIRECRAWL_API_KEY` | ✔ | ✔ | ✔ |
| **Parallel** | `PARALLEL_API_KEY` | ✔ | ✔ | — |
| **Tavily** | `TAVILY_API_KEY` | ✔ | ✔ | ✔ |
| **Exa** | `EXA_API_KEY` | ✔ | ✔ | — |

Quick setup example:

```yaml
web:
  backend: firecrawl    # firecrawl | parallel | tavily | exa
```

If `web.backend` is not set, the backend is auto-detected from whichever API key is available. Self-hosted Firecrawl is also supported via `FIRECRAWL_API_URL`.

### Browser Automation

Browser automation is useful when a forecast depends on pages that require interaction, filtering, or inspection beyond simple extraction:

- **Browserbase** — Managed cloud browsers with anti-bot tooling, CAPTCHA solving, and residential proxies
- **Browser Use** — Alternative cloud browser provider
- **Local Chromium-family CDP** — Connect to your running Chrome, Brave, Chromium, or Edge browser using `/browser connect`
- **Local Chromium** — Headless local browser via the `agent-browser` CLI

See [Browser Automation](/user-guide/features/browser) for setup and usage.

### Tool Servers (MCP)

- **[MCP Servers](/user-guide/features/mcp)** — Connect Superforecasting Agent to external tool servers via Model Context Protocol. Access GitHub, databases, file systems, browser stacks, internal APIs, data warehouses, and custom source systems without writing native tools. Supports both stdio and SSE transports, per-server tool filtering, and capability-aware resource/prompt registration.

## Plugins & Custom Connectors

- **[Plugin System](/user-guide/features/plugins)** — Extend the forecast desk with custom tools, lifecycle hooks, CLI commands, source adapters, model runners, and review workflows without modifying core code. Plugins are discovered from `~/.superforecasting-agent/plugins/`, legacy `~/.hermes/plugins/`, project-local `.hermes/plugins/`, and pip-installed entry points.
- **[Build a Plugin](/guides/build-a-superforecasting-agent-plugin)** — The plugin authoring guide covers tools, hooks, and CLI commands that can be used to add forecasting-specific connectors.

Good plugin candidates include market-data connectors, policy trackers, source reliability scorers, evidence snapshotters, reference-class builders, and domain-specific model runners.

## Review, Alerts & Automation

- **[Cron](/user-guide/features/cron)** — Schedule stale-forecast checks, domain watchlists, recurring evidence scans, calibration reviews, and post-resolution learning jobs.
- **[Webhooks](/user-guide/messaging/webhooks)** — Trigger forecast review or evidence capture from external systems.
- **Messaging platforms** — Deliver alerts, review reminders, and forecast summaries where a team already works.

## Memory, Backtesting & Evaluation

- **[Built-in Memory](/user-guide/features/memory)** — Support persistent lessons and user preferences via `MEMORY.md` and `USER.md` files. Forecast probabilities, evidence, scores, and resolutions belong in the forecast ledger, not ordinary chat memory.
- **[Memory Providers](/user-guide/features/memory-providers)** — Plug in external memory backends for deeper retrieval of domain lessons and prior mistakes. Eight providers are supported: Honcho, OpenViking, Mem0, Hindsight, Holographic, RetainDB, ByteRover, and Supermemory.
- **[Batch Processing](/user-guide/features/batch-processing)** — Run the agent across many prompts in parallel for backtesting, evaluation, or structured trajectory generation.

The closed learning loop is forecast -> observe -> resolve -> score -> diagnose -> recalibrate. Integrations should feed that loop instead of becoming standalone chat surfaces.

## Messaging Platforms

Superforecasting Agent can run inherited gateway bots on 19+ messaging platforms, all configured through the same `gateway` subsystem. Treat these as alert and collaboration channels for the CLI forecast desk rather than the primary product surface.

- **[Telegram](/user-guide/messaging/telegram)**, **[Discord](/user-guide/messaging/discord)**, **[Slack](/user-guide/messaging/slack)**, **[WhatsApp](/user-guide/messaging/whatsapp)**, **[Signal](/user-guide/messaging/signal)**, **[Matrix](/user-guide/messaging/matrix)**, **[Mattermost](/user-guide/messaging/mattermost)**, **[Email](/user-guide/messaging/email)**, **[SMS](/user-guide/messaging/sms)**, **[DingTalk](/user-guide/messaging/dingtalk)**, **[Feishu/Lark](/user-guide/messaging/feishu)**, **[WeCom](/user-guide/messaging/wecom)**, **[WeCom Callback](/user-guide/messaging/wecom-callback)**, **[Weixin](/user-guide/messaging/weixin)**, **[BlueBubbles](/user-guide/messaging/bluebubbles)**, **[QQ Bot](/user-guide/messaging/qqbot)**, **[Yuanbao](/user-guide/messaging/yuanbao)**, **[Home Assistant](/user-guide/messaging/homeassistant)**, **[Microsoft Teams](/user-guide/messaging/teams)**, **[Webhooks](/user-guide/messaging/webhooks)**

See the [Messaging Gateway overview](/user-guide/messaging) for the platform comparison table and setup guide.

## Secondary Inherited Surfaces

- **[IDE Integration (ACP)](/user-guide/features/acp)** — Use Superforecasting Agent inside ACP-compatible editors such as VS Code, Zed, and JetBrains when code, notebooks, or model artifacts are part of the forecasting workflow.
- **[API Server](/user-guide/features/api-server)** — Expose Superforecasting Agent as an OpenAI-compatible HTTP endpoint. This is useful for internal tools that need forecast-desk capabilities through an API.
- **[Voice & TTS](/user-guide/features/tts)** and **[Voice Mode](/user-guide/features/voice-mode)** — Speech-to-text and text-to-speech remain available for messaging workflows, but they are not core to the forecast lifecycle.
- **[Home Assistant](/user-guide/messaging/homeassistant)** — Home automation remains available through the inherited gateway/toolset, but it is secondary unless it supports a concrete forecasting or alerting workflow.
