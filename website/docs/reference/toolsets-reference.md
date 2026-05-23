---
sidebar_position: 4
title: "Toolsets Reference"
description: "Reference for forecast-desk, core, platform, and dynamic toolsets"
---

# Toolsets Reference

Toolsets are named bundles of tools. They define what an agent session is
allowed to do: inspect sources, run commands, edit files, write forecast
ledger entries, send messages, use plugins, or call MCP servers.

For Superforecasting Agent, the important default is `forecast-desk`. It gives
the CLI enough capability to research, model, update, schedule, score, and
learn from forecasts without exposing every inherited general-assistant
integration by default.

## How Toolsets Work

Every tool belongs to one logical toolset. Toolsets can include other toolsets,
so a composite such as `forecast-desk` expands into the underlying tool names
before the model sees them.

Toolsets come in four kinds:

| Kind | Meaning | Example |
|------|---------|---------|
| Forecast default | The CLI's primary product capability set | `forecast-desk` |
| Core | One logical group of related tools | `file`, `web`, `forecasting` |
| Composite | Multiple core toolsets combined for a workflow | `debugging`, `safe` |
| Platform | A complete runtime preset for a deployment context | `forecast-api-server`, `hermes-telegram` |

Platform names that still start with `hermes-` are compatibility identifiers in
the runtime. They do not mean the old broad assistant surface is the preferred
product surface. New configs can use fork-native aliases for the main inherited
runtime presets: `forecast-cli`, `forecast-acp`, `forecast-api-server`,
`forecast-cron`, and `forecast-gateway`.

## Configuring Toolsets

### Per Session

```bash
# Forecast desk default
superforecasting-agent

# Add a specific opt-in capability
superforecasting-agent chat --toolsets forecast-desk,mcp-market-data

# Use the inherited full runtime preset only when you need it
superforecasting-agent chat --toolsets forecast-cli
```

Avoid `all` for normal forecasting work. It exposes every registered built-in,
plugin, and dynamic toolset, which makes prompts noisier and broadens the
agent's action surface.

### Per Platform

```yaml
toolsets:
  - forecast-desk
```

Messaging, gateway, ACP, and API-server profiles can still use their platform
presets when that deployment needs the inherited runtime behavior.

### Interactive Management

```bash
superforecasting-agent tools
superforecasting-agent tools list
```

In the classic interactive CLI, slash commands can inspect and adjust tool
availability for the current runtime:

```text
/tools list
/tools disable browser
/tools enable mcp-market-data
```

The `superforecasting-agent tools` UI persists tool-level disables to
`config.yaml`. Disabled tools are filtered out even when a matching toolset is
enabled.

## Forecast Default

| Toolset | Includes | Purpose |
|---------|----------|---------|
| `forecast-desk` | `forecasting`, `web`, `browser`, `terminal`, `file`, `code_execution`, `todo`, `clarify`, `cronjob` | Default CLI desk for forecast ledger operations, source research, local modeling, evidence capture, scheduled review, and explicit clarification. |

The default intentionally does not include generic memory-provider tools,
skills marketplace tools, image generation, delegation, messaging delivery,
Home Assistant, Spotify, Discord administration, RL training, or other broad
assistant integrations. Enable those explicitly when a forecast workflow
actually needs them.

## Core Toolsets

| Toolset | Tools | Purpose |
|---------|-------|---------|
| `forecasting` | `forecast_ledger` | Forecast question lifecycle, evidence, snapshots, assumptions, reference classes, model runs, schedules, alerts, scores, postmortems, calibration lessons, and exports. |
| `web` | `web_search`, `web_extract` | Web search and page extraction for evidence gathering. |
| `search` | `web_search` | Search only, without extraction. |
| `browser` | browser navigation/snapshot/click/type/scroll/console/CDP tools, `web_search` | Interactive source inspection and pages that need browser automation. CDP-only tools register only when a CDP endpoint is available. |
| `file` | `read_file`, `write_file`, `patch`, `search_files` | Read, write, patch, and search local files. |
| `terminal` | `terminal`, `process` | Shell command execution and background process management. |
| `code_execution` | `execute_code` | Run Python scripts that can call tools programmatically. |
| `cronjob` | `cronjob` | Inherited generic scheduler. Forecast lifecycle schedules should prefer `forecast schedule`. |
| `todo` | `todo` | Session task planning and tracking. |
| `clarify` | `clarify` | Ask the user for a needed decision or missing input. |
| `memory` | `memory` | Generic cross-session memory. Forecast learning should be stored in the forecast ledger. |
| `session_search` | `session_search` | Search prior chat sessions. |
| `skills` | `skills_list`, `skill_view`, `skill_manage` | Browse and manage skill documents. |
| `delegation` | `delegate_task` | Spawn isolated subagent instances for complex subtasks. |
| `vision` | `vision_analyze` | Analyze images. |
| `image_gen` | `image_generate` | Generate images through configured providers. |
| `video` | `video_analyze` | Analyze video; opt-in. |
| `video_gen` | `video_generate` | Generate video through configured providers; opt-in. |
| `tts` | `text_to_speech` | Generate speech audio. |
| `messaging` | `send_message` | Send outbound messages through configured platforms. |
| `computer_use` | `computer_use` | Background macOS desktop control via cua-driver. |
| `homeassistant` | `ha_list_entities`, `ha_get_state`, `ha_list_services`, `ha_call_service` | Smart-home control, gated by Home Assistant credentials. |
| `kanban` | `kanban_*` tools | Multi-agent board coordination for dispatcher/worker profiles. |
| `discord` | `discord` | Discord text/embed/DM actions for gateway use. |
| `discord_admin` | `discord_admin` | Discord moderation and server administration. |
| `spotify` | `spotify_*` tools | Spotify playback, queue, search, playlist, album, and library control. |
| `x_search` | `x_search` | Search X posts and threads through xAI credentials; off by default. |
| `moa` | `mixture_of_agents` | Multi-model consensus. |
| `yuanbao` | `yb_*` tools | Yuanbao DM/group/sticker actions. |
| `feishu_doc` | `feishu_doc_read` | Feishu/Lark document reads. |
| `feishu_drive` | `feishu_drive_*` tools | Feishu/Lark document comment operations. |

## Composite Toolsets

| Toolset | Includes | Purpose |
|---------|----------|---------|
| `debugging` | `file`, `terminal`, `web` | Troubleshooting and development work. Useful for fixing code, not a default forecasting surface. |
| `safe` | `web`, `vision`, `image_gen` | Read-only research and media generation. It omits terminal and file-write access. |

## Platform Toolsets

Platform toolsets define complete presets for non-default deployment targets.
Most names are inherited compatibility identifiers.

| Toolset | Purpose |
|---------|---------|
| `forecast-cli` | Fork-native alias for `hermes-cli`; inherited full interactive runtime preset. Prefer `forecast-desk` for normal forecasting work. |
| `forecast-acp` | Fork-native alias for `hermes-acp`; editor integration for VS Code, Zed, and JetBrains. |
| `forecast-api-server` | Fork-native alias for `hermes-api-server`; OpenAI-compatible HTTP runtime without interactive clarification or outbound messaging. |
| `forecast-cron` | Fork-native alias for `hermes-cron`; inherited cron runtime preset. Forecast-aware jobs should prefer `forecast schedule`. |
| `forecast-gateway` | Fork-native alias for `hermes-gateway`; inherited messaging gateway preset. |
| `hermes-cli` | Legacy full interactive assistant preset. Use explicitly when you want the broad inherited tool surface. |
| `hermes-acp` | Editor integration for VS Code, Zed, and JetBrains. Drops interactive messaging/audio tools. |
| `hermes-api-server` | OpenAI-compatible HTTP runtime without interactive clarification or outbound messaging. |
| `hermes-cron` | Inherited cron runtime preset. Forecast-aware jobs should prefer `forecast schedule`. |
| `hermes-telegram`, `hermes-slack`, `hermes-whatsapp`, `hermes-signal`, `hermes-matrix`, `hermes-mattermost`, `hermes-email`, `hermes-sms`, `hermes-bluebubbles`, `hermes-dingtalk`, `hermes-wecom`, `hermes-wecom-callback`, `hermes-weixin`, `hermes-qqbot`, `hermes-webhook` | Messaging/gateway presets built on the inherited runtime. |
| `hermes-discord` | Messaging preset plus Discord and Discord-admin tools. |
| `hermes-feishu` | Messaging preset plus Feishu/Lark document tools. |
| `hermes-yuanbao` | Messaging preset plus Yuanbao tools. |
| `hermes-homeassistant` | Messaging preset where Home Assistant credentials activate smart-home tools. |
| `hermes-gateway` | Internal gateway orchestrator preset, a union of all messaging platform presets. |

## Dynamic Toolsets

### MCP Server Toolsets

Each configured MCP server generates a `mcp-<server>` toolset at runtime. If a
`market-data` MCP server is configured, `mcp-market-data` becomes available in
`--toolsets`, platform configs, and the tools UI.

```yaml
mcp_servers:
  market-data:
    command: npx
    args: ["-y", "@example/market-data-mcp"]
```

### Plugin Toolsets

Plugins can register tools through `ctx.register_tool(...)`. Registered plugin
tools appear beside built-in tools and can be enabled or disabled through the
same UI.

### Custom Toolsets

Define project-specific bundles in `config.yaml` when a recurring workflow
needs a stable set of tools.

```yaml
toolsets:
  - forecast-desk
custom_toolsets:
  macro-research:
    - forecasting
    - web
    - browser
    - file
    - terminal
    - code_execution
    - mcp-market-data
```

### Wildcards

- `all` or `*` expands to every registered built-in, dynamic, and plugin
  toolset.

Use wildcards for diagnostics or deliberate full-surface sessions, not routine
forecasting.

## Relationship To Tools

Toolsets decide the first layer of exposure. The tools UI can then disable
individual tools within those enabled toolsets. The model only receives tools
that survive both filters and pass any runtime availability checks such as
credentials, platform support, or a connected browser endpoint.

See also: [Tools Reference](./tools-reference.md) for individual tool schemas.
