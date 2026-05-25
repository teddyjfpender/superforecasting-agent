---
sidebar_position: 6
title: "Event Hooks"
description: "Run custom forecast-desk code at lifecycle points."
---

# Event Hooks

Event hooks let you run custom code around the inherited runtime: gateway events, plugin lifecycle callbacks, and shell-script callbacks. In Superforecasting Agent, hooks are mainly for forecast-desk support work:

- Deliver stale-forecast, resolution, and self-check alerts.
- Record tool/runtime audit events.
- Block unsafe tool calls.
- Inject short-lived review context.
- Redact sensitive source output before the model sees it.
- Route approval prompts to a different notification system.

Hooks are not the forecast ledger. They should not silently overwrite probabilities or calibration state. If a hook creates durable forecast material, it should call explicit forecast workflows such as `forecast evidence add`, `forecast update`, `forecast score`, `forecast postmortem`, `forecast lessons`, or `forecast self-check`, and it should preserve provenance.

| System | Registered via | Runs in | Forecast-desk use |
|--------|----------------|---------|-------------------|
| **[Gateway hooks](#gateway-event-hooks)** | `HOOK.yaml` + `handler.py` in `~/.superforecasting-agent/hooks/` | Gateway only | Delivery alerts, webhook calls, startup checks |
| **[Plugin hooks](#plugin-hooks)** | `ctx.register_hook()` in a [plugin](/user-guide/features/plugins) | CLI + Gateway | Tool interception, metrics, guardrails, context injection |
| **[Shell hooks](#shell-hooks)** | `hooks:` in `~/.superforecasting-agent/config.yaml` | CLI + Gateway | Drop-in scripts for blocking, formatting, context, notifications |

Most hooks are best-effort observers: errors are caught and logged so the main runtime keeps going. A few hook return values intentionally affect behavior, such as blocking a tool call, injecting context, rewriting gateway messages, or transforming tool/model output.

Legacy homes such as `~/.hermes/` can still appear during migration. New fork-native setup should prefer `~/.superforecasting-agent/`.

## Ledger Boundary

The core safety rule is simple: hooks may create prompts, alerts, proposed updates, audit logs, and delivery messages, but durable forecast state changes should be explicit and append-only.

Allowed patterns:

- A hook notices `agent:end` and posts a review summary to Slack.
- A shell hook blocks `terminal` commands that would delete the local ledger.
- A `post_tool_call` plugin logs `web_extract` latency and source domains.
- A `pre_llm_call` plugin injects today's active calibration lessons as ephemeral context.
- A gateway startup hook runs `forecast self-check --auto-score --auto-postmortem` when the user configured that behavior.

Avoid:

- Silently changing a forecast probability from a hook.
- Writing evidence without source, timestamp, or question association.
- Letting a hook-owned memory system override ledger calibration lessons.
- Using `transform_llm_output` to make a response look like a scoreable forecast update when no ledger snapshot exists.

## Gateway Event Hooks

Gateway hooks fire automatically during gateway operation across Telegram, Discord, Slack, WhatsApp, Matrix, Teams, email, webhooks, and other messaging surfaces. They run outside the primary CLI forecast desk, so treat them as delivery and monitoring infrastructure.

### Creating a Hook

Each hook is a directory under `~/.superforecasting-agent/hooks/` containing two files:

```text
~/.superforecasting-agent/hooks/
└── stale-forecast-alert/
    ├── HOOK.yaml
    └── handler.py
```

#### HOOK.yaml

```yaml
name: stale-forecast-alert
description: Notify when forecast review work is active
events:
  - gateway:startup
  - command:forecast
  - agent:end
```

The `events` list determines which events trigger your handler. Wildcards such as `command:*` are supported.

#### handler.py

```python
import json
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = (
    Path.home()
    / ".superforecasting-agent"
    / "hooks"
    / "stale-forecast-alert"
    / "activity.log"
)

async def handle(event_type: str, context: dict):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        **context,
    }
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
```

Handler rules:

- The callable must be named `handle`.
- It receives `event_type` and `context`.
- It can be `async def` or regular `def`.
- Exceptions are logged and do not crash the gateway.

### Available Events

| Event | When it fires | Context keys |
|-------|---------------|--------------|
| `gateway:startup` | Gateway process starts | `platforms` |
| `session:start` | New messaging session created | `platform`, `user_id`, `session_id`, `session_key` |
| `session:end` | Session ended before reset | `platform`, `user_id`, `session_key` |
| `session:reset` | User ran `/new` or `/reset` | `platform`, `user_id`, `session_key` |
| `agent:start` | Agent begins processing a message | `platform`, `user_id`, `session_id`, `message` |
| `agent:step` | Each tool-loop iteration | `platform`, `user_id`, `session_id`, `iteration`, `tool_names` |
| `agent:end` | Agent finishes processing | `platform`, `user_id`, `session_id`, `message`, `response` |
| `command:*` | Any slash command executes | `platform`, `user_id`, `command`, `args` |

#### Wildcard Matching

Handlers registered for `command:*` fire for any `command:` event, including `command:forecast`, `command:alerts`, and compatibility slash commands.

### Examples

#### Telegram Alert on Long Forecast Review

Send a message when a gateway forecast-review turn takes many tool iterations:

```yaml
# ~/.superforecasting-agent/hooks/long-review-alert/HOOK.yaml
name: long-review-alert
description: Alert when forecast review work takes many steps
events:
  - agent:step
```

```python
# ~/.superforecasting-agent/hooks/long-review-alert/handler.py
import os
import httpx

THRESHOLD = 10
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_HOME_CHANNEL")

async def handle(event_type: str, context: dict):
    iteration = context.get("iteration", 0)
    if iteration != THRESHOLD or not BOT_TOKEN or not CHAT_ID:
        return
    tools = ", ".join(context.get("tool_names", []))
    text = f"Forecast review still running after {iteration} steps. Last tools: {tools}"
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text},
            timeout=10,
        )
```

#### Command Usage Logger

Track slash-command usage across gateway surfaces:

```yaml
# ~/.superforecasting-agent/hooks/command-logger/HOOK.yaml
name: command-logger
description: Log slash command usage
events:
  - command:*
```

```python
# ~/.superforecasting-agent/hooks/command-logger/handler.py
import json
from datetime import datetime, timezone
from pathlib import Path

LOG = Path.home() / ".superforecasting-agent" / "logs" / "command_usage.jsonl"

def handle(event_type: str, context: dict):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "command": context.get("command"),
        "args": context.get("args"),
        "platform": context.get("platform"),
        "user": context.get("user_id"),
    }
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
```

#### Session Start Webhook

POST to an external service when a new forecast-review session starts:

```yaml
# ~/.superforecasting-agent/hooks/session-webhook/HOOK.yaml
name: session-webhook
description: Notify external service on new sessions
events:
  - session:start
  - session:reset
```

```python
# ~/.superforecasting-agent/hooks/session-webhook/handler.py
import httpx

WEBHOOK_URL = "https://your-service.example.com/forecast-events"

async def handle(event_type: str, context: dict):
    async with httpx.AsyncClient() as client:
        await client.post(
            WEBHOOK_URL,
            json={"event": event_type, **context},
            timeout=5,
        )
```

### Tutorial: BOOT.md — Run a Startup Checklist on Every Gateway Boot

A useful gateway pattern is a local startup checklist. Put instructions in `~/.superforecasting-agent/BOOT.md`, then run them whenever the gateway starts.

For this fork, the most useful checklist is a lightweight forecast-desk self-check:

- Inspect scheduled jobs.
- Review stale active forecasts.
- Check unresolved alerts.
- Score newly resolved questions when configured.
- Draft postmortems and calibration lessons when configured.
- Deliver a summary to the home channel.

This is user-defined. Superforecasting Agent does not ship a hidden built-in BOOT hook.

#### What we're building

1. A file at `~/.superforecasting-agent/BOOT.md` with startup instructions.
2. A gateway hook that fires on `gateway:startup`.
3. A one-shot agent run that uses the gateway's resolved model and credentials.
4. A `[SILENT]` convention for cases where no message is needed.

#### Step 1: Write your checklist

Create `~/.superforecasting-agent/BOOT.md`:

```markdown
# Startup Forecast Desk Checklist

1. Run `forecast review --stale` and summarize urgent active forecasts.
2. Run `forecast alerts` and list unacknowledged alerts.
3. Run `forecast self-check --auto-score --auto-postmortem` if configured for this profile.
4. Run `superforecasting-agent cron list` and report failed scheduled jobs.
5. If there is forecast work, send a concise summary to the home channel.
6. If nothing needs attention, reply with only `[SILENT]`.
```

Scheduled jobs must not silently mutate probabilities. Use `--auto-score` and `--auto-postmortem` only when you intend those learning writes. Probability movement still requires an explicit `forecast update` snapshot.

#### Step 2: Create the hook

```text
~/.superforecasting-agent/hooks/boot-md/
├── HOOK.yaml
└── handler.py
```

**`~/.superforecasting-agent/hooks/boot-md/HOOK.yaml`**

```yaml
name: boot-md
description: Run BOOT.md on gateway startup
events:
  - gateway:startup
```

**`~/.superforecasting-agent/hooks/boot-md/handler.py`**

```python
import asyncio
from pathlib import Path

from run_agent import AIAgent

BOOT_FILE = Path.home() / ".superforecasting-agent" / "BOOT.md"

async def handle(event_type: str, context: dict):
    if event_type != "gateway:startup" or not BOOT_FILE.exists():
        return

    instructions = BOOT_FILE.read_text(encoding="utf-8").strip()
    if not instructions:
        return

    def run_once():
        agent = AIAgent(platform="gateway", enabled_toolsets=["forecast-desk"])
        return agent.chat(instructions)

    response = await asyncio.to_thread(run_once)
    if response and response.strip() != "[SILENT]":
        # Replace this with your platform-specific delivery path.
        print(response)
```

Use the gateway adapter or `send_message` tooling in your own handler when you want delivery to a specific platform.

#### Step 3: Test it

```bash
superforecasting-agent gateway restart
superforecasting-agent logs --follow --level INFO
```

You can also run the gateway hook manually by invoking the handler in a local test script with a synthetic `gateway:startup` event.

#### Extending the pattern

Common extensions:

- Keep separate `BOOT.md` files per profile.
- Run domain-scoped checks such as `forecast self-check --domain macro`.
- Send summaries only when `forecast alerts` returns open alerts.
- Use a locked-down profile with `forecast-desk` tools only.
- Save raw startup logs outside the ledger, then explicitly import durable evidence when needed.

#### Why this isn't a built-in

Startup automation can spend tokens, call tools, and write learning artifacts if configured. Keeping it as a documented pattern makes the behavior visible and opt-in.

### How It Works

1. On gateway startup, the hook registry scans `~/.superforecasting-agent/hooks/`.
2. Each hook directory with a valid `HOOK.yaml` and `handler.py` is loaded.
3. When an event fires, matching handlers run.
4. Handler exceptions are logged and skipped.
5. Gateway operation continues unless a documented return value intentionally changes control flow.

## Plugin Hooks

[Plugins](/user-guide/features/plugins) can register hooks that fire in both CLI and gateway sessions. They are registered with `ctx.register_hook()` inside a plugin's `register(ctx)` function.

```python
def register(ctx):
    ctx.register_hook("pre_tool_call", my_tool_guard)
    ctx.register_hook("post_tool_call", my_tool_metrics)
    ctx.register_hook("pre_llm_call", inject_review_context)
    ctx.register_hook("post_llm_call", log_turn_summary)
    ctx.register_hook("on_session_start", init_session)
    ctx.register_hook("on_session_end", cleanup_session)
```

General rules:

- Callbacks receive keyword arguments. Always accept `**kwargs` for forward compatibility.
- Callback crashes are logged and skipped.
- `pre_tool_call`, `pre_llm_call`, `pre_gateway_dispatch`, and transform hooks have behavior-changing return values.
- Other hooks are observer-only.
- Plugin hooks must keep durable forecast state explicit and auditable.

### Quick reference

| Hook | Fires when | Returns |
|------|------------|---------|
| [`pre_tool_call`](#pre_tool_call) | Before any tool executes | `{"action": "block", "message": str}` to veto |
| [`post_tool_call`](#post_tool_call) | After any tool returns | ignored |
| [`pre_llm_call`](#pre_llm_call) | Once per turn before tool loop | `{"context": str}` or string to inject context |
| [`post_llm_call`](#post_llm_call) | Once per turn after tool loop | ignored |
| [`on_session_start`](#on_session_start) | New session created | ignored |
| [`on_session_end`](#on_session_end) | Conversation turn/session ends | ignored |
| [`on_session_finalize`](#on_session_finalize) | Active session tears down | ignored |
| [`on_session_reset`](#on_session_reset) | Gateway rotates session key | ignored |
| [`subagent_stop`](#subagent_stop) | Delegated child exits | ignored |
| [`pre_gateway_dispatch`](#pre_gateway_dispatch) | Gateway receives inbound message | `skip`, `rewrite`, or `allow` |
| [`pre_approval_request`](#pre_approval_request) | Approval request is about to show | ignored |
| [`post_approval_response`](#post_approval_response) | Approval response recorded | ignored |
| [`transform_tool_result`](#transform_tool_result) | Tool result before model sees it | string replacement or `None` |
| [`transform_terminal_output`](#transform_terminal_output) | Terminal output before truncation/redaction | string replacement or `None` |
| [`transform_llm_output`](#transform_llm_output) | Final response before delivery | string replacement or `None` |

### `pre_tool_call`

Fires immediately before every tool execution, including built-in tools and plugin tools.

```python
def my_callback(tool_name: str, args: dict, task_id: str, **kwargs):
    ...
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `tool_name` | `str` | Tool about to execute, such as `terminal`, `web_search`, or `forecast_ledger`. |
| `args` | `dict` | Tool arguments. |
| `task_id` | `str` | Session or task identifier; empty when unset. |

Return a block directive to veto the call:

```python
return {"action": "block", "message": "Do not delete forecast ledger files"}
```

Example: block destructive terminal commands that target the local forecast store.

```python
LEDGER_PATHS = (".superforecasting-agent/forecasting", "forecasting/ledger")

def protect_ledger(tool_name, args, **kwargs):
    if tool_name != "terminal":
        return None
    command = str(args.get("command", ""))
    if "rm -rf" in command and any(path in command for path in LEDGER_PATHS):
        return {"action": "block", "message": "Blocked destructive ledger command"}
    return None

def register(ctx):
    ctx.register_hook("pre_tool_call", protect_ledger)
```

### `post_tool_call`

Fires immediately after every tool execution returns.

```python
def my_callback(tool_name: str, args: dict, result: str, task_id: str,
                duration_ms: int, **kwargs):
    ...
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `tool_name` | `str` | Tool that executed. |
| `args` | `dict` | Tool arguments. |
| `result` | `str` | Tool return value, normally a JSON string. |
| `task_id` | `str` | Session or task identifier. |
| `duration_ms` | `int` | Dispatch duration. |

Return value is ignored.

Example: collect source-tool latency and error metrics.

```python
from collections import Counter, defaultdict
import json

counts = Counter()
errors = Counter()
latency_ms = defaultdict(list)

def track_tool_metrics(tool_name, result, duration_ms=0, **kwargs):
    counts[tool_name] += 1
    latency_ms[tool_name].append(duration_ms)
    try:
        parsed = json.loads(result)
    except Exception:
        return
    if parsed.get("error"):
        errors[tool_name] += 1

def register(ctx):
    ctx.register_hook("post_tool_call", track_tool_metrics)
```

### `pre_llm_call`

Fires once per user turn before the tool-calling loop begins. It can inject ephemeral context into the current user message.

```python
def my_callback(session_id: str, user_message: str, conversation_history: list,
                is_first_turn: bool, model: str, platform: str, **kwargs):
    ...
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `str` | Current session ID. |
| `user_message` | `str` | Original message for this turn. |
| `conversation_history` | `list` | Copy of the OpenAI-format message list. |
| `is_first_turn` | `bool` | Whether this is a new session. |
| `model` | `str` | Model identifier. |
| `platform` | `str` | Runtime surface such as `cli`, `telegram`, or `discord`. |

Return `{"context": "..."}` or a non-empty string to append context to the user message. Return `None` for no injection.

Injected context is ephemeral. It does not mutate conversation history, session storage, or the forecast ledger.

Example: inject active calibration lessons for the current domain.

```python
def inject_macro_lessons(user_message, **kwargs):
    if "macro" not in user_message.lower():
        return None
    return {
        "context": (
            "Active calibration reminder for macro forecasts:\n"
            "- Check base rates before inside-view narratives.\n"
            "- Do not treat a single central-bank speech as decisive evidence."
        )
    }

def register(ctx):
    ctx.register_hook("pre_llm_call", inject_macro_lessons)
```

Where context is injected: always the user message, never the system prompt. This preserves prompt caching and keeps forecast protocol, tool rules, personality, and skills stable.

### `post_llm_call`

Fires once per successful turn after the tool loop completes and the final response exists.

```python
def my_callback(session_id: str, user_message: str, assistant_response: str,
                conversation_history: list, model: str, platform: str, **kwargs):
    ...
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `str` | Current session ID. |
| `user_message` | `str` | Original user message. |
| `assistant_response` | `str` | Final text response. |
| `conversation_history` | `list` | Message list after the turn. |
| `model` | `str` | Model identifier. |
| `platform` | `str` | Runtime surface. |

Return value is ignored.

Example: log short turn summaries for observability. Do not treat this as a forecast snapshot unless the ledger was explicitly updated.

```python
import logging

logger = logging.getLogger(__name__)

def log_turn(session_id, assistant_response, model, platform, **kwargs):
    logger.info(
        "turn_complete session=%s platform=%s model=%s chars=%d",
        session_id,
        platform,
        model,
        len(assistant_response or ""),
    )

def register(ctx):
    ctx.register_hook("post_llm_call", log_turn)
```

### `on_session_start`

Fires once when a new session is created.

```python
def my_callback(session_id: str, model: str, platform: str, **kwargs):
    ...
```

Use it to initialize session-scoped counters, telemetry buckets, or per-session caches.

```python
sessions = {}

def init_session(session_id, model, platform, **kwargs):
    sessions[session_id] = {"model": model, "platform": platform, "tool_calls": 0}

def register(ctx):
    ctx.register_hook("on_session_start", init_session)
```

### `on_session_end`

Fires at the end of every `run_conversation()` call and from the CLI exit handler if the agent was mid-turn when the user quit.

```python
def my_callback(session_id: str, completed: bool, interrupted: bool,
                model: str, platform: str, **kwargs):
    ...
```

Use it to flush buffers, close resources, or log completion status.

```python
def cleanup_session(session_id, completed, interrupted, **kwargs):
    status = "completed" if completed else ("interrupted" if interrupted else "failed")
    print(f"session={session_id} status={status}")

def register(ctx):
    ctx.register_hook("on_session_end", cleanup_session)
```

### `on_session_finalize`

Fires when the CLI or gateway tears down an active session, such as `/new`, idle gateway GC, or CLI exit with an active agent. This is the last chance to flush state tied to the outgoing session.

```python
def my_callback(session_id: str | None, platform: str, **kwargs):
    ...
```

Return value is ignored.

### `on_session_reset`

Fires when the gateway swaps in a new session key for an active chat, such as `/new`, `/reset`, `/clear`, or adapter idle-window rotation.

```python
def my_callback(session_id: str, platform: str, **kwargs):
    ...
```

Gateway order is `on_session_finalize(old_id)`, swap, `on_session_reset(new_id)`, then `on_session_start(new_id)` on the first inbound turn.

See the **[Build a Superforecasting Agent Plugin guide](/guides/build-a-superforecasting-agent-plugin)** for the inherited plugin-authoring walkthrough, including tool schemas, handlers, and additional hook patterns.

### `subagent_stop`

Fires once per delegated child after `delegate_task` finishes.

```python
def my_callback(parent_session_id: str, child_role: str | None,
                child_summary: str | None, child_status: str,
                duration_ms: int, **kwargs):
    ...
```

Use it to log orchestration activity or track duration. For forecast work, this is useful when child agents are assigned reference-class research, source extraction, model critique, or backtest analysis.

```python
import logging

logger = logging.getLogger(__name__)

def log_subagent(parent_session_id, child_role, child_status, duration_ms, **kwargs):
    logger.info(
        "subagent parent=%s role=%s status=%s duration_ms=%d",
        parent_session_id,
        child_role,
        child_status,
        duration_ms,
    )

def register(ctx):
    ctx.register_hook("subagent_stop", log_subagent)
```

### `pre_gateway_dispatch`

Fires once per incoming `MessageEvent` in the gateway, after the internal-event guard and before auth, pairing, and agent dispatch.

```python
def my_callback(event, gateway, session_store, **kwargs):
    ...
```

| Return | Effect |
|--------|--------|
| `{"action": "skip", "reason": "..."}` | Drop the message; plugin is assumed to have handled it. |
| `{"action": "rewrite", "text": "new text"}` | Replace `event.text`, then continue normal dispatch. |
| `{"action": "allow"}` or `None` | Continue normal dispatch. |

Use cases include listen-only group chats, human handoff, per-profile routing, or turning ambient source notes into a single forecast-review prompt.

```python
buffers = {}

def buffer_until_tagged(event, **kwargs):
    key = (event.source.platform, event.source.chat_id)
    text = event.text or ""
    if "@forecast" in text:
        prior = "\n".join(buffers.pop(key, []))
        return {"action": "rewrite", "text": prior + "\n" + text}
    buffers.setdefault(key, []).append(text)
    return {"action": "skip", "reason": "ambient-source-note"}

def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", buffer_until_tagged)
```

### `pre_approval_request`

Fires immediately before an approval request is shown to the user across CLI, TUI, gateway platforms, and ACP clients.

```python
def my_callback(
    command: str,
    description: str,
    pattern_key: str,
    pattern_keys: list[str],
    session_key: str,
    surface: str,
    **kwargs,
):
    ...
```

Return value is ignored. Use [`pre_tool_call`](#pre_tool_call) if you need to block before the approval system.

Example: send an approval notification to a separate channel.

```python
import logging

logger = logging.getLogger(__name__)

def log_approval(command, description, session_key, surface, **kwargs):
    logger.info(
        "approval_request surface=%s session=%s description=%s command=%s",
        surface,
        session_key,
        description,
        command[:120],
    )

def register(ctx):
    ctx.register_hook("pre_approval_request", log_approval)
```

### `post_approval_response`

Fires after the user responds to an approval prompt or the prompt times out.

```python
def my_callback(
    command: str,
    description: str,
    pattern_key: str,
    pattern_keys: list[str],
    session_key: str,
    surface: str,
    choice: str,
    **kwargs,
):
    ...
```

`choice` is one of `once`, `session`, `always`, `deny`, or `timeout`.

### `transform_tool_result`

Fires after a tool returns and before the result is appended to the conversation.

```python
def my_callback(
    tool_name: str,
    arguments: dict,
    result: str,
    task_id: str | None,
    **kwargs,
) -> str | None:
    ...
```

Return a string to replace the result, or `None` to leave it unchanged.

Use this for redaction, schema tagging, result summaries, or removing irrelevant tool noise before the model sees it. Do not use it to fabricate evidence; if you rewrite source output, preserve enough provenance for later audit.

```python
import re

SECRET = re.compile(r"sk-[A-Za-z0-9]{32,}")

def redact_secrets(tool_name, result, **kwargs):
    if SECRET.search(result):
        return SECRET.sub("[REDACTED]", result)
    return None

def register(ctx):
    ctx.register_hook("transform_tool_result", redact_secrets)
```

### `transform_terminal_output`

Fires inside the `terminal` tool before default truncation, ANSI stripping, and secret redaction.

```python
def my_callback(
    command: str,
    output: str,
    exit_code: int,
    cwd: str,
    task_id: str | None,
    **kwargs,
) -> str | None:
    ...
```

Return a string to replace raw output, or `None` to leave it unchanged.

Example: summarize huge file listings without hiding the command outcome.

```python
def summarize_find(command, output, **kwargs):
    if command.startswith("find ") and len(output) > 50_000:
        lines = output.count("\n")
        head = "\n".join(output.splitlines()[:40])
        return f"{head}\n\n[summary: {lines} paths total, showing first 40]"
    return None

def register(ctx):
    ctx.register_hook("transform_terminal_output", summarize_find)
```

### `transform_llm_output`

Fires once per turn after the tool loop completes and before the final response is delivered.

```python
def my_callback(
    response_text: str,
    session_id: str,
    model: str,
    platform: str,
    **kwargs,
) -> str | None:
    ...
```

Return a non-empty string to replace the response text. The first non-empty string wins when multiple plugins register.

Use this for redaction or house formatting. It is not a substitute for a ledger update. A transformed response is still just delivery text unless a forecast command or tool wrote the durable record.

## Shell Hooks

Shell hooks let you declare scripts in config instead of writing Python plugins. They run as subprocesses whenever the corresponding plugin-hook event fires.

Use shell hooks for simple, auditable tasks:

- Block dangerous terminal commands.
- Auto-format files after write operations.
- Inject small context snippets.
- Log subagent completion.
- Send lightweight forecast-alert notifications.

### Comparison at a glance

| Dimension | Shell hooks | Python plugin hooks | Gateway event hooks |
|-----------|-------------|---------------------|---------------------|
| Declared in | `hooks:` block in `~/.superforecasting-agent/config.yaml` | `register()` in a plugin | `HOOK.yaml` + `handler.py` |
| Lives under | `~/.superforecasting-agent/agent-hooks/` by convention | `~/.superforecasting-agent/plugins/<name>/` | `~/.superforecasting-agent/hooks/<name>/` |
| Runs in | CLI + gateway | CLI + gateway | Gateway only |
| Best for | One-file scripts | Rich runtime integrations | Platform delivery and gateway lifecycle |

### Configuration schema

```yaml
hooks:
  pre_tool_call:
    - command: "~/.superforecasting-agent/agent-hooks/block-ledger-delete.sh"
      timeout: 5
      matcher:
        tool_name: terminal
```

Supported keys:

- `command`: script or command to execute.
- `timeout`: seconds before the hook is killed.
- `matcher`: optional event-specific filters, such as `tool_name`.

### JSON wire protocol

Each time the event fires, the runtime spawns every matching hook, pipes a JSON payload to stdin, and reads stdout back as JSON.

Example `pre_tool_call` payload:

```json
{
  "event": "pre_tool_call",
  "tool_name": "terminal",
  "args": {"command": "forecast review --stale"},
  "task_id": "session-123"
}
```

Useful responses:

```json
{"action": "allow"}
{"action": "block", "message": "Forbidden command"}
{"context": "Ephemeral context to append to this turn"}
```

### Worked examples

#### 1. Auto-format Python files after every write

```yaml
# ~/.superforecasting-agent/config.yaml
hooks:
  post_tool_call:
    - command: "~/.superforecasting-agent/agent-hooks/auto-format.sh"
      timeout: 20
      matcher:
        tool_name: write_file
```

```bash
#!/usr/bin/env bash
# ~/.superforecasting-agent/agent-hooks/auto-format.sh
set -euo pipefail
payload="$(cat)"
python -m json.tool >/dev/null <<<"$payload"
echo '{"action":"allow"}'
```

#### 2. Block destructive `terminal` commands

```yaml
hooks:
  pre_tool_call:
    - command: "~/.superforecasting-agent/agent-hooks/block-rm-rf.sh"
      matcher:
        tool_name: terminal
```

```bash
#!/usr/bin/env bash
# ~/.superforecasting-agent/agent-hooks/block-rm-rf.sh
set -euo pipefail
payload="$(cat)"
if printf '%s' "$payload" | grep -q 'rm -rf.*\.superforecasting-agent'; then
  echo '{"action":"block","message":"Refusing to delete forecast-desk state"}'
else
  echo '{"action":"allow"}'
fi
```

#### 3. Inject `git status` into every turn (Claude-Code `UserPromptSubmit` equivalent)

```yaml
hooks:
  pre_llm_call:
    - command: "~/.superforecasting-agent/agent-hooks/inject-cwd-context.sh"
      timeout: 5
```

```bash
#!/usr/bin/env bash
# ~/.superforecasting-agent/agent-hooks/inject-cwd-context.sh
set -euo pipefail
status="$(git status --short 2>/dev/null | head -40 || true)"
python - <<'PY' "$status"
import json, sys
print(json.dumps({"context": "Workspace status:\n" + sys.argv[1]}))
PY
```

Claude Code's `UserPromptSubmit` event is intentionally not a separate event here. `pre_llm_call` fires at the same place and already supports context injection.

#### 4. Log every subagent completion

```yaml
hooks:
  subagent_stop:
    - command: "~/.superforecasting-agent/agent-hooks/log-orchestration.sh"
      timeout: 5
```

```bash
#!/usr/bin/env bash
# ~/.superforecasting-agent/agent-hooks/log-orchestration.sh
set -euo pipefail
log="$HOME/.superforecasting-agent/logs/orchestration.log"
mkdir -p "$(dirname "$log")"
cat >> "$log"
printf '\n' >> "$log"
echo '{"action":"allow"}'
```

### Consent model

Each unique `(event, command)` pair prompts for approval the first time the runtime sees it, then persists the decision to `~/.superforecasting-agent/shell-hooks-allowlist.json`. Subsequent CLI or gateway runs skip the prompt.

Ways to pre-approve in controlled environments:

1. `--accept-hooks` on the CLI, such as `superforecasting-agent --accept-hooks chat`.
2. `SUPERFORECASTING_AGENT_ACCEPT_HOOKS=1` or `FORECAST_ACCEPT_HOOKS=1`, with `HERMES_ACCEPT_HOOKS=1` retained as an inherited compatibility alias.

Script edits are trusted once the command is allowed. The allowlist keys on the command string, not the script hash. Use `superforecasting-agent hooks doctor` after editing or pulling shared hook configs.

### The `hermes hooks` CLI

The command namespace is still available as `hermes hooks` for compatibility, but new usage should prefer `superforecasting-agent hooks`.

| Command | Purpose |
|---------|---------|
| `superforecasting-agent hooks list` | Dump configured hooks with matcher, timeout, and consent status. |
| `superforecasting-agent hooks test <event> [--for-tool X] [--payload-file F]` | Fire matching hooks against a synthetic payload. |
| `superforecasting-agent hooks revoke <command>` | Remove allowlist entries matching the command. |
| `superforecasting-agent hooks doctor` | Check exec bit, allowlist status, mtime drift, JSON output validity, and rough execution time. |

### Security

- Keep scripts inside `~/.superforecasting-agent/agent-hooks/` so the path is easy to audit.
- Re-run `superforecasting-agent hooks doctor` after pulling shared config.
- Review any hook that can block, rewrite, inject context, or transform output.
- Treat shell hooks as executable code with the same care as plugins.
- Keep secrets in `.env` or the platform's secret store, not inside scripts.

### Ordering and precedence

Python plugin hooks run before shell hooks for the same event. For behavior-changing hooks, the first recognized directive wins. Observers continue to run unless the event dispatcher documents otherwise.
