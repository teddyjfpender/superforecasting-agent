---
sidebar_position: 2
title: "Slash Commands Reference"
description: "Complete reference for interactive CLI and messaging slash commands"
---

# Slash Commands Reference

Superforecasting Agent has three slash-command surfaces:

- **Classic interactive CLI slash commands** — dispatched by `cli.py`, with autocomplete from the central `COMMAND_REGISTRY` in `hermes_cli/commands.py`
- **Messaging slash commands** — dispatched by `gateway/run.py`, with help text and platform menus generated from the registry
- **TUI forecast shortcuts** — local Ink handlers for forecast-desk workflows such as `/forecast`, `/sources`, `/new-forecast`, `/ingest`, `/evidence`, `/research`, `/base-rate`, `/model-run`, `/trend-model`, `/update-forecast`, `/resolve`, `/score`, `/postmortem`, `/review`, `/alerts`, `/calibration`, `/lessons`, `/backtest`, `/schedule`, `/performance`, `/readiness`, `/doctor`, `/pilot-report`, `/pilot-cohort`, and `/pilot-aggregate`

Installed skills are also exposed as dynamic slash commands on the classic CLI and messaging surfaces. That includes bundled skills like `/plan`, which opens plan mode and saves markdown plans under the workspace-local compatibility plans directory.

## Forecast desk commands

The forecast desk is the primary product surface. Use these before reaching for general chat/session controls:

| Command | Surface | Description |
|---------|---------|-------------|
| `/forecast [limit\|subcommand]` | CLI, TUI | Show the forecast dashboard or run `forecast <subcommand>` from the active session. Common subcommands include `new`, `research`, `base-rate`, `model`, `update`, `resolve`, `score`, `calibration`, `review`, `self-check`, `backtest`, and `export`. |
| `/new-forecast [args]` | TUI | Create a scoreable forecast question. Equivalent to `forecast new ...`. |
| `/ingest [args]` | TUI | Stage a URL or file as a forecast candidate. Equivalent to `forecast ingest ...`. |
| `/evidence [args]` | TUI | Add or inspect timestamped evidence. Equivalent to `forecast evidence ...`. |
| `/research [args]` | TUI | Collect evidence or source notes without moving probability. Equivalent to `forecast research ...`. |
| `/base-rate [args]` | TUI | Propose, add, or inspect reference-class/base-rate work. |
| `/model-run [args]` | TUI | Inspect or record a quantitative model run. Equivalent to `forecast model ...`. |
| `/trend-model [args]` | TUI | Record a deterministic trend projection model run. Equivalent to `forecast model ... --type trend_projection`. |
| `/update-forecast [args]` | TUI | Inspect or append a probability update to a forecast. |
| `/resolve [args]` | TUI | Record a forecast resolution. |
| `/score [args]` | TUI | Score a resolved forecast. |
| `/postmortem [args]` | TUI | Diagnose a resolved forecast and capture learning. |
| `/review [args]` | TUI | Run forecast review workflows for stale or due questions. |
| `/alerts [args]` | TUI | Show watched-source and scheduled-review alerts. |
| `/sources [--json]` | TUI | List built-in evidence/source adapters, import command shapes, and watched-source prefixes. |
| `/calibration [args]` | TUI | Show calibration analytics and error profiles. |
| `/lessons [args]` | TUI | List active calibration lessons. |
| `/backtest [args]` | TUI | Run or inspect historical replay datasets. |
| `/schedule [args]` | TUI | Manage scheduled self-checks. |
| `/performance [args]` | TUI | Show recent backtest performance. |
| `/readiness [args]` | TUI | Show live/backtest/external-corpus evidence gaps. |
| `/doctor [args]` | TUI | Run combined pilot/readiness/operator checks. |
| `/pilot-report [args]` | TUI | Check tester pilot artifact coverage. |
| `/pilot-cohort [manifest...]` | TUI | Seed prospective live pilot questions. |
| `/pilot-bundle [args]` | TUI | Bundle tester handoff evidence. |
| `/pilot-aggregate [files...]` | TUI | Aggregate tester export packets. |

## Permissions and admin/user split

Every messaging platform that supports a per-user allowlist (Telegram, Discord, Slack, Matrix, Mattermost, Signal, ...) also supports a two-tier slash command split: **admins** get every registered command, **regular users** only get the names you list in `user_allowed_commands` (plus the always-allowed floor `/help` and `/whoami`). Configure `allow_admin_from` and `user_allowed_commands` (and the per-group equivalents `group_allow_admin_from` / `group_user_allowed_commands`) inside the platform's `extra:` block in `~/.superforecasting-agent/gateway-config.yaml`. Legacy `~/.hermes/gateway-config.yaml` is still accepted during the compatibility transition.

See the per-platform docs for examples — the structure is identical across platforms:

- [Telegram](../user-guide/messaging/telegram.md#slash-command-access-control)
- [Discord](../user-guide/messaging/discord.md)
- [Slack](../user-guide/messaging/slack.md)
- [Matrix](../user-guide/messaging/matrix.md)
- [Mattermost](../user-guide/messaging/mattermost.md)
- [Signal](../user-guide/messaging/signal.md)

If `allow_admin_from` is unset for a scope, that scope stays in unrestricted backward-compat mode — every allowed user can run every command.

## Interactive CLI slash commands

Type `/` in the CLI to open the autocomplete menu. Built-in commands are case-insensitive.

### Forecast Desk

| Command | Description |
|---------|-------------|
| `/forecast [limit\|subcommand]` (alias: `/forecasts`) | Run forecast desk lifecycle commands from the active session. With no subcommand it shows the desk summary; common subcommands include `status`, `new`, `research`, `base-rate`, `model`, `update`, `resolve`, `score`, `calibration`, `review`, `self-check`, `backtest`, and `export`. |

### Session

| Command | Description |
|---------|-------------|
| `/new [name]` (alias: `/reset`) | Start a new session (fresh session ID + history). Optional `[name]` sets the initial session title — e.g. `/new my-experiment` opens a fresh session already titled `my-experiment` so it's easy to find later with `/resume` or `/sessions`. |
| `/clear` | Clear screen and start a new session |
| `/history` | Show forecast transcript history |
| `/save` | Save the current forecast transcript |
| `/retry` | Retry the last message (resend to agent) |
| `/undo` | Remove the last user/forecaster exchange |
| `/title` | Set a title for the current session (usage: /title My Session Name) |
| `/compress [focus topic]` | Manually compress forecast transcript context (flush memories + summarize). Optional focus topic narrows what the summary preserves. |
| `/rollback` | List or restore filesystem checkpoints (usage: /rollback [number]) |
| `/snapshot [create\|restore <id>\|prune]` (alias: `/snap`) | Create or restore runtime config/state snapshots. `create [label]` saves a snapshot, `restore <id>` reverts to it, `prune [N]` removes old snapshots, or list all with no args. |
| `/stop` | Kill all running background processes |
| `/queue <forecast note>` (alias: `/q`) | Queue a forecast note for the next turn (doesn't interrupt the current agent response). |
| `/steer <forecast note>` | Inject a mid-run note that arrives at the agent **after the next tool call** — no interrupt, no new user turn. The text is appended to the last tool result's content once the current tool completes, giving the agent new context without breaking the current tool-calling loop. Use this to nudge direction mid-task (e.g. "focus on the auth module" while the agent is running tests). |
| `/goal <text>` | Set a standing goal the agent works toward across turns. After each turn an auxiliary judge model decides whether the goal is done; if not, the agent auto-continues. Subcommands: `/goal status`, `/goal pause`, `/goal resume`, `/goal clear`. Budget defaults to 20 turns (`goals.max_turns`); any real user message preempts the continuation loop, and state survives `/resume`. See [Persistent Goals](/user-guide/features/goals) for the full walkthrough. |
| `/subgoal <text>` | Append a user-supplied criterion to the active goal mid-loop. The continuation prompt surfaces all subgoals to the agent verbatim, and the judge factors them into its DONE/CONTINUE verdict — so the goal isn't marked done until the original goal **and** every subgoal are met. Subcommands: `/subgoal` (list), `/subgoal remove <N>`, `/subgoal clear`. Requires an active `/goal`. |
| `/resume [name]` | Resume a previously-named session |
| `/sessions` | Browse and resume previous sessions in an interactive picker |
| `/redraw` | Force a full UI repaint (recovers from terminal drift after tmux resize, mouse selection artifacts, etc.) |
| `/status` | Show session info — model, provider, profile, session ID, working directory, title, created/updated timestamps, token totals, agent-running state — followed by a local **Session recap** block (recent user/forecaster turn counts, tool result count, top tools used, last few files touched, the latest user prompt, and the latest forecast response). The recap is computed locally from the in-memory transcript; no LLM call, no prompt-cache impact. |
| `/agents` (alias: `/tasks`) | Show active agents and running tasks across the current session. |
| `/background <forecast note>` (alias: `/bg`, `/btw`) | Run a forecast-support note in a separate background session. The agent processes it independently — your current session stays free for other work. Results appear as a panel when the task finishes. See [CLI Background Sessions](/user-guide/cli#background-sessions). |
| `/branch [name]` (alias: `/fork`) | Branch the current session (explore a different path) |

### Configuration

| Command | Description |
|---------|-------------|
| `/config` | Show current configuration |
| `/model [model-name]` | Show or change the current model. Supports: `/model claude-sonnet-4`, `/model provider:model` (switch providers), `/model custom:model` (custom endpoint), `/model custom:name:model` (named custom provider), `/model custom` (auto-detect from endpoint), and user-defined aliases (`/model fav`, `/model grok` — see [Custom model aliases](#custom-model-aliases)). Use `--global` to persist the change to config.yaml. **Note:** `/model` can only switch between already-configured providers. To add a new provider, exit the session and run `superforecasting-agent model` from your terminal. |
| `/codex-runtime [auto\|codex_app_server\|on\|off]` | Toggle the optional [Codex app-server runtime](../user-guide/features/codex-app-server-runtime) for OpenAI/Codex models. `auto` (default) uses the standard chat-completions runtime; `codex_app_server` hands turns to a `codex app-server` subprocess for native shell, apply_patch, ChatGPT subscription auth, and migrated Codex plugins. Effective on next session. |
| `/verbose` | Cycle tool progress display: off → new → all → verbose. Can be [enabled for messaging](#notes) via config. |
| `/fast [normal\|fast\|status]` | Toggle fast mode — OpenAI Priority Processing / Anthropic Fast Mode. Options: `normal`, `fast`, `status`. |
| `/reasoning` | Manage reasoning effort and display (usage: /reasoning [level\|show\|hide]) |
| `/skin` | Show or change the display skin/theme |
| `/style [name]` | Switch forecast style overlays for this session. The legacy `/personality` spelling remains accepted as an alias. |
| `/statusbar` (alias: `/sb`) | Toggle the context/model status bar on or off |
| `/yolo` | Toggle YOLO mode — skip all dangerous command approval prompts. |
| `/footer [on\|off\|status]` | Toggle the gateway runtime-metadata footer on final replies (shows model, tool counts, timing). |
| `/busy [queue\|steer\|interrupt\|status]` | CLI-only: control what pressing Enter does while the forecast desk is working — queue the new message, steer mid-turn, or interrupt immediately. |
| `/indicator [ascii\|emoji\|markers\|unicode]` | CLI-only: pick the TUI busy-indicator style. |

### Tools & Skills

| Command | Description |
|---------|-------------|
| `/tools [list\|disable\|enable] [name...]` | Manage tools: list available tools, or disable/enable specific tools for the current session. Disabling a tool removes it from the agent's toolset and triggers a session reset. |
| `/toolsets` | List available toolsets |
| `/browser [connect\|disconnect\|status]` | Manage a local Chromium-family CDP connection. `connect` attaches browser tools to a running Chrome, Brave, Chromium, or Edge instance (default: `http://127.0.0.1:9222`). `disconnect` detaches. `status` shows current connection. Auto-launches a supported Chromium-family browser if no debugger is detected. |
| `/cron` | Manage scheduled tasks (list, add/create, edit, pause, resume, run, remove) |
| `/reload-mcp` (alias: `/reload_mcp`) | Reload MCP servers from config.yaml |
| `/reload-skills` (alias: `/reload_skills`) | Re-scan `~/.superforecasting-agent/skills/` for newly installed or removed skills; legacy `~/.hermes/skills/` remains readable. |
| `/reload` | Reload `.env` variables into the running session (picks up new API keys without restarting) |
| `/plugins` | List installed plugins and their status |

### Compatibility

These commands remain available for inherited workflows, optional messaging surfaces, or legacy skill systems, but they are not the primary forecast lifecycle.

| Command | Description |
|---------|-------------|
| `/personality` | Adjust a compatibility persona overlay; forecast protocol prompts remain authoritative. |
| `/voice [on\|off\|tts\|status]` | Toggle optional CLI voice mode and spoken playback. Recording uses `voice.record_key` (default: `Ctrl+B`). |
| `/skills` | Search, install, inspect, or manage optional skill playbooks from online registries. |
| `/bundles` | List optional skill bundles, which create aliases such as `/<name>` for multiple skills. |
| `/curator` | Optional background skill maintenance — `status`, `run`, `pin`, `archive`. See [Curator](/user-guide/features/curator). |
| `/kanban <action>` | Optional multi-profile collaboration board. Full `superforecasting-agent kanban` surface is available: `/kanban list`, `/kanban show t_abc`, `/kanban create "title" --assignee X`, `/kanban comment t_abc "text"`, `/kanban unblock t_abc`, `/kanban dispatch`, etc. See [Kanban slash command](/user-guide/features/kanban#kanban-slash-command). |
| `/platforms` (alias: `/gateway`) | Show optional gateway/messaging platform status. |
| `/handoff <platform>` | **CLI only.** Hand the current session off to a messaging platform (Telegram, Discord, Slack, WhatsApp, Signal, Matrix). Requires the gateway to be running and a home channel configured for the target platform (`/sethome` from the destination chat). See [Cross-Platform Handoff](/user-guide/sessions#cross-platform-handoff). |

### Info

| Command | Description |
|---------|-------------|
| `/help` | Show this help message |
| `/usage` | Show token usage, cost breakdown, session duration, and — when available from the active provider — an **Account limits** section with remaining quota / credits / plan usage pulled live from the provider's API. |
| `/insights` | Show usage insights and analytics (last 30 days) |
| `/platform <list\|pause\|resume> [name]` | Operate a running gateway platform. `/platform list` lists every adapter and its state (running, paused-by-breaker, manually-paused); `/platform pause <name>` stops dispatching new messages to that adapter without unloading it; `/platform resume <name>` re-enables it. The gateway also auto-pauses an adapter when its circuit breaker trips on repeated retryable failures (network / rate-limit / 5xx) — use `/platform resume <name>` to clear the breaker once the upstream is healthy. Available wherever the gateway is reachable (CLI session, Telegram, Discord, …). |
| `/paste` | Attach a clipboard image |
| `/copy [number]` | Copy the last forecast response to clipboard (or the Nth-from-last with a number). CLI-only. |
| `/image <path>` | Attach a local image file for your next forecast note. |
| `/debug` | Upload debug report (system info + logs) and get shareable links. Also available in messaging. |
| `/profile` | Show active profile name and home directory |
| `/gquota` | Show Google Gemini Code Assist quota usage with progress bars (only available when the `google-gemini-cli` provider is active). |

### Exit

| Command | Description |
|---------|-------------|
| `/quit` | Exit the CLI (also: `/exit`). See note on `/q` under `/queue` above. Pass `--delete` (or `-d`) — e.g. `/exit --delete` — to also permanently remove the current session's SQLite history and on-disk transcripts before exiting. Useful for privacy-sensitive or one-off tasks. |

### Dynamic CLI slash commands

Dynamic skill commands are optional compatibility playbooks. Use the forecast
lifecycle commands first unless a skill directly improves research, evidence
capture, modeling, or review.

| Command | Description |
|---------|-------------|
| `/<skill-name>` | Load any installed skill as an on-demand command. Example: `/gif-search`, `/github-pr-workflow`, `/excalidraw`. |
| `/skills ...` | Search, browse, inspect, install, audit, publish, and configure skills from registries and the official optional-skills catalog. |

### Quick Commands

User-defined quick commands map a short slash command to either a shell command or another slash command. Configure them in `~/.superforecasting-agent/config.yaml`:

```yaml
quick_commands:
  status:
    type: exec
    command: systemctl status superforecasting-agent
  deploy:
    type: exec
    command: scripts/deploy.sh
  inbox:
    type: alias
    target: /gmail unread
```

Then type `/status`, `/deploy`, or `/inbox` in the CLI or a messaging platform. Quick commands are resolved at dispatch time and may not appear in every built-in autocomplete/help table.

String-only prompt shortcuts are not supported as quick commands. Put longer reusable prompts in a skill, or use `type: alias` to point at an existing slash command.

### Custom model aliases

Define your own short names for models you use often, then reach them with `/model <alias>` in the CLI or any messaging platform. Aliases work identically in both, on session-only (default) and `--global` switches.

Two config formats are supported:

**Full form** — pin an exact model, provider, and optionally a base URL. Put this in `~/.superforecasting-agent/config.yaml`:

```yaml
model_aliases:
  fav:
    model: claude-sonnet-4.6
    provider: anthropic
  grok:
    model: grok-4
    provider: x-ai
  ollama-qwen:
    model: qwen3-coder:30b
    provider: custom
    base_url: http://localhost:11434/v1
```

**Short form** — `provider/model` in one string. Set from the shell without editing YAML:

```bash
superforecasting-agent config set model.aliases.fav anthropic/claude-opus-4.6
superforecasting-agent config set model.aliases.grok x-ai/grok-4
```

Then in chat:

```
/model fav            # session-only
/model grok --global  # also persists current-model change to config.yaml
```

User aliases take precedence over built-in short names, so naming an alias `sonnet`, `kimi`, `opus`, etc. will shadow the built-in. Alias names are case-insensitive.

### Alias Resolution

Commands support prefix matching: typing `/h` resolves to `/help`, `/mod` resolves to `/model`. When a prefix is ambiguous (matches multiple commands), the first match in registry order wins. Full command names and registered aliases always take priority over prefix matches.

## Messaging slash commands

The messaging gateway supports the following built-in commands inside Telegram, Discord, Slack, WhatsApp, Signal, Email, Home Assistant, and Teams chats:

| Command | Description |
|---------|-------------|
| `/new` | Start a new research session. |
| `/reset` | Reset research-session history. |
| `/status` | Show session info, followed by a local **Session recap** block (recent turn counts, top tools used, files touched, latest prompt + reply). |
| `/stop` | Kill all running background processes and interrupt the running agent. |
| `/model [provider:model]` | Show or change the model. Supports provider switches (`/model zai:glm-5`), custom endpoints (`/model custom:model`), named custom providers (`/model custom:local:qwen`), auto-detect (`/model custom`), and user-defined aliases (`/model fav`, `/model grok` — see [Custom model aliases](#custom-model-aliases)). Use `--global` to persist the change to config.yaml. **Note:** `/model` can only switch between already-configured providers. To add a new provider or set up API keys, use `superforecasting-agent model` from your terminal outside the active session. |
| `/codex-runtime [auto\|codex_app_server\|on\|off]` | Toggle the optional [Codex app-server runtime](../user-guide/features/codex-app-server-runtime). Persists to `model.openai_runtime` in config.yaml and evicts the cached agent so the next message picks up the new runtime. Effective on next session. |
| `/style [name]` | Switch forecast style overlays for the session. |
| `/personality [name]` | Adjust a compatibility persona overlay for the session; forecast protocol prompts remain authoritative. |
| `/fast [normal\|fast\|status]` | Toggle fast mode — OpenAI Priority Processing / Anthropic Fast Mode. |
| `/retry` | Retry the last message. |
| `/undo` | Remove the last exchange. |
| `/sethome` (alias: `/set-home`) | Mark the current conversation as the platform home channel for forecast review and cron deliveries. |
| `/compress [focus topic]` | Manually compress research-session context. Optional focus topic narrows what the summary preserves. |
| `/topic [off\|help\|session-id]` | **Telegram DM only.** Manage user-managed multi-session topic mode. `/topic` enables it or shows status; `/topic off` disables it and clears bindings; `/topic help` shows usage; `/topic <session-id>` inside a topic restores a previous session. See [Multi-session DM mode](/user-guide/messaging/telegram#multi-session-dm-mode-topic). |
| `/title [name]` | Set or show the session title. |
| `/resume [name]` | Resume a previously named session. |
| `/usage` | Show token usage, estimated cost breakdown (input/output), context window state, session duration, and — when available from the active provider — an **Account limits** section with remaining quota / credits pulled live from the provider's API. |
| `/insights [days]` | Show usage analytics. |
| `/reasoning [level\|show\|hide]` | Change reasoning effort or toggle reasoning display. |
| `/voice [on\|off\|tts\|join\|channel\|leave\|status]` | Control optional spoken replies in chat. `join`/`channel`/`leave` manage Discord voice-channel mode. |
| `/rollback [number]` | List or restore filesystem checkpoints. |
| `/background <forecast note>` | Run a forecast-support note in a separate background session. Results are delivered back to the same chat when the task finishes. See [Messaging Background Sessions](/user-guide/messaging/#background-sessions). |
| `/queue <forecast note>` (alias: `/q`) | Queue a forecast note for the next turn without interrupting the current one. |
| `/steer <forecast note>` | Inject a forecast note after the next tool call without interrupting — the model picks it up on its next iteration rather than as a new turn. |
| `/goal <text>` | Set a standing goal the agent works toward across turns. A judge model checks after each turn; if not done, the agent auto-continues until it is, you pause/clear it, or the turn budget (default 20) is hit. Subcommands: `/goal status`, `/goal pause`, `/goal resume`, `/goal clear`. Safe to run mid-agent for status/pause/clear; setting a new goal requires `/stop` first. See [Persistent Goals](/user-guide/features/goals). |
| `/footer [on\|off\|status]` | Toggle the runtime-metadata footer on final replies (shows model, tool counts, timing). |
| `/curator [status\|run\|pin\|archive]` | Optional background skill maintenance controls. |
| `/kanban <action>` | Drive the optional multi-profile, multi-project collaboration board from chat — identical argument surface to the CLI. Bypasses the running-agent guard, so `/kanban unblock t_abc`, `/kanban comment t_abc "…"`, `/kanban list --mine`, `/kanban boards switch <slug>`, etc. work mid-turn. `/kanban create …` auto-subscribes the originating chat to the new task's terminal events. See [Kanban slash command](/user-guide/features/kanban#kanban-slash-command). |
| `/reload-mcp` (alias: `/reload_mcp`) | Reload MCP servers from config. |
| `/yolo` | Toggle YOLO mode — skip all dangerous command approval prompts. |
| `/commands [page]` | Browse all commands and skills (paginated). |
| `/approve [session\|always]` | Approve and execute a pending dangerous command. `session` approves for this session only; `always` adds to permanent allowlist. |
| `/deny` | Reject a pending dangerous command. |
| `/update` | Update Superforecasting Agent to the latest version. |
| `/restart` | Gracefully restart the gateway after draining active runs. When the gateway comes back online, it sends a confirmation to the requester's chat/thread. |
| `/debug` | Upload debug report (system info + logs) and get shareable links. |
| `/help` | Show messaging help. |
| `/<skill-name>` | Invoke any installed skill by name. |

## Notes

- `/skin`, `/snapshot`, `/gquota`, `/reload`, `/tools`, `/toolsets`, `/browser`, `/config`, `/cron`, `/skills`, `/platforms`, `/paste`, `/image`, `/statusbar`, `/plugins`, `/busy`, `/indicator`, `/redraw`, `/clear`, `/history`, `/save`, `/copy`, `/handoff`, and `/quit` are **CLI-only** commands.
- `/verbose` is **CLI-only by default**, but can be enabled for messaging platforms by setting `display.tool_progress_command: true` in `config.yaml`. When enabled, it cycles the `display.tool_progress` mode and saves to config.
- `/sethome`, `/update`, `/restart`, `/approve`, `/deny`, `/topic`, and `/commands` are **messaging-only** commands.
- `/status`, `/background`, `/queue`, `/steer`, `/voice`, `/reload-mcp`, `/reload-skills`, `/rollback`, `/debug`, `/fast`, `/footer`, `/curator`, `/kanban`, `/sessions`, and `/yolo` work in **both** the CLI and the messaging gateway.
- `/voice join`, `/voice channel`, and `/voice leave` are only meaningful on Discord.

## Confirmation prompts for destructive commands

The CLI prompts before running slash commands that throw away unsaved session state. The current destructive set is:

| Command | What it destroys |
|---------|------------------|
| `/clear` | Clears the screen and starts a fresh session — current session ID and in-memory history are gone. |
| `/new` / `/reset` | Starts a fresh session (new session ID + empty history). |
| `/undo` | Removes the last user/forecaster exchange from history. |
| `/exit --delete` / `/quit --delete` | Exits **and** permanently deletes the current session's SQLite history and on-disk transcripts. |

For each of these the CLI opens a three-choice modal: **Approve Once** (proceed this time), **Always Approve** (proceed and persist `approvals.destructive_slash_confirm: false` so future destructive commands run without prompting), or **Cancel**.

Set `approvals.destructive_slash_confirm: false` in `~/.superforecasting-agent/config.yaml` to disable the prompts globally; set it back to `true` to re-enable. See [Security — Destructive slash command confirmation](../user-guide/security.md#dangerous-command-approval) for context.
