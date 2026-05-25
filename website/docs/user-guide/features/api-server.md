---
sidebar_position: 14
title: "API Server"
description: "Expose the forecast desk through an OpenAI-compatible API"
---

# API Server

The API server exposes Superforecasting Agent through an OpenAI-compatible HTTP endpoint. It is a secondary surface for external dashboards, control planes, and OpenAI-compatible clients that need to ask the forecast desk for work.

The CLI and forecast ledger remain the primary product. Use the API server when another tool needs to submit research prompts, subscribe to long-running agent progress, or manage scheduled background jobs. Do not treat it as a replacement for the forecast lifecycle commands that create, update, score, and review forecasts.

Requests run with the server-side agent toolset: terminal, files, web tooling, memory, skills, and any enabled forecast modules. Streaming responses include tool progress events so clients can show what the desk is doing.

## Quick Start

### 1. Enable the API server

Add this to `~/.superforecasting-agent/.env`:

```bash
API_SERVER_ENABLED=true
API_SERVER_KEY=change-me-local-dev
API_SERVER_MODEL_NAME=superforecasting-agent

# Optional: only if a browser must call the API directly
# API_SERVER_CORS_ORIGINS=http://localhost:3000
```

`~/.hermes/.env` is still accepted by compatibility installs, but new forecast-desk setups should use `~/.superforecasting-agent`.

### 2. Start the gateway

```bash
superforecasting-agent gateway
```

You should see:

```text
[API Server] API server listening on http://127.0.0.1:8642
```

### 3. Submit a forecast-desk request

Point an OpenAI-compatible client at `http://localhost:8642/v1`:

```bash
curl http://localhost:8642/v1/chat/completions \
  -H "Authorization: Bearer change-me-local-dev" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "superforecasting-agent",
    "messages": [
      {
        "role": "user",
        "content": "Review active forecasts that are stale or have new evidence today."
      }
    ]
  }'
```

Open WebUI, LobeChat, LibreChat, AnythingLLM, and similar clients can also connect through the OpenAI provider settings. Use those clients for monitoring or delegated requests; use the CLI for normal forecasting work.

## Endpoints

### POST /v1/chat/completions

Standard OpenAI Chat Completions format. This endpoint is stateless unless the client opts into session continuity with the `X-Hermes-Session-Id` compatibility header.

**Request:**

```json
{
  "model": "superforecasting-agent",
  "messages": [
    {
      "role": "system",
      "content": "Focus on evidence freshness and explicitly mention unresolved assumptions."
    },
    {
      "role": "user",
      "content": "Summarize what should be checked before updating the macro-policy forecasts."
    }
  ],
  "stream": false
}
```

**Response:**

```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1710000000,
  "model": "superforecasting-agent",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "The stale forecasts are..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 50,
    "completion_tokens": 200,
    "total_tokens": 250
  }
}
```

**Inline image input:** user messages may send `content` as an array of `text` and `image_url` parts. Both remote `http(s)` URLs and `data:image/...` URLs are supported.

Uploaded files (`file`, `input_file`, `file_id`) and non-image `data:` URLs return `400 unsupported_content_type`.

**Streaming:** set `"stream": true` to receive Server-Sent Events. Chat Completions streams use standard `chat.completion.chunk` events plus the inherited `hermes.tool.progress` event for tool-start visibility.

### POST /v1/responses

OpenAI Responses API format. This endpoint supports server-side conversation state through `previous_response_id`, so clients can keep multi-turn context without resending the entire transcript.

**Request:**

```json
{
  "model": "superforecasting-agent",
  "input": "Check whether any active forecasts in the energy profile need a source refresh.",
  "instructions": "Return only the forecast IDs, reason for review, and suggested next command.",
  "store": true
}
```

**Response:**

```json
{
  "id": "resp_abc123",
  "object": "response",
  "status": "completed",
  "model": "superforecasting-agent",
  "output": [
    {
      "type": "message",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "forecast-142 needs an evidence refresh..."
        }
      ]
    }
  ],
  "usage": {
    "input_tokens": 50,
    "output_tokens": 200,
    "total_tokens": 250
  }
}
```

**Inline image input:** `input[].content` can contain `input_text` and `input_image` parts. Both remote URLs and `data:image/...` URLs are supported.

Uploaded files (`input_file`, `file_id`) and non-image `data:` URLs return `400 unsupported_content_type`.

#### Multi-turn with previous_response_id

Chain responses to maintain full context, including tool calls:

```json
{
  "input": "Now draft the update rationale for the first forecast.",
  "previous_response_id": "resp_abc123"
}
```

Chained requests share the same session, so they appear as one entry in session history.

#### Named conversations

Use the `conversation` parameter instead of tracking response IDs:

```json
{"input": "Review the clean-energy forecasts.", "conversation": "energy-review"}
{"input": "Which ones have stale evidence?", "conversation": "energy-review"}
{"input": "Prepare update notes for the top two.", "conversation": "energy-review"}
```

The server automatically chains to the latest response in that named conversation.

### GET /v1/responses/\{id\}

Retrieve a stored response by ID.

### DELETE /v1/responses/\{id\}

Delete a stored response.

### GET /v1/models

Lists the advertised server-side agent model. Set `API_SERVER_MODEL_NAME` when a profile should expose a custom name. If unset, the default profile advertises `superforecasting-agent`; named profiles advertise the active [profile](/user-guide/profiles) name.

### GET /v1/capabilities

Returns a machine-readable description of the stable API surface for external UIs, orchestrators, and plugin bridges.

```json
{
  "object": "superforecasting_agent.api_server.capabilities",
  "legacy_object": "hermes.api_server.capabilities",
  "platform": "superforecasting-agent",
  "legacy_platform": "hermes-agent",
  "model": "superforecasting-agent",
  "auth": {"type": "bearer", "required": true},
  "features": {
    "chat_completions": true,
    "responses_api": true,
    "run_submission": true,
    "run_status": true,
    "run_events_sse": true,
    "run_stop": true,
    "session_continuity_header": "X-Hermes-Session-Id",
    "session_key_header": "X-Hermes-Session-Key"
  },
  "compatibility": {
    "legacy_object": "hermes.api_server.capabilities",
    "legacy_platform": "hermes-agent",
    "session_headers": ["X-Hermes-Session-Id", "X-Hermes-Session-Key"],
    "tool_progress_event": "hermes.tool.progress"
  }
}
```

The `legacy_*`, `hermes.tool.progress`, and `X-Hermes-*` names are inherited compatibility identifiers on the wire. They do not mean the API server should be used as a generic assistant product surface.

### GET /health

Health check. Returns `{"status": "ok"}`. Also available at `GET /v1/health` for OpenAI-compatible clients that expect the `/v1/` prefix.

### GET /health/detailed

Extended health check that reports gateway state, active sessions, connected platforms, and runtime details. Use it for monitoring.

## Runs API

The runs API is useful when a client wants to start a long-running desk task, disconnect, and later poll or subscribe to structured progress.

### POST /v1/runs

Create a new agent run. The body accepts `input`, plus optional `session_id`, `instructions`, `conversation_history`, and `previous_response_id`.

```json
{
  "input": "Research new evidence for forecast-142 and prepare an update recommendation.",
  "instructions": "Do not change the ledger. Return the evidence and suggested probability delta."
}
```

Response:

```json
{
  "run_id": "run_abc123",
  "status": "started"
}
```

### GET /v1/runs/\{run_id\}

Poll the current run state:

```json
{
  "object": "hermes.run",
  "run_id": "run_abc123",
  "status": "completed",
  "session_id": "energy-review",
  "model": "superforecasting-agent",
  "output": "forecast-142 should be updated from 0.38 to 0.43...",
  "usage": {
    "input_tokens": 50,
    "output_tokens": 200,
    "total_tokens": 250
  }
}
```

### GET /v1/runs/\{run_id\}/events

Server-Sent Events stream of tool progress, token deltas, approval requests, and lifecycle events. Designed for dashboards and thick clients that reconnect without losing run state.

### POST /v1/runs/\{run_id\}/approval

Resolve a pending approval request for an active run.

### POST /v1/runs/\{run_id\}/stop

Interrupt a running agent turn. The endpoint returns `{"status": "stopping"}` while the active agent exits at the next safe interruption point.

## Jobs API

The server exposes lightweight CRUD endpoints for scheduled background agent runs. These are useful for remote control planes, but forecast-specific scheduled learning should normally be configured through:

```bash
superforecasting-agent forecast schedule
superforecasting-agent forecast watch add
superforecasting-agent forecast alerts
```

### GET /api/jobs

List all scheduled jobs.

### POST /api/jobs

Create a scheduled job. The body accepts the same shape as `superforecasting-agent cron`: prompt, schedule, skills, provider override, and delivery target.

### GET /api/jobs/\{job_id\}

Fetch a single job definition and last-run state.

### PATCH /api/jobs/\{job_id\}

Update fields on an existing job.

### DELETE /api/jobs/\{job_id\}

Remove a job and cancel any in-flight run.

### POST /api/jobs/\{job_id\}/pause

Pause a job without deleting it.

### POST /api/jobs/\{job_id\}/resume

Resume a paused job.

### POST /api/jobs/\{job_id\}/run

Trigger the job immediately, outside its schedule.

## Prompt Handling

Client `system` messages in Chat Completions and `instructions` in Responses are layered on top of the server-side forecast-desk prompt. They can narrow the behavior for a particular frontend, but they should not replace the forecast protocol.

Good API instructions are specific and bounded:

```text
Check evidence freshness for active energy forecasts. Do not write ledger updates.
Return forecast ID, stale source, and recommended next CLI command.
```

Avoid using the API prompt to bypass ledger, scoring, calibration, or scheduled review behavior. The closed feedback loop still lives in the forecast ledger and backtesting layer.

## Authentication

Bearer token auth uses the `Authorization` header:

```text
Authorization: Bearer ***
```

Configure the key with `API_SERVER_KEY`. If a browser must call the API directly, set `API_SERVER_CORS_ORIGINS` to an explicit allowlist.

:::warning Security
The API server gives external callers access to the server-side agent toolset, including terminal commands and forecast workspace files. When binding to a non-loopback address like `0.0.0.0`, `API_SERVER_KEY` is required. Keep `API_SERVER_CORS_ORIGINS` narrow.

The default bind address is `127.0.0.1` for local-only use. Browser access is disabled by default.
:::

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `API_SERVER_ENABLED` | `false` | Enables the API server. |
| `API_SERVER_PORT` | `8642` | HTTP server port. |
| `API_SERVER_HOST` | `127.0.0.1` | Bind address. |
| `API_SERVER_KEY` | _(none)_ | Bearer token for auth. |
| `API_SERVER_CORS_ORIGINS` | _(none)_ | Comma-separated browser origins. |
| `API_SERVER_MODEL_NAME` | _(profile name)_ | Model name on `/v1/models`; defaults to `superforecasting-agent` for the default profile and the profile name for named profiles. |

### config.yaml

```yaml
# API_SERVER_* values are still environment variables.
# config.yaml support is not the canonical path for this surface yet.
```

## Security Headers

All responses include:

- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: no-referrer`

## CORS

The API server does not enable browser CORS by default. For direct browser access, set an explicit allowlist:

```bash
API_SERVER_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

When CORS is enabled:

- Preflight responses include `Access-Control-Max-Age: 600`.
- SSE streaming responses include CORS headers.
- `Idempotency-Key` is an allowed request header for deduplication.

Most frontends connect server-to-server and do not need CORS.

## Compatible Clients

Any client that supports the OpenAI API format can connect. Useful examples:

| Client | Use |
|--------|-----|
| [Open WebUI](/user-guide/messaging/open-webui) | Browser monitoring and occasional forecast-desk prompts. |
| LobeChat | Custom provider endpoint. |
| LibreChat | Custom endpoint in `librechat.yaml`. |
| AnythingLLM | Generic OpenAI provider. |
| OpenAI Python SDK | `OpenAI(base_url="http://localhost:8642/v1")`. |
| curl | Direct HTTP requests. |

Use these clients around the desk. The forecast CLI remains the canonical workflow for creating questions, updating probabilities, resolving outcomes, scoring performance, and running postmortems.

## Profiles

Profiles are separate forecast workspaces with their own config, credentials, memory, skills, and forecast ledger. To expose multiple profiles through the API, give each profile a different port:

```bash
superforecasting-agent profile create macro
superforecasting-agent profile create policy

cat >> ~/.superforecasting-agent/profiles/macro/.env <<EOF
API_SERVER_ENABLED=true
API_SERVER_PORT=8643
API_SERVER_KEY=macro-secret
API_SERVER_MODEL_NAME=macro-forecast-desk
EOF

cat >> ~/.superforecasting-agent/profiles/policy/.env <<EOF
API_SERVER_ENABLED=true
API_SERVER_PORT=8644
API_SERVER_KEY=policy-secret
API_SERVER_MODEL_NAME=policy-forecast-desk
EOF

superforecasting-agent -p macro gateway &
superforecasting-agent -p policy gateway &
```

Each profile advertises its configured model name through `/v1/models`.

## Limitations

- **Forecast ledger operations**: the API server is an agent-entry surface, not the authoritative ledger API. Use the `forecast` CLI and dashboard forecast pages for lifecycle operations.
- **Response storage**: stored Responses API state is persisted in SQLite and survives gateway restarts. Max 100 stored responses are retained with LRU eviction.
- **No file upload**: inline images are supported, but uploaded files and non-image document inputs are not supported through the API.
- **Model field is cosmetic**: the request `model` is accepted for OpenAI compatibility. The actual LLM provider/model is configured server-side.
- **Inherited wire names**: compatibility fields, progress events, and session headers can still include `hermes` for existing clients.

## Proxy Mode

The API server also serves as the backend for gateway proxy mode. When another compatible gateway is configured with `GATEWAY_PROXY_URL` pointing at this API server, it forwards messages here instead of running its own agent. This supports split deployments, such as a container handling Matrix E2EE while the host-side forecast desk owns tools and ledger access.

See [Matrix Proxy Mode](/user-guide/messaging/matrix#proxy-mode-e2ee-on-macos) for setup details.
