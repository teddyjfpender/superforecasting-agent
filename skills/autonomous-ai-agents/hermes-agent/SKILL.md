---
name: superforecasting-agent
description: "Configure, extend, or contribute to Superforecasting Agent."
version: 2.1.0
author: Superforecasting Agent + Teknium
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [superforecasting-agent, setup, configuration, multi-agent, spawning, cli, gateway, development]
    aliases: [hermes-agent]
    homepage: https://github.com/teddyjfpender/superforecasting-agent
    related_skills: [claude-code, codex, opencode]
---

# Superforecasting Agent

Superforecasting Agent is a CLI-first forecasting desk forked from the Hermes Agent runtime. It keeps useful inherited infrastructure such as provider adapters, tool execution, plugins, profiles, logging, sessions, gateway support, and editor integrations, but the product center is the durable forecast ledger.

What matters in this fork:

- **Forecast ledger** — scoreable questions, probability history, evidence, assumptions, model runs, resolutions, scores, postmortems, calibration lessons, and domain/topic error profiles are the durable state.
- **Learning loop** — scheduled self-checks, backtests, scoring, and postmortems exist to improve future forecasts rather than preserve generic chat memory.
- **Provider-agnostic runtime** — swap models and providers mid-workflow without changing the forecast lifecycle. Credential pools rotate across multiple API keys automatically.
- **Profiles and gateways** — run isolated forecast desks, optional messaging surfaces, and background automations when they help forecast review, evidence capture, or alerts.
- **Extensible** — plugins, MCP servers, custom tools, webhook triggers, cron scheduling, and the full Python ecosystem remain available when they improve forecasting workflows.

Use this skill when you need to configure, extend, troubleshoot, or contribute to the inherited runtime inside this Superforecasting Agent fork. For durable probability changes, evidence, scores, postmortems, and calibration updates, use the forecast ledger workflows rather than generic memory or skill notes.

**Docs:** use this repository's `website/docs/` tree and the fork PRD/context docs under `docs/plans/`.

## Quick Start

```bash
# Setup
superforecasting-agent setup

# Open the forecast desk
superforecasting-agent
forecast status

# Create a scoreable question
forecast new "Will X happen?" --resolution-criteria "Resolved by ..."

# Forecast-scoped chat remains available explicitly
superforecasting-agent chat -q "Help decompose this forecasting question."

# Change model/provider
superforecasting-agent model

# Check health
superforecasting-agent doctor
```

---

## CLI Reference

### Global Flags

```
superforecasting-agent [flags] [command]

  --version, -V             Show version
  --resume, -r SESSION      Resume session by ID or title
  --continue, -c [NAME]     Resume by name, or most recent session
  --worktree, -w            Isolated git worktree mode (parallel agents)
  --skills, -s SKILL        Preload skills (comma-separate or repeat)
  --profile, -p NAME        Use a named profile
  --yolo                    Skip dangerous command approval
  --pass-session-id         Include session ID in system prompt
```

Bare `superforecasting-agent` opens the forecast desk during the fork transition.
Use `forecast ...` for ledger lifecycle commands and `superforecasting-agent chat`
only when you explicitly want the inherited forecast-scoped chat runtime.

### Chat

```
superforecasting-agent chat [flags]
  -q, --query TEXT          Single query, non-interactive
  -m, --model MODEL         Model (e.g. anthropic/claude-sonnet-4)
  -t, --toolsets LIST       Comma-separated toolsets
  --provider PROVIDER       Force provider (openrouter, anthropic, nous, etc.)
  -v, --verbose             Verbose output
  -Q, --quiet               Suppress banner, spinner, tool previews
  --checkpoints             Enable filesystem checkpoints (/rollback)
  --source TAG              Session source tag (default: cli)
```

### Configuration

```
superforecasting-agent setup [section]      Interactive wizard (model|terminal|gateway|tools|agent)
superforecasting-agent model                Interactive model/provider picker
superforecasting-agent config               View current config
superforecasting-agent config edit          Open config.yaml in $EDITOR
superforecasting-agent config set KEY VAL   Set a config value
superforecasting-agent config path          Print config.yaml path
superforecasting-agent config env-path      Print .env path
superforecasting-agent config check         Check for missing/outdated config
superforecasting-agent config migrate       Update config with new options
superforecasting-agent login [--provider P] OAuth login (nous, openai-codex)
superforecasting-agent logout               Clear stored auth
superforecasting-agent doctor [--fix]       Check dependencies and config
superforecasting-agent status [--all]       Show component status
```

### Tools & Skills

```
superforecasting-agent tools                Interactive tool enable/disable (curses UI)
superforecasting-agent tools list           Show all tools and status
superforecasting-agent tools enable NAME    Enable a toolset
superforecasting-agent tools disable NAME   Disable a toolset

superforecasting-agent skills list          List installed skills
superforecasting-agent skills search QUERY  Search the skills hub
superforecasting-agent skills install ID    Install a skill (ID can be a hub identifier OR a direct https://…/SKILL.md URL; pass --name to override when frontmatter has no name)
superforecasting-agent skills inspect ID    Preview without installing
superforecasting-agent skills config        Enable/disable skills per platform
superforecasting-agent skills check         Check for updates
superforecasting-agent skills update        Update outdated skills
superforecasting-agent skills uninstall N   Remove a hub skill
superforecasting-agent skills publish PATH  Publish to registry
superforecasting-agent skills browse        Browse all available skills
superforecasting-agent skills tap add REPO  Add a GitHub repo as skill source
```

### MCP Servers

```
superforecasting-agent mcp serve            Run Superforecasting Agent as an MCP server
superforecasting-agent mcp add NAME         Add an MCP server (--url or --command)
superforecasting-agent mcp remove NAME      Remove an MCP server
superforecasting-agent mcp list             List configured servers
superforecasting-agent mcp test NAME        Test connection
superforecasting-agent mcp configure NAME   Toggle tool selection
```

### Gateway (Messaging Platforms)

```
superforecasting-agent gateway run          Start gateway foreground
superforecasting-agent gateway install      Install as background service
superforecasting-agent gateway start/stop   Control the service
superforecasting-agent gateway restart      Restart the service
superforecasting-agent gateway status       Check status
superforecasting-agent gateway setup        Configure platforms
```

Supported platforms: Telegram, Discord, Slack, WhatsApp, Signal, Email, SMS, Matrix, Mattermost, Home Assistant, DingTalk, Feishu, WeCom, BlueBubbles (iMessage), Weixin (WeChat), API Server, Webhooks. Open WebUI connects via the API Server adapter.

Platform docs: /user-guide/messaging/

### Sessions

```
superforecasting-agent sessions list        List recent forecast sessions
superforecasting-agent sessions browse      Interactive picker
superforecasting-agent sessions export OUT  Export to JSONL
superforecasting-agent sessions rename ID T Rename a forecast session
superforecasting-agent sessions delete ID   Delete a forecast session
superforecasting-agent sessions prune       Clean up old forecast sessions (--older-than N days)
superforecasting-agent sessions stats       Session store statistics
```

### Cron Jobs

```
superforecasting-agent cron list            List jobs (--all for disabled)
superforecasting-agent cron create SCHED    Create: '30m', 'every 2h', '0 9 * * *'
superforecasting-agent cron edit ID         Edit schedule, prompt, delivery
superforecasting-agent cron pause/resume ID Control job state
superforecasting-agent cron run ID          Trigger on next tick
superforecasting-agent cron remove ID       Delete a job
superforecasting-agent cron status          Scheduler status
```

### Webhooks

```
superforecasting-agent webhook subscribe N  Create route at /webhooks/<name>
superforecasting-agent webhook list         List subscriptions
superforecasting-agent webhook remove NAME  Remove a subscription
superforecasting-agent webhook test NAME    Send a test POST
```

### Profiles

```
superforecasting-agent profile list         List all profiles
superforecasting-agent profile create NAME  Create (--clone, --clone-all, --clone-from)
superforecasting-agent profile use NAME     Set sticky default
superforecasting-agent profile delete NAME  Delete a profile
superforecasting-agent profile show NAME    Show details
superforecasting-agent profile alias NAME   Manage wrapper scripts
superforecasting-agent profile rename A B   Rename a profile
superforecasting-agent profile export NAME  Export to tar.gz
superforecasting-agent profile import FILE  Import from archive
```

### Credential Pools

```
superforecasting-agent auth add             Interactive credential wizard
superforecasting-agent auth list [PROVIDER] List pooled credentials
superforecasting-agent auth remove P INDEX  Remove by provider + index
superforecasting-agent auth reset PROVIDER  Clear exhaustion status
```

### Other

```
superforecasting-agent insights [--days N]  Usage analytics
superforecasting-agent update               Update to latest version
superforecasting-agent pairing list/approve/revoke  DM authorization
superforecasting-agent plugins list/install/remove  Plugin management
superforecasting-agent honcho setup/status  Honcho memory integration (requires honcho plugin)
superforecasting-agent memory setup/status/off  Memory provider config
superforecasting-agent completion bash|zsh  Shell completions
superforecasting-agent acp                  ACP server (IDE integration)
superforecasting-agent claw migrate         Migrate from OpenClaw
superforecasting-agent uninstall            Uninstall Superforecasting Agent
```

---

## Slash Commands (In-Session)

Type these during an interactive forecast session. New commands land fairly
often; if something below looks stale, run `/help` in-session for the
authoritative list or see the [live slash commands reference](/reference/slash-commands).
The registry of record is `hermes_cli/commands.py` — every consumer
(autocomplete, Telegram menu, Slack mapping, `/help`) derives from it.

### Session Control
```
/new (/reset)        Fresh forecast session
/clear               Clear screen + new forecast session (CLI)
/retry               Resend last forecast note
/undo                Remove last forecast exchange
/title [name]        Name the forecast session
/compress            Manually compress context
/stop                Kill background processes
/rollback [N]        Restore filesystem checkpoint
/snapshot [sub]      Create or restore state snapshots of Superforecasting Agent config/state (CLI)
/background <prompt> Run prompt in background
/queue <prompt>      Queue for next turn
/steer <prompt>      Inject a message after the next tool call without interrupting
/agents (/tasks)     Show active agents and running tasks
/resume [name]       Resume a named forecast session
/goal [text|sub]     Set a standing goal Superforecasting Agent works on across turns until achieved
                     (subcommands: status, pause, resume, clear)
/redraw              Force a full UI repaint (CLI)
```

### Configuration
```
/config              Show config (CLI)
/model [name]        Show or change model
/style [name]        Set forecast style (`/personality` remains a legacy alias)
/reasoning [level]   Set reasoning (none|minimal|low|medium|high|xhigh|show|hide)
/verbose             Cycle: off → new → all → verbose
/voice [on|off|tts]  Voice mode
/yolo                Toggle approval bypass
/busy [sub]          Control what Enter does while Superforecasting Agent is working (CLI)
                     (subcommands: queue, steer, interrupt, status)
/indicator [style]   Pick the TUI busy-indicator style (CLI)
                     (styles: markers, emoji, unicode, ascii)
/footer [on|off]     Toggle gateway runtime-metadata footer on final replies
/skin [name]         Change theme (CLI)
/statusbar           Toggle status bar (CLI)
```

### Tools & Skills
```
/tools               Manage tools (CLI)
/toolsets            List toolsets (CLI)
/skills              Search/install skills (CLI)
/skill <name>        Load a skill into session
/reload-skills       Re-scan ~/.superforecasting-agent/skills/ for added/removed skills
/reload              Reload .env variables into the running session (CLI)
/reload-mcp          Reload MCP servers
/cron                Manage cron jobs (CLI)
/curator [sub]       Background skill maintenance (status, run, pin, archive, …)
/kanban [sub]        Multi-profile collaboration board (tasks, links, comments)
/plugins             List plugins (CLI)
```

### Gateway
```
/approve             Approve a pending command (gateway)
/deny                Deny a pending command (gateway)
/restart             Restart gateway (gateway)
/sethome             Set current conversation as scheduled forecast-review delivery channel (gateway)
/update              Update Superforecasting Agent to latest (gateway)
/topic [sub]         Enable or inspect Telegram DM topic sessions (gateway)
/platforms (/gateway) Show platform connection status (gateway)
```

### Utility
```
/branch (/fork)      Branch the current forecast session
/fast                Toggle priority/fast processing
/browser             Open CDP browser connection
/history             Show conversation history (CLI)
/save                Save conversation to file (CLI)
/copy [N]            Copy the last forecast response to clipboard (CLI)
/paste               Attach clipboard image (CLI)
/image               Attach local image file (CLI)
```

### Info
```
/help                Show commands
/commands [page]     Browse all commands (gateway)
/usage               Token usage
/insights [days]     Usage analytics
/gquota              Show Google Gemini Code Assist quota usage (CLI)
/status              Session info (gateway)
/profile             Active profile info
/debug               Upload debug report (system info + logs) and get shareable links
```

### Exit
```
/quit (/exit, /q)    Exit CLI
```

---

## Key Paths & Config

```
~/.superforecasting-agent/config.yaml       Main configuration
~/.superforecasting-agent/.env              API keys and secrets
$HERMES_HOME/skills/        Installed skills
~/.superforecasting-agent/sessions/         Session transcripts
~/.superforecasting-agent/logs/             Gateway and error logs
~/.superforecasting-agent/auth.json         OAuth tokens and credential pools
~/.superforecasting-agent/superforecasting-agent/  Source code (if git-installed)
```

Profiles use `~/.superforecasting-agent/profiles/<name>/` with the same layout.

### Config Sections

Edit with `superforecasting-agent config edit` or `superforecasting-agent config set section.key value`.

| Section | Key options |
|---------|-------------|
| `model` | `default`, `provider`, `base_url`, `api_key`, `context_length` |
| `agent` | `max_turns` (90), `tool_use_enforcement` |
| `terminal` | `backend` (local/docker/ssh/modal), `cwd`, `timeout` (180) |
| `compression` | `enabled`, `threshold` (0.50), `target_ratio` (0.20) |
| `display` | `skin`, `tool_progress`, `show_reasoning`, `show_cost` |
| `stt` | `enabled`, `provider` (local/groq/openai/mistral) |
| `tts` | `provider` (edge/elevenlabs/openai/minimax/mistral/neutts) |
| `memory` | `memory_enabled`, `user_profile_enabled`, `provider` |
| `security` | `tirith_enabled`, `website_blocklist` |
| `delegation` | `model`, `provider`, `base_url`, `api_key`, `max_iterations` (50), `reasoning_effort` |
| `checkpoints` | `enabled`, `max_snapshots` (50) |

Full config reference: /user-guide/configuration

### Providers

20+ providers supported. Set via `superforecasting-agent model` or `superforecasting-agent setup`.

| Provider | Auth | Key env var |
|----------|------|-------------|
| OpenRouter | API key | `OPENROUTER_API_KEY` |
| Anthropic | API key | `ANTHROPIC_API_KEY` |
| Nous Portal | OAuth | `superforecasting-agent auth` |
| OpenAI Codex | OAuth | `superforecasting-agent auth` |
| GitHub Copilot | Token | `COPILOT_GITHUB_TOKEN` |
| Google Gemini | API key | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| DeepSeek | API key | `DEEPSEEK_API_KEY` |
| xAI / Grok | API key | `XAI_API_KEY` |
| Hugging Face | Token | `HF_TOKEN` |
| Z.AI / GLM | API key | `GLM_API_KEY` |
| MiniMax | API key | `MINIMAX_API_KEY` |
| MiniMax CN | API key | `MINIMAX_CN_API_KEY` |
| Kimi / Moonshot | API key | `KIMI_API_KEY` |
| Alibaba / DashScope | API key | `DASHSCOPE_API_KEY` |
| Xiaomi MiMo | API key | `XIAOMI_API_KEY` |
| Kilo Code | API key | `KILOCODE_API_KEY` |
| AI Gateway (Vercel) | API key | `AI_GATEWAY_API_KEY` |
| OpenCode Zen | API key | `OPENCODE_ZEN_API_KEY` |
| OpenCode Go | API key | `OPENCODE_GO_API_KEY` |
| Qwen OAuth | OAuth | `superforecasting-agent login --provider qwen-oauth` |
| Custom endpoint | Config | `model.base_url` + `model.api_key` in config.yaml |
| GitHub Copilot ACP | External | `COPILOT_CLI_PATH` or Copilot CLI |

Full provider docs: /integrations/providers

### Toolsets

Enable/disable via `superforecasting-agent tools` (interactive) or `superforecasting-agent tools enable/disable NAME`.

| Toolset | What it provides |
|---------|-----------------|
| `web` | Web search and content extraction |
| `search` | Web search only (subset of `web`) |
| `browser` | Browser automation (Browserbase, Camofox, or local Chromium) |
| `terminal` | Shell commands and process management |
| `file` | File read/write/search/patch |
| `code_execution` | Sandboxed Python execution |
| `vision` | Image analysis |
| `image_gen` | AI image generation |
| `video` | Video analysis and generation |
| `tts` | Text-to-speech |
| `skills` | Skill browsing and management |
| `memory` | Persistent cross-session memory |
| `session_search` | Search past conversations |
| `delegation` | Subagent task delegation |
| `cronjob` | Scheduled task management |
| `clarify` | Ask user clarifying questions |
| `messaging` | Cross-platform message sending |
| `todo` | In-session task planning and tracking |
| `kanban` | Multi-agent work-queue tools (gated to workers) |
| `debugging` | Extra introspection/debug tools (off by default) |
| `safe` | Minimal, low-risk toolset for locked-down sessions |
| `spotify` | Spotify playback and playlist control |
| `homeassistant` | Smart home control (off by default) |
| `discord` | Discord integration tools |
| `discord_admin` | Discord admin/moderation tools |
| `feishu_doc` | Feishu (Lark) document tools |
| `feishu_drive` | Feishu (Lark) drive tools |
| `yuanbao` | Yuanbao integration tools |
| `rl` | Reinforcement learning tools (off by default) |
| `moa` | Mixture of Agents (off by default) |

Full enumeration lives in `toolsets.py` as the `TOOLSETS` dict; `_HERMES_CORE_TOOLS` is the default bundle most platforms inherit from.

Tool changes take effect on `/reset` (new forecast session). They do NOT apply mid-conversation to preserve prompt caching.

---

## Security & Privacy Toggles

Common "why is Superforecasting Agent doing X to my output / tool calls / commands?" toggles — and the exact commands to change them. Most of these need a fresh forecast session (`/reset` in chat, or start a new `superforecasting-agent` invocation) because they're read once at startup.

### Secret redaction in tool output

Secret redaction is **off by default** — tool output (terminal stdout, `read_file`, web content, subagent summaries, etc.) passes through unmodified. If the user wants Superforecasting Agent to auto-mask strings that look like API keys, tokens, and secrets before they enter the conversation context and logs:

```bash
superforecasting-agent config set security.redact_secrets true       # enable globally
```

**Restart required.** `security.redact_secrets` is snapshotted at import time — toggling it mid-session (e.g. via `export HERMES_REDACT_SECRETS=true` from a tool call) will NOT take effect for the running process. Tell the user to run `superforecasting-agent config set security.redact_secrets true` in a terminal, then start a new forecast session. This is deliberate — it prevents an LLM from flipping the toggle on itself mid-task.

Disable again with:
```bash
superforecasting-agent config set security.redact_secrets false
```

### PII redaction in gateway messages

Separate from secret redaction. When enabled, the gateway hashes user IDs and strips phone numbers from the session context before it reaches the model:

```bash
superforecasting-agent config set privacy.redact_pii true    # enable
superforecasting-agent config set privacy.redact_pii false   # disable (default)
```

### Command approval prompts

By default (`approvals.mode: manual`), Superforecasting Agent prompts the user before running shell commands flagged as destructive (`rm -rf`, `git reset --hard`, etc.). The modes are:

- `manual` — always prompt (default)
- `smart` — use an auxiliary LLM to auto-approve low-risk commands, prompt on high-risk
- `off` — skip all approval prompts (equivalent to `--yolo`)

```bash
superforecasting-agent config set approvals.mode smart       # recommended middle ground
superforecasting-agent config set approvals.mode off         # bypass everything (not recommended)
```

Per-invocation bypass without changing config:
- `superforecasting-agent --yolo …`
- `export HERMES_YOLO_MODE=1`

Note: YOLO / `approvals.mode: off` does NOT turn off secret redaction. They are independent.

### Shell hooks allowlist

Some shell-hook integrations require explicit allowlisting before they fire. Managed via `~/.superforecasting-agent/shell-hooks-allowlist.json` — prompted interactively the first time a hook wants to run.

### Disabling the web/browser/image-gen tools

To keep the model away from network or media tools entirely, open `superforecasting-agent tools` and toggle per-platform. Takes effect on next session (`/reset`). See the Tools & Skills section above.

---

## Voice & Transcription

### STT (Voice → Text)

Voice messages from messaging platforms are auto-transcribed.

Provider priority (auto-detected):
1. **Local faster-whisper** — free, no API key: `pip install faster-whisper`
2. **Groq Whisper** — free tier: set `GROQ_API_KEY`
3. **OpenAI Whisper** — paid: set `VOICE_TOOLS_OPENAI_KEY`
4. **Mistral Voxtral** — set `MISTRAL_API_KEY`

Config:
```yaml
stt:
  enabled: true
  provider: local        # local, groq, openai, mistral
  local:
    model: base          # tiny, base, small, medium, large-v3
```

### TTS (Text → Voice)

| Provider | Env var | Free? |
|----------|---------|-------|
| Edge TTS | None | Yes (default) |
| ElevenLabs | `ELEVENLABS_API_KEY` | Free tier |
| OpenAI | `VOICE_TOOLS_OPENAI_KEY` | Paid |
| MiniMax | `MINIMAX_API_KEY` | Paid |
| Mistral (Voxtral) | `MISTRAL_API_KEY` | Paid |
| NeuTTS (local) | None (`pip install neutts[all]` + `espeak-ng`) | Free |

Voice commands: `/voice on` (voice-to-voice), `/voice tts` (always voice), `/voice off`.

---

## Spawning Additional Superforecasting Agent Instances

Run additional Superforecasting Agent processes as fully independent subprocesses — separate sessions, tools, and environments.

### When to Use This vs delegate_task

| | `delegate_task` | Spawning `superforecasting-agent` process |
|-|-----------------|--------------------------|
| Isolation | Separate conversation, shared process | Fully independent process |
| Duration | Minutes (bounded by parent loop) | Hours/days |
| Tool access | Subset of parent's tools | Full tool access |
| Interactive | No | Yes (PTY mode) |
| Use case | Quick parallel subtasks | Long autonomous missions |

### One-Shot Mode

```
terminal(command="superforecasting-agent chat -q 'Summarize evidence and base rates for forecast fq_123'", timeout=300)

# Background for long tasks:
terminal(command="superforecasting-agent chat -q 'Research new evidence for the active macro forecast book'", background=true)
```

### Interactive PTY Mode (via tmux)

Superforecasting Agent uses prompt_toolkit, which requires a real terminal. Use tmux for interactive spawning:

```
# Start
terminal(command="tmux new-session -d -s agent1 -x 120 -y 40 'superforecasting-agent'", timeout=10)

# Wait for startup, then send a message
terminal(command="sleep 8 && tmux send-keys -t agent1 'Review stale forecasts and propose cited updates' Enter", timeout=15)

# Read output
terminal(command="sleep 20 && tmux capture-pane -t agent1 -p", timeout=5)

# Send follow-up
terminal(command="tmux send-keys -t agent1 'Export the highest-priority forecast packet' Enter", timeout=5)

# Exit
terminal(command="tmux send-keys -t agent1 '/exit' Enter && sleep 2 && tmux kill-session -t agent1", timeout=10)
```

### Multi-Agent Coordination

```
# Agent A: policy desk
terminal(command="tmux new-session -d -s backend -x 120 -y 40 'superforecasting-agent -w'", timeout=10)
terminal(command="sleep 8 && tmux send-keys -t backend 'Research policy forecasts closing this month' Enter", timeout=15)

# Agent B: market desk
terminal(command="tmux new-session -d -s frontend -x 120 -y 40 'superforecasting-agent -w'", timeout=10)
terminal(command="sleep 8 && tmux send-keys -t frontend 'Check market-implied baselines for active forecasts' Enter", timeout=15)

# Check progress, relay context between them
terminal(command="tmux capture-pane -t backend -p | tail -30", timeout=5)
terminal(command="tmux send-keys -t frontend 'Here are policy-desk evidence refs to compare with market baselines: ...' Enter", timeout=5)
```

### Session Resume

```
# Resume most recent session
terminal(command="tmux new-session -d -s resumed 'superforecasting-agent --continue'", timeout=10)

# Resume specific session
terminal(command="tmux new-session -d -s resumed 'superforecasting-agent --resume 20260225_143052_a1b2c3'", timeout=10)
```

### Tips

- **Prefer `delegate_task` for quick subtasks** — less overhead than spawning a full process
- **Use `-w` (worktree mode)** when spawning agents that edit code — prevents git conflicts
- **Set timeouts** for one-shot mode — complex tasks can take 5-10 minutes
- **Use `forecast ...` for durable ledger writes** and `superforecasting-agent chat -q` only for ephemeral forecast-scoped analysis — no PTY needed
- **Use tmux for interactive sessions** — raw PTY mode has `\r` vs `\n` issues with prompt_toolkit
- **For scheduled tasks**, use the `cronjob` tool instead of spawning — handles delivery and retry

---

## Durable & Background Systems

Four systems run alongside the main conversation loop. Quick reference
here; full developer notes live in `AGENTS.md`, user-facing docs under
`website/docs/user-guide/features/`.

### Delegation (`delegate_task`)

Synchronous subagent spawn — the parent waits for the child's summary
before continuing its own loop. Isolated context + terminal session.

- **Single:** `delegate_task(goal, context, toolsets)`.
- **Batch:** `delegate_task(tasks=[{goal, ...}, ...])` runs children in
  parallel, capped by `delegation.max_concurrent_children` (default 3).
- **Roles:** `leaf` (default; cannot re-delegate) vs `orchestrator`
  (can spawn its own workers, bounded by `delegation.max_spawn_depth`).
- **Not durable.** If the parent is interrupted, the child is
  cancelled. For work that must outlive the turn, use `cronjob` or
  `terminal(background=True, notify_on_complete=True)`.

Config: `delegation.*` in `config.yaml`.

### Cron (scheduled jobs)

Durable scheduler — `cron/jobs.py` + `cron/scheduler.py`. Drive it via
the `cronjob` tool, the `superforecasting-agent cron` CLI (`list`, `add`, `edit`,
`pause`, `resume`, `run`, `remove`), or the `/cron` slash command.

- **Schedules:** duration (`"30m"`, `"2h"`), "every" phrase
  (`"every monday 9am"`), 5-field cron (`"0 9 * * *"`), or ISO timestamp.
- **Per-job knobs:** `skills`, `model`/`provider` override, `script`
  (pre-run data collection; `no_agent=True` makes the script the whole
  job), `context_from` (chain job A's output into job B), `workdir`
  (run in a specific dir with its `AGENTS.md` / `CLAUDE.md` loaded),
  multi-platform delivery.
- **Invariants:** 3-minute hard interrupt per run, `.tick.lock` file
  prevents duplicate ticks across processes, cron sessions pass
  `skip_memory=True` by default, and cron deliveries are framed with a
  header/footer instead of being mirrored into the target gateway
  session (keeps role alternation intact).

User docs: /user-guide/features/cron

### Curator (skill lifecycle)

Background maintenance for agent-created skills. Tracks usage, marks
idle skills stale, archives stale ones, keeps a pre-run tar.gz backup
so nothing is lost.

- **CLI:** `superforecasting-agent curator <verb>` — `status`, `run`, `pause`, `resume`,
  `pin`, `unpin`, `archive`, `restore`, `prune`, `backup`, `rollback`.
- **Slash:** `/curator <subcommand>` mirrors the CLI.
- **Scope:** only touches skills with `created_by: "agent"` provenance.
  Bundled + hub-installed skills are off-limits. **Never deletes** —
  max destructive action is archive. Pinned skills are exempt from
  every auto-transition and every LLM review pass.
- **Telemetry:** sidecar at `~/.superforecasting-agent/skills/.usage.json` holds
  per-skill `use_count`, `view_count`, `patch_count`,
  `last_activity_at`, `state`, `pinned`.

Config: `curator.*` (`enabled`, `interval_hours`, `min_idle_hours`,
`stale_after_days`, `archive_after_days`, `backup.*`).
User docs: /user-guide/features/curator

### Kanban (multi-agent work queue)

Durable SQLite board for multi-profile / multi-worker collaboration.
Users drive it via `superforecasting-agent kanban <verb>`; dispatcher-spawned workers
see a focused `kanban_*` toolset gated by `HERMES_KANBAN_TASK`, and
orchestrator profiles can opt into the broader `kanban` toolset. Normal
sessions still have zero `kanban_*` schema footprint unless configured.

- **CLI verbs (common):** `init`, `create`, `list` (alias `ls`),
  `show`, `assign`, `link`, `unlink`, `comment`, `complete`, `block`,
  `unblock`, `archive`, `tail`. Less common: `watch`, `stats`, `runs`,
  `log`, `dispatch`, `daemon`, `gc`.
- **Worker/orchestrator toolset:** `kanban_show`, `kanban_complete`,
  `kanban_block`, `kanban_heartbeat`, `kanban_comment`, `kanban_create`,
  `kanban_link`; profiles that explicitly enable the `kanban` toolset
  outside a dispatcher-spawned task also get `kanban_list` and
  `kanban_unblock` for board routing.
- **Dispatcher** runs inside the gateway by default
  (`kanban.dispatch_in_gateway: true`) — reclaims stale claims,
  promotes ready tasks, atomically claims, spawns assigned profiles.
  Auto-blocks a task after `failure_limit` consecutive spawn failures
  (default 2; configurable via `kanban.failure_limit` or per-task
  `max_retries`).
- **Isolation:** board is the hard boundary (workers get
  `HERMES_KANBAN_BOARD` pinned in env); tenant is a soft namespace
  within a board for workspace-path + memory-key isolation.

User docs: /user-guide/features/kanban

---

## Windows-Specific Quirks

Superforecasting Agent runs natively on Windows (PowerShell, cmd, Windows Terminal, git-bash
mintty, VS Code integrated terminal). Most of it just works, but a handful
of differences between Win32 and POSIX have bitten us — document new ones
here as you hit them so the next person (or the next session) doesn't
rediscover them from scratch.

### Input / Keybindings

**Alt+Enter doesn't insert a newline.** Windows Terminal intercepts Alt+Enter
at the terminal layer to toggle fullscreen — the keystroke never reaches
prompt_toolkit. Use **Ctrl+Enter** instead. Windows Terminal delivers
Ctrl+Enter as LF (`c-j`), distinct from plain Enter (`c-m` / CR), and the
CLI binds `c-j` to newline insertion on `win32` only (see
`_bind_prompt_submit_keys` + the Windows-only `c-j` binding in `cli.py`).
Side effect: the raw Ctrl+J keystroke also inserts a newline on Windows —
unavoidable, because Windows Terminal collapses Ctrl+Enter and Ctrl+J to
the same keycode at the Win32 console API layer. No conflicting binding
existed for Ctrl+J on Windows, so this is a harmless side effect.

mintty / git-bash behaves the same (fullscreen on Alt+Enter) unless you
disable Alt+Fn shortcuts in Options → Keys. Easier to just use Ctrl+Enter.

**Diagnosing keybindings.** Run `python scripts/keystroke_diagnostic.py`
(repo root) to see exactly how prompt_toolkit identifies each keystroke
in the current terminal. Answers questions like "does Shift+Enter come
through as a distinct key?" (almost never — most terminals collapse it
to plain Enter) or "what byte sequence is my terminal sending for
Ctrl+Enter?" This is how the Ctrl+Enter = c-j fact was established.

### Config / Files

**HTTP 400 "No models provided" on first run.** `config.yaml` was saved
with a UTF-8 BOM (common when Windows apps write it). Re-save as UTF-8
without BOM. `superforecasting-agent config edit` writes without BOM; manual edits in
Notepad are the usual culprit.

### `execute_code` / Sandbox

**WinError 10106** ("The requested service provider could not be loaded
or initialized") from the sandbox child process — it can't create an
`AF_INET` socket, so the loopback-TCP RPC fallback fails before
`connect()`. Root cause is usually **not** a broken Winsock LSP; it's
Superforecasting Agent's own env scrubber dropping `SYSTEMROOT` / `WINDIR` / `COMSPEC`
from the child env. Python's `socket` module needs `SYSTEMROOT` to locate
`mswsock.dll`. Fixed via the `_WINDOWS_ESSENTIAL_ENV_VARS` allowlist in
`tools/code_execution_tool.py`. If you still hit it, echo `os.environ`
inside an `execute_code` block to confirm `SYSTEMROOT` is set. Full
diagnostic recipe in `references/execute-code-sandbox-env-windows.md`.

### Testing / Contributing

**`scripts/run_tests.sh` doesn't work as-is on Windows** — it looks for
POSIX venv layouts (`.venv/bin/activate`). The Superforecasting Agent-installed venv at
`venv/Scripts/` has no pip or pytest either (stripped for install size).
Workaround: install `pytest + pytest-xdist + pyyaml` into a system Python
3.11 user site, then invoke pytest directly with `PYTHONPATH` set:

```bash
"/c/Program Files/Python311/python" -m pip install --user pytest pytest-xdist pyyaml
export PYTHONPATH="$(pwd)"
"/c/Program Files/Python311/python" -m pytest tests/foo/test_bar.py -v --tb=short -n 0
```

Use `-n 0`, not `-n 4` — `pyproject.toml`'s default `addopts` already
includes `-n`, and the wrapper's CI-parity guarantees don't apply off POSIX.

**POSIX-only tests need skip guards.** Common markers already in the codebase:
- Symlinks — elevated privileges on Windows
- `0o600` file modes — POSIX mode bits not enforced on NTFS by default
- `signal.SIGALRM` — Unix-only (see `tests/conftest.py::_enforce_test_timeout`)
- Winsock / Windows-specific regressions — `@pytest.mark.skipif(sys.platform != "win32", ...)`

Use the existing skip-pattern style (`sys.platform == "win32"` or
`sys.platform.startswith("win")`) to stay consistent with the rest of the
suite.

### Path / Filesystem

**Line endings.** Git may warn `LF will be replaced by CRLF the next time
Git touches it`. Cosmetic — the repo's `.gitattributes` normalizes. Don't
let editors auto-convert committed POSIX-newline files to CRLF.

**Forward slashes work almost everywhere.** `C:/Users/...` is accepted by
every Superforecasting Agent tool and most Windows APIs. Prefer forward slashes in code
and logs — avoids shell-escaping backslashes in bash.

---

## Troubleshooting

### Voice not working
1. Check `stt.enabled: true` in config.yaml
2. Verify provider: `pip install faster-whisper` or set API key
3. In gateway: `/restart`. In CLI: exit and relaunch.

### Tool not available
1. `superforecasting-agent tools` — check if toolset is enabled for your platform
2. Some tools need env vars (check `.env`)
3. `/reset` after enabling tools

### Model/provider issues
1. `superforecasting-agent doctor` — check config and dependencies
2. `superforecasting-agent login` — re-authenticate OAuth providers
3. Check `.env` has the right API key
4. **Copilot 403**: `gh auth login` tokens do NOT work for Copilot API. You must use the Copilot-specific OAuth device code flow via `superforecasting-agent model` → GitHub Copilot.

### Changes not taking effect
- **Tools/skills:** `/reset` starts a new forecast session with updated toolset
- **Config changes:** In gateway: `/restart`. In CLI: exit and relaunch.
- **Code changes:** Restart the CLI or gateway process

### Skills not showing
1. `superforecasting-agent skills list` — verify installed
2. `superforecasting-agent skills config` — check platform enablement
3. Load explicitly: `/skill name` or `superforecasting-agent -s name`

### Gateway issues
Check logs first:
```bash
grep -i "failed to send\|error" ~/.superforecasting-agent/logs/gateway.log | tail -20
```

Common gateway problems:
- **Gateway dies on SSH logout**: Enable linger: `sudo loginctl enable-linger $USER`
- **Gateway dies on WSL2 close**: WSL2 requires `systemd=true` in `/etc/wsl.conf` for systemd services to work. Without it, gateway falls back to `nohup` (dies when session closes).
- **Gateway crash loop**: Reset the failed state: `systemctl --user reset-failed superforecasting-agent-gateway`

### Platform-specific issues
- **Discord bot silent**: Must enable **Message Content Intent** in Bot → Privileged Gateway Intents.
- **Slack bot only works in DMs**: Must subscribe to `message.channels` event. Without it, the bot ignores public channels.
- **Windows-specific issues** (`Alt+Enter` newline, WinError 10106, UTF-8 BOM config, test suite, line endings): see the dedicated **Windows-Specific Quirks** section above.

### Auxiliary models not working
If `auxiliary` tasks (vision, compression, session_search) fail silently, the `auto` provider can't find a backend. Either set `OPENROUTER_API_KEY` or `GOOGLE_API_KEY`, or explicitly configure each auxiliary task's provider:
```bash
superforecasting-agent config set auxiliary.vision.provider <your_provider>
superforecasting-agent config set auxiliary.vision.model <model_name>
```

---

## Where to Find Things

| Looking for... | Location |
|----------------|----------|
| Config options | `superforecasting-agent config edit` or [Configuration docs](/user-guide/configuration) |
| Available tools | `superforecasting-agent tools list` or [Tools reference](/reference/tools-reference) |
| Slash commands | `/help` in session or [Slash commands reference](/reference/slash-commands) |
| Skills catalog | `superforecasting-agent skills browse` or [Skills catalog](/reference/skills-catalog) |
| Provider setup | `superforecasting-agent model` or [Providers guide](/integrations/providers) |
| Platform setup | `superforecasting-agent gateway setup` or [Messaging docs](/user-guide/messaging/) |
| MCP servers | `superforecasting-agent mcp list` or [MCP guide](/user-guide/features/mcp) |
| Profiles | `superforecasting-agent profile list` or [Profiles docs](/user-guide/profiles) |
| Cron jobs | `superforecasting-agent cron list` or [Cron docs](/user-guide/features/cron) |
| Memory | `superforecasting-agent memory status` or [Memory docs](/user-guide/features/memory) |
| Env variables | `superforecasting-agent config env-path` or [Env vars reference](/reference/environment-variables) |
| CLI commands | `superforecasting-agent --help` or [CLI reference](/reference/cli-commands) |
| Gateway logs | `~/.superforecasting-agent/logs/gateway.log` |
| Session files | `~/.superforecasting-agent/sessions/` or `superforecasting-agent sessions browse` |
| Source code | `~/.superforecasting-agent/superforecasting-agent/` |

---

## Contributor Quick Reference

For occasional contributors and PR authors. Full developer docs: /developer-guide/

### Project Layout

```
superforecasting-agent/
├── run_agent.py          # AIAgent — core conversation loop
├── model_tools.py        # Tool discovery and dispatch
├── toolsets.py           # Toolset definitions
├── cli.py                # Interactive forecast CLI (ForecastCLI)
├── hermes_state.py       # SQLite session store
├── agent/                # Prompt builder, context compression, memory, model routing, credential pooling, skill dispatch
├── hermes_cli/           # CLI subcommands, config, setup, commands
│   ├── commands.py       # Slash command registry (CommandDef)
│   ├── config.py         # DEFAULT_CONFIG, env var definitions
│   └── main.py           # CLI entry point and argparse
├── tools/                # One file per tool
│   └── registry.py       # Central tool registry
├── gateway/              # Messaging gateway
│   └── platforms/        # Platform adapters (telegram, discord, etc.)
├── cron/                 # Job scheduler
├── tests/                # ~3000 pytest tests
└── website/              # Docusaurus docs site
```

Config: `~/.superforecasting-agent/config.yaml` (settings), `~/.superforecasting-agent/.env` (API keys).

### Adding a Tool (3 files)

**1. Create `tools/your_tool.py`:**
```python
import json, os
from tools.registry import registry

def check_requirements() -> bool:
    return bool(os.getenv("EXAMPLE_API_KEY"))

def example_tool(param: str, task_id: str = None) -> str:
    return json.dumps({"success": True, "data": "..."})

registry.register(
    name="example_tool",
    toolset="example",
    schema={"name": "example_tool", "description": "...", "parameters": {...}},
    handler=lambda args, **kw: example_tool(
        param=args.get("param", ""), task_id=kw.get("task_id")),
    check_fn=check_requirements,
    requires_env=["EXAMPLE_API_KEY"],
)
```

**2. Add to `toolsets.py`** → `_HERMES_CORE_TOOLS` list.

Auto-discovery: any `tools/*.py` file with a top-level `registry.register()` call is imported automatically — no manual list needed.

All handlers must return JSON strings. Use `get_hermes_home()` for paths, never hardcode `~/.superforecasting-agent`.

### Adding a Slash Command

1. Add `CommandDef` to `COMMAND_REGISTRY` in `hermes_cli/commands.py`
2. Add handler in `cli.py` → `process_command()`
3. (Optional) Add gateway handler in `gateway/run.py`

All consumers (help text, autocomplete, Telegram menu, Slack mapping) derive from the central registry automatically.

### Agent Loop (High Level)

```
run_conversation():
  1. Build system prompt
  2. Loop while iterations < max:
     a. Call LLM (OpenAI-format messages + tool schemas)
     b. If tool_calls → dispatch each via handle_function_call() → append results → continue
     c. If text response → return
  3. Context compression triggers automatically near token limit
```

### Testing

```bash
python -m pytest tests/ -o 'addopts=' -q   # Full suite
python -m pytest tests/tools/ -q            # Specific area
```

- Tests auto-redirect `HERMES_HOME` to temp dirs — never touch real `~/.superforecasting-agent/`
- Run full suite before pushing any change
- Use `-o 'addopts='` to clear any baked-in pytest flags

**Windows contributors:** `scripts/run_tests.sh` currently looks for POSIX venvs (`.venv/bin/activate` / `venv/bin/activate`) and will error out on Windows where the layout is `venv/Scripts/activate` + `python.exe`. The Superforecasting Agent-installed venv at `venv/Scripts/` also has no `pip` or `pytest` — it's stripped for end-user install size. Workaround: install pytest + pytest-xdist + pyyaml into a system Python 3.11 user site (`/c/Program Files/Python311/python -m pip install --user pytest pytest-xdist pyyaml`), then run tests directly:

```bash
export PYTHONPATH="$(pwd)"
"/c/Program Files/Python311/python" -m pytest tests/tools/test_foo.py -v --tb=short -n 0
```

Use `-n 0` (not `-n 4`) because `pyproject.toml`'s default `addopts` already includes `-n`, and the wrapper's CI-parity story doesn't apply off-POSIX.

**Cross-platform test guards:** tests that use POSIX-only syscalls need a skip marker. Common ones already in the codebase:
- Symlink creation → `@pytest.mark.skipif(sys.platform == "win32", reason="Symlinks require elevated privileges on Windows")` (see `tests/cron/test_cron_script.py`)
- POSIX file modes (0o600, etc.) → `@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX mode bits not enforced on Windows")` (see `tests/hermes_cli/test_auth_toctou_file_modes.py`)
- `signal.SIGALRM` → Unix-only (see `tests/conftest.py::_enforce_test_timeout`)
- Live Winsock / Windows-specific regression tests → `@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific regression")`

**Monkeypatching `sys.platform` is not enough** when the code under test also calls `platform.system()` / `platform.release()` / `platform.mac_ver()`. Those functions re-read the real OS independently, so a test that sets `sys.platform = "linux"` on a Windows runner will still see `platform.system() == "Windows"` and route through the Windows branch. Patch all three together:

```python
monkeypatch.setattr(sys, "platform", "linux")
monkeypatch.setattr(platform, "system", lambda: "Linux")
monkeypatch.setattr(platform, "release", lambda: "6.8.0-generic")
```

See `tests/agent/test_prompt_builder.py::TestEnvironmentHints` for a worked example.

### Extending the system prompt's execution-environment block

Factual guidance about the host OS, user home, cwd, terminal backend, and shell (bash vs. PowerShell on Windows) is emitted from `agent/prompt_builder.py::build_environment_hints()`. This is also where the WSL hint and per-backend probe logic live. The convention:

- **Local terminal backend** → emit host info (OS, `$HOME`, cwd) + Windows-specific notes (hostname ≠ username, `terminal` uses bash not PowerShell).
- **Remote terminal backend** (anything in `_REMOTE_TERMINAL_BACKENDS`: `docker, singularity, modal, daytona, ssh, vercel_sandbox, managed_modal`) → **suppress** host info entirely and describe only the backend. A live `uname`/`whoami`/`pwd` probe runs inside the backend via `tools.environments.get_environment(...).execute(...)`, cached per process in `_BACKEND_PROBE_CACHE`, with a static fallback if the probe times out.
- **Key fact for prompt authoring:** when `TERMINAL_ENV != "local"`, *every* file tool (`read_file`, `write_file`, `patch`, `search_files`) runs inside the backend container, not on the host. The system prompt must never describe the host in that case — the agent can't touch it.

Full design notes, the exact emitted strings, and testing pitfalls:
`references/prompt-builder-environment-hints.md`.

**Refactor-safety pattern (POSIX-equivalence guard):** when you extract inline logic into a helper that adds Windows/platform-specific behavior, keep a `_legacy_<name>` oracle function in the test file that's a verbatim copy of the old code, then parametrize-diff against it. Example: `tests/tools/test_code_execution_windows_env.py::TestPosixEquivalence`. This locks in the invariant that POSIX behavior is bit-for-bit identical and makes any future drift fail loudly with a clear diff.

### Commit Conventions

```
type: concise subject line

Optional body.
```

Types: `fix:`, `feat:`, `refactor:`, `docs:`, `chore:`

### Key Rules

- **Never break prompt caching** — don't change context, tools, or system prompt mid-conversation
- **Message role alternation** — never two assistant or two user messages in a row
- Use `get_hermes_home()` from `hermes_constants` for all paths (profile-safe)
- Config values go in `config.yaml`, secrets go in `.env`
- New tools need a `check_fn` so they only appear when requirements are met
