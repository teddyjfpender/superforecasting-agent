---
sidebar_position: 2
title: "Configuration"
description: "Configure Superforecasting Agent profiles, models, tools, ledger state, and runtime options"
---

# Configuration

Superforecasting Agent keeps normal runtime settings in `config.yaml`, secrets
in `.env`, and durable forecasting state in the forecast ledger. The defaults
are designed for the CLI forecast desk: scoreable questions, timestamped
evidence, model runs, scheduled self-checks, calibration lessons, and
postmortems.

New installs use `~/.superforecasting-agent/` by default. Existing
`~/.hermes/` directories remain supported for compatibility, and explicit home
environment variables can point the agent anywhere.

## Directory Structure

```text
~/.superforecasting-agent/
├── config.yaml                 # Non-secret settings
├── .env                        # Secrets only
├── auth.json                   # OAuth provider credentials
├── SOUL.md                     # Primary agent identity
├── forecasting/
│   ├── forecasting.db          # Forecast ledger SQLite database
│   ├── evidence_snapshots/     # Archived source snapshots
│   └── resolution_snapshots/   # Archived resolution-source snapshots
├── cron/                       # Inherited cron jobs
├── sessions/                   # Runtime sessions
├── skills/                     # User skills
├── plugins/                    # User plugins
└── logs/                       # agent.log, errors.log, gateway.log
```

The home path is resolved in this order:

1. `SUPERFORECASTING_AGENT_HOME`
2. `FORECAST_HOME`
3. `HERMES_HOME`
4. `~/.superforecasting-agent` for new installs
5. `~/.hermes` when an existing legacy directory is present

The forecast ledger can be overridden for one command with `forecast --db
<path> ...`, which is useful for isolated benchmark runs or tests.

## Managing Configuration

```bash
superforecasting-agent config
superforecasting-agent config edit
superforecasting-agent config set <key> <value>
superforecasting-agent config check
superforecasting-agent config migrate
superforecasting-agent config path
superforecasting-agent config env-path
```

Examples:

```bash
superforecasting-agent config set model.provider openrouter
superforecasting-agent config set model.default openai/gpt-5.2
superforecasting-agent config set terminal.backend docker
superforecasting-agent config set OPENROUTER_API_KEY sk-or-...
```

`config set` routes known secret keys to `.env`. Non-secret values are written
to `config.yaml`.

Legacy `hermes ...` commands still work, but new docs and examples use
`superforecasting-agent ...` and `forecast ...`.

## Configuration Precedence

Settings are resolved in this order:

1. CLI arguments for the current invocation
2. `config.yaml`
3. `.env` for secrets and legacy environment fallbacks
4. Built-in defaults

Secrets belong in `.env`: API keys, bot tokens, OAuth secrets, SSH passwords,
and service credentials. Runtime policy belongs in `config.yaml`: model
selection, terminal backend, toolsets, compression, display, cron, gateway, and
forecast-desk behavior.

## Environment Variable Substitution

`config.yaml` supports `${VAR_NAME}` substitution:

```yaml
model:
  provider: custom
  base_url: ${LOCAL_MODEL_URL}

auxiliary:
  vision:
    api_key: ${GOOGLE_API_KEY}
```

Only `${VAR}` syntax is expanded. If the variable is missing, the placeholder is
left unchanged so configuration mistakes are visible.

## Forecast Desk Defaults

The default CLI surface is the forecast desk, not general chat.

```yaml
toolsets:
  - forecast-desk
display:
  skin: forecast
agent:
  personality: forecast
```

`forecast-desk` exposes the core capabilities needed for forecasting:

- `forecast_ledger`
- web research and browser inspection
- terminal, process, file, and code execution tools
- todo and clarify tools
- cron scheduling for self-checks and alerts

Broad inherited assistant capabilities are opt-in: generic memory tools,
skills marketplace tools, image/video generation, delegation, outbound
messaging, Home Assistant, Spotify, Discord administration, RL tools, and
wildcard `all` tool exposure.

Secondary runtimes use matching forecast-scoped presets by default. For
example, Telegram starts from `forecast-telegram`, the API server starts from
`forecast-api-server`, and cron starts from `forecast-cron`. Legacy
`hermes-*` presets remain valid for existing configs, but new installs should
prefer the `forecast-*` platform presets unless the broad inherited action
surface is intentional.

## Forecast Ledger State

The ledger is the durable learning system. It stores:

- forecast questions and outcome spaces
- append-only forecast snapshots
- evidence and source snapshots
- assumptions, reference classes, and model runs
- resolutions and corrections
- Brier/log scores and calibration summaries
- postmortems, lessons, and domain/topic error profiles
- scheduled reviews, watched sources, and alerts
- benchmark datasets and backtest runs

Use CLI commands to mutate this state:

```bash
forecast new "Will X happen before 2027?" --resolution-criteria "..."
forecast evidence add <id> "https://example.com/source" --source-type url
forecast update <id> --probability 0.37 --rationale "..."
forecast schedule add --question <id> --cadence 1d --next-run-at 2026-05-22T09:00:00Z
forecast resolve <id> --outcome yes
forecast score <id>
forecast postmortem <id> --lesson "..."
```

Generic runtime memory may still help inherited assistant sessions, but
forecast learning should be written to the ledger so it can be scored,
audited, and revisited.

## Toolsets

The `toolsets` key controls the first layer of tool exposure:

```yaml
toolsets:
  - forecast-desk
```

Use `superforecasting-agent tools` for the interactive tool UI and
`superforecasting-agent tools list` for a text listing.

Examples:

```bash
superforecasting-agent chat --toolsets forecast-desk,mcp-market-data
superforecasting-agent chat --toolsets hermes-cli
```

`hermes-cli` is the legacy full assistant preset. Use it only when the broad
inherited action surface is intentional.

Platform defaults can also be overridden explicitly:

```yaml
platform_toolsets:
  telegram:
    - forecast-telegram
    - mcp-market-data
  api_server:
    - forecast-api-server
```

## Global Toolset Disable

To suppress toolsets across every platform, add them under
`agent.disabled_toolsets`:

```yaml
agent:
  disabled_toolsets:
    - memory
    - image_gen
    - delegation
```

This filter applies after per-platform tool configuration. It is useful for
organizations that want the forecast desk to remain narrow even if a profile or
gateway preset requests broader tools.

## Models

Use `superforecasting-agent model` for interactive provider and model setup.
For direct YAML configuration:

```yaml
model:
  provider: openrouter
  default: openai/gpt-5.2
  base_url: ""
  api_key: ""
  api_mode: chat_completions
```

Provider-specific setup is covered in [AI Providers](../integrations/providers.md).

### Provider Timeouts

Provider-wide and model-specific timeouts can be configured under
`providers.<id>`:

```yaml
providers:
  openrouter:
    request_timeout_seconds: 1800
    stale_timeout_seconds: 300
    models:
      openai/gpt-5.2:
        timeout_seconds: 1800
        stale_timeout_seconds: 300
```

Request timeouts control the API call. Stale timeouts control the non-streaming
detector that flags calls that produce no response for too long.

## Auxiliary Models

Auxiliary tasks are side-model calls for vision, web summaries, browser
screenshots, title generation, compression, and similar work. By default,
`provider: auto` routes them to the main model.

```yaml
auxiliary:
  vision:
    provider: openrouter
    model: google/gemini-2.5-flash
  web_extract:
    provider: openrouter
    model: google/gemini-2.5-flash
  compression:
    provider: auto
    model: ""
```

For forecasting, cheap auxiliary models are often enough for extraction and
summarization. The final probability should still be recorded through the
forecast ledger with model refs, evidence refs, and rationale.

### OpenRouter Routing & Pareto Code For Auxiliary Tasks

OpenRouter request-body overrides can be attached to auxiliary tasks through
`extra_body`:

```yaml
auxiliary:
  compression:
    provider: openrouter
    model: openrouter/auto
    extra_body:
      plugins:
        - id: pareto-code
```

The shape mirrors OpenRouter's request body. Unknown fields are forwarded to
the provider.

## Fallback Model

Fallback routing is configured separately from auxiliary models:

```yaml
fallback_model:
  provider: openrouter
  model: anthropic/claude-sonnet-4.5
```

The fallback is for primary-turn failures. Auxiliary-task overrides are under
`auxiliary.*`.

## Terminal Backend Configuration

Terminal and code-execution tools can run locally or in a sandbox. Forecasting
work benefits from reproducible environments because model runs and backtests
should be repeatable.

```yaml
terminal:
  backend: local
  cwd: "."
  timeout: 180
  env_passthrough: []
```

| Backend | Where commands run | Best for |
|---------|--------------------|----------|
| `local` | Current machine | Trusted analysis and quick local work |
| `docker` | One persistent Docker container | Reproducible modeling and dependency isolation |
| `ssh` | Remote host | Larger jobs or separation from the local repo |
| `modal` | Modal cloud sandbox | Ephemeral cloud compute |
| `daytona` | Daytona workspace | Managed remote dev environments |
| `vercel_sandbox` | Vercel Sandbox microVM | Snapshot-backed cloud execution |
| `singularity` | Singularity/Apptainer container | HPC and rootless environments |

### Local Backend

```yaml
terminal:
  backend: local
```

Local execution has no isolation. The agent has the same filesystem access as
your user account.

### Docker Backend

```yaml
terminal:
  backend: docker
  docker_image: "nikolaik/python-nodejs:python3.11-nodejs20"
  docker_mount_cwd_to_workspace: false
  docker_run_as_host_user: false
  docker_forward_env:
    - "GITHUB_TOKEN"
  docker_volumes:
    - "/home/user/projects:/workspace/projects"
    - "/home/user/data:/data:ro"
  docker_extra_args:
    - "--gpus=all"
  container_cpu: 1
  container_memory: 5120
  container_disk: 51200
  container_persistent: true
```

The Docker backend uses one long-lived container per agent process. Terminal,
file, and code-execution calls route through that container, so installed
packages and files in the workspace persist for the life of the process. With
`container_persistent: true`, workspace state can also survive process restarts.

Use this backend for repeated backtests and model experiments where dependency
state should be stable.

### SSH Backend

```yaml
terminal:
  backend: ssh
  persistent_shell: true
```

Required secrets:

```bash
TERMINAL_SSH_HOST=my-server.example.com
TERMINAL_SSH_USER=ubuntu
TERMINAL_SSH_KEY=~/.ssh/id_rsa
```

SSH uses a persistent shell by default so working directory and environment
state can survive across commands. Commands that require stdin or sudo may fall
back to one-shot mode.

### Modal Backend

```yaml
terminal:
  backend: modal
  container_cpu: 1
  container_memory: 5120
  container_disk: 51200
  container_persistent: true
```

Modal requires `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` or a valid
`~/.modal.toml`.

### Daytona Backend

```yaml
terminal:
  backend: daytona
  container_cpu: 1
  container_memory: 5120
  container_disk: 10240
  container_persistent: true
```

Daytona requires `DAYTONA_API_KEY`.

### Vercel Sandbox Backend

```yaml
terminal:
  backend: vercel_sandbox
  vercel_runtime: node24
  cwd: /vercel/sandbox
  container_persistent: true
  container_disk: 51200
```

Install the optional extra when using Vercel Sandbox:

```bash
pip install 'superforecasting-agent[vercel]'
```

Required secrets are `VERCEL_TOKEN`, `VERCEL_PROJECT_ID`, and
`VERCEL_TEAM_ID`. Short-lived `VERCEL_OIDC_TOKEN` also works for local
one-off sessions.

### Singularity Backend

```yaml
terminal:
  backend: singularity
  singularity_image: "docker://nikolaik/python-nodejs:python3.11-nodejs20"
  container_memory: 5120
```

Singularity/Apptainer is useful on shared clusters where Docker is unavailable.

## Remote Sync

For non-local backends, modified files can be synced back under the agent home:

```text
~/.superforecasting-agent/cache/remote-syncs/<session-id>/
```

Treat this path as the recovery record when a remote sandbox has been torn
down.

## Skill Settings

Skills can declare config keys in `SKILL.md` frontmatter. Those values live
under `skills.config`:

```yaml
skills:
  config:
    myplugin:
      path: ~/myplugin-data
```

Useful commands:

```bash
superforecasting-agent config migrate
superforecasting-agent config set skills.config.myplugin.path ~/myplugin-data
```

Heavy or niche skills should remain optional unless they directly improve
research, modeling, evidence quality, or calibration review.

## Memory

Forecast learning is ledger-first. Generic memory providers are still
available for inherited assistant workflows, but they should not replace
forecast snapshots, score records, postmortems, calibration lessons, or domain
error profiles.

```yaml
memory:
  memory_enabled: false
  provider: ""
```

Enable memory deliberately when a profile needs generic recall outside the
forecast ledger.

## Context Compression

Context compression keeps long sessions inside the model context window.

```yaml
compression:
  enabled: true
  threshold_percent: 80
  target_percent: 45
auxiliary:
  compression:
    provider: auto
    model: ""
```

Compression is a transcript-management feature. It does not summarize or mutate
the forecast ledger; durable forecast facts should be written through forecast
commands.

## Cron And Scheduled Review

Forecast-aware review should use the ledger scheduler:

```bash
forecast schedule add --question <id> --cadence 1d --next-run-at 2026-05-22T09:00:00Z
forecast schedule run --due --auto-score --auto-postmortem
forecast watch add --question <id> gdelt:"central bank rate cut"
```

The inherited `superforecasting-agent cron` command remains available for
ordinary recurring prompts and script-only jobs:

```yaml
cron:
  enabled: true
```

Scheduled forecast jobs should create alerts, evidence, scores, postmortems,
and lessons. They should not silently overwrite active probabilities.

## Display And Logs

```yaml
display:
  skin: forecast
  tool_preview_length: 0
logging:
  level: INFO
```

Logs live under the active agent home:

```text
logs/agent.log
logs/errors.log
logs/gateway.log
```

Use:

```bash
superforecasting-agent logs
superforecasting-agent logs --follow
```

## Gateway Settings

Gateway profiles support messaging integrations, webhooks, and delivery. These
are inherited runtime surfaces and should be enabled only when they improve a
forecast workflow: alerts, scheduled review delivery, team review, or
resolution-source monitoring.

```yaml
gateway:
  enabled: false
```

Use `terminal.cwd` for gateway working directory. Secret platform tokens belong
in `.env`.

## Web Search And Browser

```yaml
web_search:
  provider: auto
browser:
  cdp_url: ""
```

Use source snapshots and evidence refs for claims that move a probability.
Search output alone is not a durable forecast record.

## Website Blocklist

The website blocklist prevents browser and web tools from visiting known-bad
or out-of-scope domains.

```yaml
security:
  website_blocklist:
    enabled: true
    files:
      - "~/.superforecasting-agent/blocked-sites.txt"
    domains:
      - "example.invalid"
```

Use this for organizational policy, source hygiene, or to keep automated
research away from forbidden sites.

## Security Settings

```yaml
security:
  require_approval_for_shell: false
  env_passthrough: []
terminal:
  env_passthrough: []
```

Forwarded environment variables are visible to the tool runtime and should be
treated as exposed to that session. Prefer explicit allowlists.

## Checkpoints

```yaml
checkpoints:
  enabled: false
```

Checkpoints are inherited runtime state. Forecast state remains in the ledger
and should be exported with `forecast export` when a review packet is needed.

## Delegation

```yaml
delegation:
  enabled: false
  provider: auto
  model: ""
  base_url: ""
  api_key: ""
```

Delegation is opt-in. Use it for bounded side research or implementation work,
then write durable forecasting conclusions back to the ledger.

## Project Context

Two context layers are loaded:

| File | Purpose |
|------|---------|
| `SOUL.md` | Primary agent identity from the active agent home |
| `.hermes.md`, `AGENTS.md`, `CLAUDE.md`, `.cursorrules` | Project instructions discovered from the working tree |

For the fork, the default `SOUL.md` is forecast-desk oriented. Project context
should not replace ledger records.

## Working Directory

| Surface | Working directory |
|---------|-------------------|
| CLI | The directory where you launch the command |
| Gateway, cron, scheduled jobs | `terminal.cwd` |
| Forecast ledger | Active agent home, unless `forecast --db` is supplied |

## Common Patterns

### Minimal Local Forecast Desk

```yaml
toolsets:
  - forecast-desk
terminal:
  backend: local
memory:
  memory_enabled: false
```

### Reproducible Research Sandbox

```yaml
toolsets:
  - forecast-desk
terminal:
  backend: docker
  docker_image: "python:3.11-slim"
  container_persistent: true
```

### Team Review With Alerts

```yaml
toolsets:
  - forecast-desk
gateway:
  enabled: true
cron:
  enabled: true
```

Then use ledger-native scheduling:

```bash
forecast schedule add --domain macro --cadence 1d --next-run-at 2026-05-22T09:00:00Z --auto-score --auto-postmortem
forecast watch add --domain macro fred:UNRATE
```
