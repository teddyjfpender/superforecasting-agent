---
title: Codex App-Server Runtime
sidebar_label: Codex App-Server Runtime
---

# Codex App-Server Runtime

Superforecasting Agent can optionally hand `openai/*` and `openai-codex/*` turns to the Codex CLI app-server instead of using the default agent loop. When enabled, shell commands, file edits, sandboxing, and Codex-native MCP/plugin calls run inside Codex's runtime.

This is opt-in only. The default forecast desk runtime remains unchanged unless you enable it.

For forecasting work, treat this runtime as an execution backend for code, repository work, source-adapter development, benchmark fixtures, and auxiliary research tasks. It does not change the source of durable forecast truth. Forecast questions, evidence, probabilities, model runs, resolutions, scores, postmortems, calibration lessons, and domain error profiles remain ledger-owned.

## Why Use It

- Run OpenAI/Codex turns through the same subscription auth flow used by Codex CLI.
- Use Codex's native `shell`, `apply_patch`, `update_plan`, `view_image`, and sandbox behavior.
- Reuse Codex plugins that are already installed and authorized through Codex CLI.
- Let Codex call back into configured Superforecasting Agent tools through an MCP bridge for web search, browser automation, vision, image generation, skills, and speech tools.
- Keep forecast-desk sessions, slash commands, gateway routing, and auxiliary review infrastructure around the Codex runtime.

## Tool Sources

When this runtime is active, a turn can receive tools from three places.

### 1. Codex Built-Ins

Codex provides its own built-in tools:

- `shell` for terminal commands, file reads, file writes, search, builds, and scripts
- `apply_patch` for structured file edits
- `update_plan` for in-runtime planning
- `view_image` for loading local images into the conversation
- Codex-provided `web_search` when configured

The Codex permission profile controls what the model may read or write.

### 2. Native Codex Plugins

Codex plugins installed with `codex plugin` are managed by Codex and authorized through Codex's own UI. When the runtime is enabled, installed plugins can be migrated into `~/.codex/config.toml`.

Typical plugins include GitHub, Linear, Gmail, Calendar, Outlook, and other curated integrations. Use them as source and workflow helpers. If plugin output matters to a forecast, capture the relevant claim or source in the forecast ledger before relying on it.

### 3. Superforecasting Agent Tool Callback

The runtime registers an inherited MCP server named `hermes-tools` so Codex can call tools that Codex does not ship with. The name is retained for compatibility with the existing transport module.

Common callback tools include:

- `web_search` and `web_extract`
- browser automation tools
- `vision_analyze`
- `image_generate`
- `skill_view` and `skills_list`
- `text_to_speech`

The callback dispatches through the normal tool registry path. Because it is stateless, some agent-loop tools are unavailable:

- `delegate_task`
- `memory`
- `session_search`
- `todo`

Use `/codex-runtime auto` for turns that need those default-loop tools.

## Forecast-Ledger Boundary

Codex runtime outputs are not ledger writes by themselves:

- A shell result is not an evidence snapshot until imported or recorded.
- A browser/plugin result is not a source citation until stored with source metadata.
- A generated model script is not a model run until its parameters, inputs, output, and provenance are recorded.
- A Codex plan is not a forecast rationale until a forecast update captures it.

For CLI lifecycle work, use the normal forecast commands after inspection:

```bash
superforecasting-agent forecast evidence ...
superforecasting-agent forecast model ...
superforecasting-agent forecast update ...
superforecasting-agent forecast resolve ...
```

## Workflow Features

### `/goal`

Goals can run on this runtime because continuation prompts still flow through `run_conversation()`. The goal judge uses the configured auxiliary model slot and is independent of the active runtime.

Expect more command approvals on long-running goals because each continuation is a fresh Codex turn.

### Kanban

Kanban workers can run on the Codex runtime if their profile enables it. The worker does task work through Codex built-ins and reports status through callback tools such as:

- `kanban_complete`
- `kanban_block`
- `kanban_comment`
- `kanban_heartbeat`
- `kanban_show`
- `kanban_list`

The dispatcher still uses inherited environment variables such as `HERMES_KANBAN_TASK`, `HERMES_KANBAN_DB`, `HERMES_KANBAN_WORKSPACES_ROOT`, `HERMES_KANBAN_WORKSPACE`, and legacy `HERMES_KANBAN_ROOT`. These are runtime compatibility names.

For forecast work, use kanban as task orchestration. It does not replace the forecast ledger.

### Cron

Cron jobs run through the same conversation path as the CLI. If a cron profile has `model.openai_runtime: codex_app_server`, the job can use Codex. For scheduled forecast self-checks, scoring, backtests, and domain-learning updates, prefer a tested default-runtime profile unless the job's tool needs are known to fit the Codex runtime.

## Trade-Offs

| Capability | Default runtime | Codex app-server |
|---|---:|---:|
| Forecast ledger tool access | yes | depends on callback/toolset availability |
| `delegate_task` | yes | no |
| `memory`, `session_search`, `todo` | yes | no |
| Web search and extraction | yes | yes, via callback or Codex |
| Browser automation | yes | yes, via callback |
| Vision and image generation | yes | yes, via callback or Codex image support |
| Skills | yes | read-only callback support |
| TTS | yes | yes, via callback |
| Codex shell/apply_patch/update_plan | no | yes |
| Codex sandbox | no | yes |
| ChatGPT subscription auth | provider-dependent | yes for Codex/OpenAI |
| Native Codex plugins | no | yes |
| Non-OpenAI providers | yes | no |

## Prerequisites

Install and authenticate Codex CLI:

```bash
npm i -g @openai/codex
codex --version
codex login
```

Codex auth is stored under `~/.codex/auth.json`. Superforecasting Agent's own Codex auth is separate:

```bash
superforecasting-agent auth login codex
```

Run both if you want the cleanest UX with Codex CLI and the forecast desk.

Install any native Codex plugins through Codex itself before enabling this runtime:

```bash
codex plugin marketplace add openai-curated
```

Then install and authorize the plugins from Codex's UI.

## Enabling

Inside a Superforecasting Agent session:

```text
/codex-runtime codex_app_server
```

That command:

- verifies that `codex` is installed
- persists `model.openai_runtime: codex_app_server`
- migrates user MCP servers from the forecast config to `~/.codex/config.toml`
- discovers installed native Codex plugins
- registers the tool callback MCP server
- writes a workspace-oriented default permission profile when needed

It takes effect on the next session.

Synonyms:

```text
/codex-runtime on
/codex-runtime off
/codex-runtime auto
```

Check current state:

```text
/codex-runtime
```

Manual config in `~/.superforecasting-agent/config.yaml`:

```yaml
model:
  openai_runtime: codex_app_server
```

Legacy `~/.hermes/config.yaml` profiles remain readable during migration.

## Auxiliary Tasks

When `openai-codex` is the active provider, auxiliary tasks can also use subscription auth by default. That includes title generation, context compression, vision detection, goal judging, and background review tasks unless you override them.

Route specific auxiliary work elsewhere:

```yaml
auxiliary:
  title_generation:
    provider: openrouter
    model: google/gemini-3-flash-preview
  context_compression:
    provider: openrouter
    model: google/gemini-3-flash-preview
  vision_detect:
    provider: openrouter
    model: google/gemini-3-flash-preview
  goal_judge:
    provider: openrouter
    model: google/gemini-3-flash-preview
```

Background memory and skill review are auxiliary recall/playbook maintenance. They are not forecast calibration learning. Forecast learning still belongs in scoring, postmortem, and calibration-ledger workflows.

## Approvals and Permissions

Codex requests approval before commands or patches when its permission profile requires it. These requests are shown through the normal command-approval UI.

Common permission profiles:

| Profile | Behavior |
|---|---|
| `:read-only` | No writes; shell commands require approval |
| `:workspace` | Workspace writes are allowed without prompting |
| `:danger-no-sandbox` | No sandbox; avoid unless you understand the risk |

You can override permissions in `~/.codex/config.toml` outside the managed block.

## Editing `~/.codex/config.toml`

The runtime writes a managed block to `~/.codex/config.toml` with fork-native markers. Older configs that contain inherited `hermes-agent` managed-block markers are recognized and replaced on the next migration:

```toml
# managed by superforecasting-agent — `superforecasting-agent codex-runtime migrate` regenerates this section
default_permissions = ":workspace"
[mcp_servers.hermes-tools]
...
# end superforecasting-agent managed section
```

Anything outside that block is user-owned and preserved on migration. Anything inside the block can be replaced the next time the runtime is enabled or migrated.

## Profiles and Codex State

By default, Codex reads `~/.codex/` regardless of the active forecast profile. This preserves normal Codex CLI behavior and avoids silently invalidating existing Codex auth.

For profile-specific Codex state, set `CODEX_HOME` per profile. A fork-native path is preferred:

```bash
CODEX_HOME=~/.superforecasting-agent/profiles/macro/codex superforecasting-agent chat
```

Then run `codex login` once with that `CODEX_HOME`.

Legacy examples may use `~/.hermes/profiles/<profile>/codex` and `hermes chat`; those remain compatibility paths and commands.

## HOME Passthrough

The runtime does not rewrite `HOME` when spawning the Codex app-server subprocess. Commands run by Codex still see the real user home and can find `~/.gitconfig`, `~/.gh/`, `~/.aws/`, `~/.npmrc`, and similar files.

Codex's own state is isolated through `CODEX_HOME`, which defaults to `~/.codex/`.

## MCP Migration

`mcp_servers` entries from the forecast config are translated to Codex TOML whenever you enable the runtime:

| Forecast config | Codex config |
|---|---|
| `command` + `args` + `env` | stdio transport |
| `url` + `headers` | streamable HTTP transport |
| `timeout` | `tool_timeout_sec` |
| `connect_timeout` | `startup_timeout_sec` |
| `enabled: false` | `enabled = false` |

Runtime-specific keys that Codex does not understand are dropped with warnings.

## Tool Callback MCP Server

Codex can call configured forecast-desk tools through the inherited callback server:

```toml
[mcp_servers.hermes-tools]
command = "/path/to/python"
args = ["-m", "agent.transports.hermes_tools_mcp_server"]
env = { HERMES_HOME = "/your/.superforecasting-agent", PYTHONPATH = "...", HERMES_QUIET = "1" }
startup_timeout_sec = 30.0
tool_timeout_sec = 600.0
```

The `hermes-tools`, `hermes_tools_mcp_server`, `HERMES_HOME`, and `HERMES_QUIET` names are inherited runtime identifiers. New profile paths should still point at the forecast-native home.

## Disabling

Switch back at any time:

```text
/codex-runtime auto
```

The change is effective on the next session. The Codex managed block remains in `~/.codex/config.toml` so it can be re-enabled later.

## Limitations

- The runtime is opt-in and OpenAI/Codex-scoped.
- Codex auth and Superforecasting Agent auth are separate sessions.
- `delegate_task`, `memory`, `session_search`, and `todo` are unavailable through the stateless callback.
- Inline patch preview can be incomplete when Codex does not provide the changeset before approval.
- Mid-stream cancellation is best-effort.
- Cron forecast self-checks should use a default-runtime profile unless the Codex tool surface has been verified for that job.

If you find a runtime bug, open an issue with recent logs:

```bash
superforecasting-agent logs --since 5m
```

## Architecture

```text
Superforecasting Agent CLI / TUI / gateway
  sessions, slash commands, profiles, forecast desk surfaces
    |
    v
AIAgent.run_conversation()
  if api_mode == codex_app_server:
      CodexAppServerSession
  else:
      default chat-completions / responses runtime
    |
    v
codex app-server subprocess
  shell, apply_patch, update_plan, view_image, sandbox
  native Codex plugins
  MCP client -> hermes-tools callback -> configured forecast-desk tools
```
