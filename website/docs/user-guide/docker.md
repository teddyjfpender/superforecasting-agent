---
sidebar_position: 7
title: "Docker"
description: "Run Superforecasting Agent in Docker and use Docker as a terminal backend."
---

# Superforecasting Agent — Docker

Docker supports two different workflows:

1. **Run the forecast desk in Docker** — the agent, gateway, dashboard, cron scheduler, source connectors, and forecast ledger run inside a container.
2. **Use Docker as a terminal backend** — the agent runs on your host but executes `terminal` and `execute_code` calls inside a persistent sandbox container. See [Configuration -> Docker Backend](./configuration.md#docker-backend).

This page focuses on the first workflow. The container stores all user data in a host-mounted directory at `/opt/data`: configuration, API keys, sessions, forecast ledger state, calibration reports, skills, source snapshots, cron jobs, and logs. The image itself is disposable; keep the mounted data directory backed up.

:::note Compatibility internals
The Docker image still keeps inherited internal paths such as `/opt/hermes` and supports legacy variables such as `HERMES_HOME` and `HERMES_DASHBOARD`. Treat those as compatibility identifiers. New deployments should prefer `~/.superforecasting-agent`, `superforecasting-agent`, `forecast`, `SUPERFORECASTING_AGENT_HOME`, and `SUPERFORECASTING_AGENT_DASHBOARD`.
:::

## Quick Start

Create a host data directory and run setup:

```sh
mkdir -p ~/.superforecasting-agent
docker run -it --rm \
  -v ~/.superforecasting-agent:/opt/data \
  nousresearch/superforecasting-agent setup
```

Setup prompts for model credentials and writes secrets to `/opt/data/.env` inside the container, which maps to `~/.superforecasting-agent/.env` on the host. Existing `~/.hermes` directories can still be mounted during migration, but new deployments should use the fork-native home.

## Running the Forecast Desk

For long-running forecast work, run the gateway and scheduler-capable runtime in the background:

```sh
docker run -d \
  --name superforecasting-agent \
  --restart unless-stopped \
  -v ~/.superforecasting-agent:/opt/data \
  -p 8642:8642 \
  nousresearch/superforecasting-agent gateway run
```

Port `8642` exposes the [OpenAI-compatible API server](./features/api-server.md) and health endpoint when enabled. It is optional for pure CLI or chat-platform operation, but useful for automation that submits forecast questions, exports ledger data, or drives review jobs.

To expose the API server outside the container, set an API key and bind host:

```sh
docker run -d \
  --name superforecasting-agent \
  --restart unless-stopped \
  -v ~/.superforecasting-agent:/opt/data \
  -p 8642:8642 \
  -e API_SERVER_ENABLED=true \
  -e API_SERVER_HOST=0.0.0.0 \
  -e API_SERVER_KEY=your_api_key_here \
  -e API_SERVER_CORS_ORIGINS='*' \
  nousresearch/superforecasting-agent gateway run
```

Opening a forecasting API on an internet-facing machine can expose private research, source notes, credentials, and forecast rationales. Put it behind a trusted network, reverse proxy, or VPN unless you intentionally want remote access.

## Dashboard

The dashboard can run as an optional side process in the same container as the gateway. It is useful for inspecting sessions, active forecasts, source activity, and operational status, but the CLI remains the primary product surface.

```sh
docker run -d \
  --name superforecasting-agent \
  --restart unless-stopped \
  -v ~/.superforecasting-agent:/opt/data \
  -p 8642:8642 \
  -p 9119:9119 \
  -e SUPERFORECASTING_AGENT_DASHBOARD=1 \
  nousresearch/superforecasting-agent gateway run
```

The entrypoint starts `superforecasting-agent dashboard` in the background before launching the foreground command. Dashboard output is prefixed with `[dashboard]` in `docker logs`.

| Environment variable | Description | Default |
|---------------------|-------------|---------|
| `SUPERFORECASTING_AGENT_DASHBOARD` / `FORECAST_DASHBOARD` / `HERMES_DASHBOARD` | Toggle for launching the dashboard side process | *(unset)* |
| `SUPERFORECASTING_AGENT_DASHBOARD_HOST` / `FORECAST_DASHBOARD_HOST` / `HERMES_DASHBOARD_HOST` | Dashboard bind address | `0.0.0.0` |
| `SUPERFORECASTING_AGENT_DASHBOARD_PORT` / `FORECAST_DASHBOARD_PORT` / `HERMES_DASHBOARD_PORT` | Dashboard HTTP port | `9119` |
| `SUPERFORECASTING_AGENT_DASHBOARD_TUI` / `FORECAST_DASHBOARD_TUI` / `HERMES_DASHBOARD_TUI` | Expose the embedded terminal UI in the browser | *(unset)* |

The default dashboard host of `0.0.0.0` is required for the host to reach the dashboard through the published port. The entrypoint automatically passes `--insecure` to the dashboard in that case. Use `127.0.0.1` behind a reverse proxy if you want local-only binding.

:::note
The dashboard side process is not supervised. If it crashes, restart the container.
:::

## Interactive CLI

Open a one-off interactive session against the mounted data directory:

```sh
docker run -it --rm \
  -v ~/.superforecasting-agent:/opt/data \
  nousresearch/superforecasting-agent
```

Run forecast lifecycle commands through the same image:

```sh
docker run -it --rm \
  -v ~/.superforecasting-agent:/opt/data \
  nousresearch/superforecasting-agent forecast list

docker run -it --rm \
  -v ~/.superforecasting-agent:/opt/data \
  nousresearch/superforecasting-agent forecast review --last 30d

docker run -it --rm \
  -v ~/.superforecasting-agent:/opt/data \
  nousresearch/superforecasting-agent forecast backtest
```

If you have opened a shell inside the running container, the legacy executable path is still:

```sh
/opt/hermes/.venv/bin/hermes
```

Prefer `/opt/hermes/.venv/bin/superforecasting-agent` or `/opt/hermes/.venv/bin/forecast` for fork-native scripts inside the image.

## Persistent Volume

The `/opt/data` mount is the source of truth for forecast work:

| Path | Contents |
|------|----------|
| `.env` | API keys and secrets |
| `config.yaml` | Runtime, model, tool, gateway, cron, and forecasting configuration |
| `SOUL.md` | Agent identity and standing behavior |
| `forecasting/` | Forecast ledger, source snapshots, scoring records, calibration data, and review artifacts |
| `sessions/` | Conversation and task history |
| `memories/` | Inherited memory backends and forecast-supporting notes |
| `skills/` | Installed skills |
| `cron/` | Scheduled review, alert, and maintenance jobs |
| `hooks/` | Event hooks |
| `logs/` | Runtime, gateway, scheduler, and error logs |
| `skins/` | CLI skins |

:::warning
Never run two gateway or scheduler containers against the same data directory at the same time. Forecast ledgers, session files, source snapshots, and memory stores are not designed for concurrent writes from separate runtimes.
:::

## Profiles and Domains

The fork supports [profiles](../reference/profile-commands.md), but Docker deployments are simpler and safer when each forecasting domain gets its own container and data directory. Use this pattern for work such as elections, macro, company-risk, AI benchmarks, or policy monitoring.

```sh
# Elections profile
docker run -d \
  --name forecast-elections \
  --restart unless-stopped \
  -v ~/.superforecasting-agent-elections:/opt/data \
  -p 8642:8642 \
  nousresearch/superforecasting-agent gateway run

# Macro profile
docker run -d \
  --name forecast-macro \
  --restart unless-stopped \
  -v ~/.superforecasting-agent-macro:/opt/data \
  -p 8643:8642 \
  nousresearch/superforecasting-agent gateway run
```

Separate containers keep credentials, source watchlists, scheduler jobs, calibration history, and ledger state isolated. They also make it easier to back up or pause a domain without touching the others.

## Docker Compose

For a persistent deployment with gateway, dashboard, and cron-capable runtime:

```yaml
services:
  superforecasting-agent:
    image: nousresearch/superforecasting-agent:latest
    container_name: superforecasting-agent
    restart: unless-stopped
    command: gateway run
    ports:
      - "8642:8642"   # gateway API
      - "9119:9119"   # dashboard when SUPERFORECASTING_AGENT_DASHBOARD=1
    volumes:
      - ~/.superforecasting-agent:/opt/data
    environment:
      - SUPERFORECASTING_AGENT_HOME=/opt/data
      - SUPERFORECASTING_AGENT_DASHBOARD=1
      # Forward specific env vars instead of storing them in .env if needed:
      # - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      # - OPENAI_API_KEY=${OPENAI_API_KEY}
      # - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
    deploy:
      resources:
        limits:
          memory: 4G
          cpus: "2.0"
```

Start with `docker compose up -d` and inspect logs with `docker compose logs -f`.

## Environment Variables

Secrets are normally read from `/opt/data/.env`. You can also pass them directly:

```sh
docker run -it --rm \
  -v ~/.superforecasting-agent:/opt/data \
  -e ANTHROPIC_API_KEY="sk-ant-..." \
  -e OPENAI_API_KEY="sk-..." \
  nousresearch/superforecasting-agent forecast list
```

Direct `-e` values override `.env`. This is useful for CI, short-lived evaluation runs, and secret-manager integrations.

## Resource Limits

Recommended minimums:

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| Memory | 1 GB | 2-4 GB |
| CPU | 1 core | 2 cores |
| Disk | 500 MB | 2+ GB, more for source snapshots and backtests |

Browser automation and large backtests are the most memory-hungry workloads. Allocate at least 2 GB when browser tools, Playwright, or multi-question evaluations are active.

```sh
docker run -d \
  --name superforecasting-agent \
  --restart unless-stopped \
  --memory=4g --cpus=2 \
  -v ~/.superforecasting-agent:/opt/data \
  nousresearch/superforecasting-agent gateway run
```

## What the Dockerfile Does

The image is based on Debian and includes:

- Python with Superforecasting Agent and the inherited runtime dependencies
- Node.js and npm for browser automation, TUI build artifacts, and messaging bridges
- Playwright with Chromium
- ripgrep, ffmpeg, git, Docker CLI, OpenSSH client, and tini
- bundled skills and optional runtime assets

The compatibility entrypoint (`docker/entrypoint.sh`) bootstraps the mounted data volume:

- creates directories such as `sessions/`, `memories/`, `skills/`, `cron/`, `logs/`, and `workspace/`
- copies `.env.example` and default `config.yaml` if missing
- copies default `SOUL.md` if missing
- syncs bundled skills while preserving user edits
- optionally launches the dashboard when `SUPERFORECASTING_AGENT_DASHBOARD=1`
- runs the requested command through the fork-native `superforecasting-agent` wrapper

:::warning
Do not override the image entrypoint unless you keep `/opt/hermes/docker/entrypoint.sh` in the command chain. The entrypoint drops root privileges to the runtime user before gateway state files are created. Starting the gateway as root can leave root-owned files in `/opt/data` and break later starts. Use `HERMES_ALLOW_ROOT_GATEWAY=1` only when you intentionally accept that risk.
:::

## Upgrading

Pull the latest image and recreate the container. The mounted data directory is untouched.

```sh
docker pull nousresearch/superforecasting-agent:latest
docker rm -f superforecasting-agent
docker run -d \
  --name superforecasting-agent \
  --restart unless-stopped \
  -v ~/.superforecasting-agent:/opt/data \
  nousresearch/superforecasting-agent gateway run
```

With Docker Compose:

```sh
docker compose pull
docker compose up -d
```

After upgrades that change forecast data structures, run a quick ledger check:

```sh
docker run -it --rm \
  -v ~/.superforecasting-agent:/opt/data \
  nousresearch/superforecasting-agent forecast calibration
```

## Skills and Credential Files

When Docker is used as the terminal backend rather than as the primary runtime, the agent reuses a long-lived sandbox container for tool calls and automatically bind-mounts the active skills directory and declared credential files as read-only volumes. Skill scripts, templates, and references are available inside the sandbox without manual setup, and files created during one tool call remain available for later calls in the same process.

The same syncing behavior applies to SSH and Modal backends through their upload mechanisms.

## Local Inference Servers

When the forecast desk runs in Docker and your inference server runs on the host or another container, configure networking explicitly.

### Docker Compose

Put both services on the same Docker network:

```yaml
services:
  vllm:
    image: vllm/vllm-openai:latest
    container_name: vllm
    command: >
      --model Qwen/Qwen2.5-7B-Instruct
      --served-model-name my-model
      --host 0.0.0.0
      --port 8000
    ports:
      - "8000:8000"
    networks:
      - forecast-net

  superforecasting-agent:
    image: nousresearch/superforecasting-agent:latest
    container_name: superforecasting-agent
    restart: unless-stopped
    command: gateway run
    ports:
      - "8642:8642"
    volumes:
      - ~/.superforecasting-agent:/opt/data
    networks:
      - forecast-net

networks:
  forecast-net:
    driver: bridge
```

Then use the inference container name in `~/.superforecasting-agent/config.yaml`:

```yaml
model:
  provider: custom
  model: my-model
  base_url: http://vllm:8000/v1
  api_key: "none"
```

Key points:

- use the container name, not `localhost`, when two containers share a network
- make `model` match vLLM's `--served-model-name`
- set `api_key` to any non-empty value when the server expects the header
- omit trailing slashes from `base_url`

### Standalone Docker Run

If the inference server runs directly on the host, use `host.docker.internal` on macOS and Windows, or `--network host` on Linux.

```sh
docker run -d \
  --name superforecasting-agent \
  -v ~/.superforecasting-agent:/opt/data \
  -p 8642:8642 \
  nousresearch/superforecasting-agent gateway run
```

```yaml
model:
  provider: custom
  model: my-model
  base_url: http://host.docker.internal:8000/v1
  api_key: "none"
```

On Linux with host networking:

```sh
docker run -d \
  --name superforecasting-agent \
  --network host \
  -v ~/.superforecasting-agent:/opt/data \
  nousresearch/superforecasting-agent gateway run
```

```yaml
model:
  provider: custom
  model: my-model
  base_url: http://127.0.0.1:8000/v1
  api_key: "none"
```

With `--network host`, Docker ignores `-p` because container ports are exposed directly on the host.

### Verify Connectivity

```sh
docker exec superforecasting-agent curl -s http://vllm:8000/v1/models
```

If this fails, check the Docker network, the inference server bind address, and the port number.

## Troubleshooting

### Container exits immediately

Check logs:

```sh
docker logs superforecasting-agent
```

Common causes are missing credentials, invalid config, and port conflicts.

### Permission denied errors

The entrypoint drops privileges to the non-root runtime user. If the host data directory is owned by another UID, set `SUPERFORECASTING_AGENT_UID` and `SUPERFORECASTING_AGENT_GID` to match your host user, or use the shorter `FORECAST_UID` / `FORECAST_GID` aliases. The legacy `HERMES_UID` / `HERMES_GID` variables remain accepted for inherited deployments.

```sh
chmod -R 755 ~/.superforecasting-agent
```

### Browser tools fail

Playwright needs shared memory:

```sh
docker run -d \
  --name superforecasting-agent \
  --shm-size=1g \
  -v ~/.superforecasting-agent:/opt/data \
  nousresearch/superforecasting-agent gateway run
```

### Gateway or scheduler stops updating

Restart the container, then inspect stale forecasts and scheduled review jobs:

```sh
docker restart superforecasting-agent
docker run -it --rm \
  -v ~/.superforecasting-agent:/opt/data \
  nousresearch/superforecasting-agent forecast review --stale
```

### Check health

```sh
docker logs --tail 50 superforecasting-agent
docker run -it --rm nousresearch/superforecasting-agent:latest version
docker stats superforecasting-agent
```
