---
sidebar_position: 1
title: "Tools & Toolsets"
description: "Forecast-desk tools, default tool exposure, and terminal backends"
---

# Tools & Toolsets

Superforecasting Agent uses tools to keep forecasts auditable: it can search,
inspect sources, run local models, write ledger entries, schedule self-checks,
and review prior errors. Toolsets control which capabilities are available to
the agent in each session.

The default CLI product is intentionally narrower than the inherited Hermes
assistant runtime. A new session starts from the `forecast-desk` capability set
instead of exposing every integration by default.

## Available Tools

The forecast desk groups tools by forecasting job rather than by generic agent
feature.

| Forecasting job | Typical tools | Purpose |
|-----------------|---------------|---------|
| Question setup | `forecast_ledger`, `clarify`, `todo` | Create scoreable questions, capture resolution criteria, track assumptions, and keep research work explicit. |
| Research and evidence | `web_search`, `web_extract`, browser tools, file tools | Gather time-stamped evidence, inspect primary sources, snapshot claims, and distinguish facts from assumptions. |
| Quantitative work | `execute_code`, `terminal`, `process`, file tools | Build base-rate tables, run statistical models, compare priors, and reproduce calculations. |
| Forecast updates | `forecast_ledger`, `cronjob` | Append probability updates, schedule stale-forecast checks, and route changed evidence into review queues. |
| Scoring and learning | `forecast_ledger`, `execute_code`, file tools | Resolve questions, compute Brier/log scores, run backtests, write postmortems, and update calibration lessons. |
| External priors | web tools, browser tools, connector plugins | Pull market or platform priors when useful without making any single platform the center of the product. |

:::note
Generic runtime memory remains available for inherited assistant workflows, but
forecast learning should live in the forecast ledger: probabilities, evidence,
model runs, scores, postmortems, calibration lessons, and error profiles.
:::

For code-derived detail, see the [Built-in Tools Reference](../../reference/tools-reference.md)
and [Toolsets Reference](../../reference/toolsets-reference.md).

## Default Tool Exposure

`forecast-desk` is the default toolset for the CLI. It includes the capabilities
needed for forecasting work:

- forecast ledger operations
- web research and browser inspection
- terminal, process, code execution, and file tools
- todo and clarify tools
- cron scheduling for self-checks and alerts

It does not enable broad assistant features by default. Memory-provider tools,
skills marketplace tools, image generation, delegation, messaging delivery,
Home Assistant, Spotify, Discord administration, RL training, and other broad
integrations are opt-in.

Use explicit toolsets when a forecast genuinely needs them:

```bash
# Forecast desk default
superforecasting-agent

# Add a specific connector or inherited capability for one session
superforecasting-agent chat --toolsets "forecast-desk,mcp-myserver"

# Inspect and configure available tools interactively
superforecasting-agent tools
```

The legacy `hermes` command remains accepted for compatibility, but docs and
new workflows prefer `superforecasting-agent`.

## Forecast Workflow Examples

### Research A Question

```bash
forecast new "Will Company X file for bankruptcy before 2027?"
forecast research <id>
forecast evidence add <id> "https://example.com/filing" --source-type url
forecast base-rate <id>
forecast update <id> --probability 0.18
```

The agent should leave an evidence trail for every material probability move:
what changed, when it changed, which source supports it, and how reliable that
source appears to be.

### Run Models

Use terminal or code execution tools for calculations that should be
reproducible.

```bash
forecast model <id>
forecast update <id> --probability 0.42 --rationale "Base-rate model plus new polling evidence"
```

Model output is useful only if the ledger stores the inputs, assumptions,
version, and result. Avoid treating an LLM-written rationale as the probability
engine unless the forecast explicitly records that choice.

### Schedule Self-Checks

```bash
forecast watch add --question <id> rss:https://example.com/news.xml
forecast schedule add --question <id> --cadence 1d --next-run-at 2026-05-22T09:00:00Z
forecast review --stale
```

Scheduled checks should identify stale forecasts, changed evidence, upcoming
close dates, and domains where recent postmortems show recurring mistakes.

## Using Toolsets

Toolsets are named bundles of tools. They can be configured globally, per
platform, or per session.

```bash
# List configured toolsets and setup status
superforecasting-agent tools list

# Configure the default toolsets
superforecasting-agent tools

# Use a specific toolset mix for a one-off session
superforecasting-agent chat --toolsets "forecast-desk,browser,mcp-market-data"
```

Common inherited toolsets include `web`, `search`, `terminal`, `file`,
`browser`, `vision`, `image_gen`, `skills`, `tts`, `todo`, `memory`,
`session_search`, `cronjob`, `code_execution`, `delegation`, `clarify`,
`homeassistant`, `messaging`, `spotify`, `discord`, `debugging`, `safe`, and
`rl`.

See [Toolsets Reference](../../reference/toolsets-reference.md) for the full
set, including platform presets, legacy `hermes-*` presets, and dynamic MCP
toolsets such as `mcp-<server>`.

:::tip Nous Tool Gateway
Paid [Nous Portal](https://portal.nousresearch.com) subscribers can route web
search, image generation, TTS, and browser automation through the Tool Gateway
instead of configuring separate provider keys. Use `superforecasting-agent
model` or `superforecasting-agent tools` to configure it.
:::

## Terminal Backends

The terminal tool can execute commands in different environments. Forecasting
work often benefits from a reproducible sandbox because model runs and
backtests should be repeatable.

| Backend | Description | Use case |
|---------|-------------|----------|
| `local` | Run on your machine | Trusted analysis, local notebooks, quick model runs |
| `docker` | Isolated container | Reproducible research and dependency isolation |
| `ssh` | Remote server | Keep agent execution away from the repo or run larger jobs |
| `singularity` | HPC container | Cluster computing and rootless environments |
| `modal` | Cloud execution | Serverless model jobs |
| `daytona` | Cloud sandbox workspace | Persistent remote development environments |
| `vercel_sandbox` | Vercel Sandbox microVM | Cloud execution with snapshot-backed filesystem persistence |

### Configuration

```yaml
# In ~/.superforecasting-agent/config.yaml
terminal:
  backend: local
  cwd: "."
  timeout: 180
```

Legacy `~/.hermes/config.yaml` profiles remain readable when using compatibility
commands.

### Docker Backend

```yaml
terminal:
  backend: docker
  docker_image: python:3.11-slim
```

The Docker backend starts one persistent container per process and routes
terminal, file, and code-execution calls through that container. Working
directory changes, installed packages, and files written to the workspace carry
over for the lifetime of the process. With persistence enabled, workspace state
can survive restarts.

This is useful for repeated backtests: install dependencies once, run the
benchmark suite, inspect failures, then rerun with changed assumptions.

### SSH Backend

Use SSH when you want stronger separation between the agent and the local
checkout.

```yaml
terminal:
  backend: ssh
```

```bash
# Set credentials in ~/.superforecasting-agent/.env
TERMINAL_SSH_HOST=my-server.example.com
TERMINAL_SSH_USER=myuser
TERMINAL_SSH_KEY=~/.ssh/id_rsa
```

### Container Resources

Configure CPU, memory, disk, and persistence for container backends:

```yaml
terminal:
  backend: docker
  container_cpu: 1
  container_memory: 5120
  container_disk: 51200
  container_persistent: true
```

When `container_persistent: true`, installed packages, generated datasets, and
benchmark outputs can be reused across sessions.

### Container Security

Container backends run with security hardening where the backend supports it:

- read-only root filesystem
- Linux capabilities dropped
- no privilege escalation
- PID limits
- namespace isolation
- persistent workspace volumes instead of writable root layers

Forwarded environment variables are visible inside the container and should be
treated as exposed to that session.

## Background Process Management

Long model runs, data pulls, and backtests can run in the background.

```python
terminal(command="pytest -q tests/forecasting", background=true)
# Returns: {"session_id": "proc_abc123", "pid": 12345}

process(action="list")
process(action="poll", session_id="proc_abc123")
process(action="wait", session_id="proc_abc123")
process(action="log", session_id="proc_abc123")
process(action="kill", session_id="proc_abc123")
```

PTY mode (`pty=true`) enables interactive CLI tools when a workflow needs a real
terminal.

## Sudo Support

If a command needs sudo, the CLI can prompt for a password and cache it for the
session. You can also set `SUDO_PASSWORD` in the profile `.env`, but prefer
keeping forecasting workflows reproducible without privileged commands.

:::warning
Messaging platforms and non-interactive jobs should avoid sudo. A scheduled
self-check that needs elevated privileges is brittle and difficult to audit.
:::
