---
sidebar_position: 15
title: "Web Dashboard"
description: "Browser dashboard for forecast review, configuration, logs, research sessions, cron jobs, and forecast skills."
---

# Web Dashboard

The web dashboard is a local browser UI for inspecting the Superforecasting Agent runtime. It is secondary to the CLI, but useful for reviewing the forecast book, checking configuration, managing credentials, inspecting research sessions, and watching logs without editing YAML by hand.

The fork-native landing page is **Forecasts**. It shows active questions, review queue, focused action commands, calibration health, learning memory, domain/topic error profiles, alerts, and recent backtests. The embedded chat pane is optional and exists to support forecast work, not to replace the CLI forecast workflow.

## Quick Start

```bash
superforecasting-agent dashboard
```

This starts a local web server and opens `http://127.0.0.1:9119` in your browser. The dashboard runs on your machine.

`hermes dashboard` remains accepted for inherited runtime compatibility.

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | `9119` | Port to run the web server on. |
| `--host` | `127.0.0.1` | Bind address. |
| `--no-open` | off | Do not auto-open the browser. |
| `--insecure` | off | Allow binding to non-localhost hosts. Use only behind trusted network controls. |
| `--tui` | off | Expose the optional browser Forecast Chat tab by embedding `superforecasting-agent --tui` behind a PTY/WebSocket bridge. Alternatively set `SUPERFORECASTING_AGENT_DASHBOARD_TUI=1` or `FORECAST_DASHBOARD_TUI=1`; legacy `HERMES_DASHBOARD_TUI=1` is still accepted. |

```bash
superforecasting-agent dashboard --port 8080
superforecasting-agent dashboard --no-open
superforecasting-agent dashboard --tui
```

## Prerequisites

The default install may not include the HTTP stack or PTY helper. Install the dashboard extras with:

```bash
pip install 'superforecasting-agent[web]'
```

For the optional embedded Forecast Chat tab:

```bash
pip install 'superforecasting-agent[web,pty]'
```

The `web` extra installs FastAPI and Uvicorn. The `pty` extra installs the pseudo-terminal helper needed to run the TUI inside the browser on Linux, macOS, or WSL2. Native Windows can use the rest of the dashboard, but the embedded terminal pane requires a POSIX PTY environment.

If dependencies are missing, `superforecasting-agent dashboard` prints the install command. If the frontend has not been built yet and `npm` is available, it builds automatically on first launch.

## Pages

### Forecasts

The Forecasts page is the dashboard's primary product surface.

It shows:

- Active questions and current probabilities.
- As-of timestamps, forecast deltas, confidence, and close dates.
- Alerts from watched sources and scheduled self-checks.
- Stale forecasts and review queue items.
- Open and stale reference-class counts for base-rate review pressure.
- Focused `show`, `research`, `update`, and `resolve` commands for the top
  review or active forecast.
- Calibration health by bucket, horizon, domain, and origin.
- Learning memory, active lessons, and domain/topic error profiles.
- Evidence-status gaps for live-score counts, agent-protocol replay coverage,
  leakage-free runs, positive generated-source benchmark edges, and distinct
  datasets.
- Recent backtest runs and paired baseline comparisons.

Use this page when you want to see where the forecast book needs work before jumping back into the CLI.

Related CLI commands:

```bash
forecast status
forecast review
forecast alerts
forecast show <id>
forecast research <id>
forecast update <id> --probability <0-1>
forecast resolve <id> --outcome <value> --source <url>
forecast calibration --by-origin
forecast lessons
forecast performance
```

### Status

Status shows the runtime state around the forecasting desk:

- Superforecasting Agent version.
- Active profile and home path.
- Gateway status and connected platforms.
- Active and recent research sessions.
- Model/provider status.

This page is operational telemetry. Forecast truth lives in the ledger, not in the session list.

### Forecast Chat

When started with `--tui`, the dashboard exposes an optional Forecast Chat tab. It embeds the real terminal TUI through xterm.js. The transcript, composer, slash commands, model picker, approvals, clarify prompts, tool activity, and `/forecast` shortcuts are the same TUI flow you get from:

```bash
superforecasting-agent --tui
```

How it works:

- `/api/pty` opens a WebSocket authenticated with the dashboard session token.
- The server spawns `superforecasting-agent --tui` behind a POSIX pseudo-terminal.
- Keystrokes travel to the PTY; ANSI output streams back to the browser.
- Resizing the browser window resizes the TUI through xterm.js.

Resume from Research Sessions by opening a session and launching the chat pane with that session id. Close the browser tab to reap the PTY process on the server.

### Config

Config edits the active profile's `config.yaml`. The form is generated from the default config schema and grouped by runtime area:

- Model/provider settings.
- Terminal backend and working directory.
- Display and skin settings.
- Forecast-desk tool exposure.
- Gateway, cron, memory, and extension settings.
- Approval and security controls.

Actions:

- **Save** writes the profile config.
- **Reset to defaults** reverts the form before saving.
- **Export** downloads the current config as JSON.
- **Import** uploads JSON config.

Config changes usually apply on the next agent session, gateway restart, or TUI restart. The dashboard edits the same config that `superforecasting-agent config set` reads.

### API Keys

API Keys manages the active profile's `.env` file. Keys are grouped by provider, tool, messaging platform, and setting.

Each key shows whether it is set, a redacted preview, a description, a provider link when known, and controls to update or delete it.

Secrets stay in `.env`. Non-secret settings should usually live in `config.yaml`.

### Research Sessions

Research sessions are conversation continuity and operational history. They are not the forecast ledger.

Use this page to:

- Search prior forecast chats and CLI research sessions with FTS5.
- Inspect message history and tool calls.
- Resume a prior terminal/TUI session.
- Delete obsolete research transcripts.

When a session contains important evidence, probability changes, assumptions, or calibration lessons, move those artifacts into the forecast ledger through `forecast evidence`, `forecast update`, `forecast postmortem`, or the `forecast_ledger` tool.

### Logs

Logs shows agent, gateway, and error logs with filtering and live tailing.

Use it for:

- Startup and provider errors.
- Gateway connection issues.
- Tool execution traces.
- Cron/self-check failures.
- Dashboard/TUI troubleshooting.

### Analytics

Analytics summarizes token usage, model usage, cache hit rate, and estimated cost from session history. This is runtime accounting, not forecast performance.

For forecast performance, use:

```bash
forecast calibration
forecast performance
forecast backtest
```

### Cron

Cron manages inherited scheduled agent jobs. Forecast lifecycle schedules are usually better managed through:

```bash
forecast schedule
forecast watch add
forecast alerts
```

Use dashboard cron only for general runtime jobs or delivery workflows. Use forecast schedules for stale-forecast checks, evidence scans, resolution checks, scoring, postmortems, and calibration-memory updates.

### Forecast Skills And Toolsets

Browse, search, and toggle forecast skills and toolsets for the active profile. This is a support surface for repeatable research procedures, source workflows, modeling recipes, and review checklists; the forecast ledger remains the durable source of truth. New installs prefer `~/.superforecasting-agent/skills/`; legacy `~/.hermes/skills/` remains readable during compatibility.

For routine forecasting, keep the default `forecast-desk` toolset narrow. Enable broad inherited tools only when they improve evidence quality, modeling, review, or calibration.

## Security

The dashboard reads and writes credentials and config for the active profile.

- It binds to `127.0.0.1` by default.
- Do not bind to `0.0.0.0` unless the host is protected by trusted network controls.
- Treat `--insecure` as exposing credentials and tool controls to the network.
- Keep browser access local when terminal, file, browser, or code-execution tools are enabled.

## Reloading Credentials

After editing `.env` through the dashboard, use `/reload` in an active CLI/TUI session to re-read credentials without restarting the process:

```text
You -> /reload
Reloaded .env (3 var(s) updated)
```

The reload path reads the active profile's `.env`, normally under `~/.superforecasting-agent/` or a named profile directory. Legacy `~/.hermes` homes remain supported.

## REST API

The frontend consumes the dashboard REST API. You can also call these endpoints directly for local automation.

Forecast endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /api/forecast/dashboard` | Shared forecast dashboard summary: active book, review queue, calibration health, learning memory, alerts, and backtests. |

Runtime endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /api/status` | Version, active profile, gateway status, platform states, and active-session count. |
| `GET /api/sessions` | Recent research sessions with metadata and previews. |
| `GET /api/sessions/{session_id}` | Metadata for one research session. |
| `GET /api/sessions/{session_id}/messages` | Full message history for one research session. |
| `GET /api/sessions/search?q=...` | Full-text search across message content. |
| `DELETE /api/sessions/{session_id}` | Delete a session. |
| `GET /api/config` | Current `config.yaml` as JSON. |
| `GET /api/config/defaults` | Default configuration values. |
| `GET /api/config/schema` | Config field schema used by the form renderer. |
| `PUT /api/config` | Save config. Body: `{"config": {...}}`. |
| `GET /api/env` | Known env vars with redacted set/unset status. |
| `PUT /api/env` | Set an env var. Body: `{"key": "VAR_NAME", "value": "secret"}`. |
| `DELETE /api/env` | Remove an env var. Body: `{"key": "VAR_NAME"}`. |
| `GET /api/logs` | Log lines with file, level, component, and line-count filters. |
| `GET /api/analytics/usage` | Session token/cost analytics. |
| `GET /api/cron/jobs` | Inherited cron jobs. |
| `POST /api/cron/jobs` | Create inherited cron job. |
| `POST /api/cron/jobs/{job_id}/pause` | Pause cron job. |
| `POST /api/cron/jobs/{job_id}/resume` | Resume cron job. |
| `POST /api/cron/jobs/{job_id}/trigger` | Trigger cron job. |
| `DELETE /api/cron/jobs/{job_id}` | Delete cron job. |
| `GET /api/skills` | Skills and enabled state. |
| `PUT /api/skills/toggle` | Enable or disable a skill. |
| `GET /api/tools/toolsets` | Toolsets, labels, requirements, and active/configured state. |

## CORS

The server restricts CORS to localhost origins:

- `http://localhost:9119` / `http://127.0.0.1:9119`
- `http://localhost:3000` / `http://127.0.0.1:3000`
- `http://localhost:5173` / `http://127.0.0.1:5173`

If you run the server on a custom port, that origin is added automatically.

## Development

For frontend work:

```bash
# Terminal 1: backend API
superforecasting-agent dashboard --no-open

# Terminal 2: frontend dev server
cd web/
npm install
npm run dev
```

The Vite dev server at `http://localhost:5173` proxies `/api` requests to the FastAPI backend at `http://127.0.0.1:9119`.

Production builds output to `hermes_cli/web_dist/`, which the FastAPI server serves as a static SPA. The directory name is inherited for compatibility.

## Automatic Build On Update

When you run `superforecasting-agent update`, the web frontend is rebuilt if `npm` is available. If `npm` is not installed, the update skips the frontend build and the dashboard builds on first launch when possible.

## Themes And Extensions

The dashboard supports user-defined themes, extension tabs, and backend API routes. These are inherited extension surfaces and should be used when they improve forecast review, evidence inspection, monitoring, or operational control.

Built-in themes:

| Theme | Character |
|-------|-----------|
| **Forecast Desk** (`default`) | Dark teal + cream, system fonts, comfortable spacing. |
| **Forecast Desk Large** (`default-large`) | Same as default with larger text and roomier spacing. |
| **Midnight** (`midnight`) | Deep blue-violet, Inter + JetBrains Mono. |
| **Ember** (`ember`) | Warm crimson + bronze, Spectral serif + IBM Plex Mono. |
| **Mono** (`mono`) | Grayscale, IBM Plex, compact. |
| **Cyberpunk** (`cyberpunk`) | Neon green on black, Share Tech Mono. |
| **Rose** (`rose`) | Pink + ivory, Fraunces serif, spacious. |

To build your own theme, add an extension tab, inject into shell slots, or expose plugin-specific REST endpoints, see [Extending the Dashboard](./extending-the-dashboard).
