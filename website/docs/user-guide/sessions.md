---
sidebar_position: 7
title: "Forecast Sessions"
description: "Forecast transcripts, resume, search, and the boundary with the forecast ledger"
---

# Forecast Sessions

Superforecasting Agent automatically saves interactive work as forecast sessions. Sessions are for continuity around forecast work: resume, handoff, search, and transcript management.

Forecasts themselves live in the forecast ledger, not ordinary session memory. The ledger is the scoreable store for questions, evidence, forecast snapshots, assumptions, model runs, resolutions, scores, postmortems, and calibration lessons. A session can discuss a forecast, but a forecast only becomes durable and learnable when the agent writes to the ledger.

## How Forecast Sessions Work

Every forecast thread — whether from the CLI, TUI, Telegram, Discord, Slack, WhatsApp, Signal, Matrix, Teams, or another messaging platform — is stored as a session with full message history. Sessions are tracked in two complementary systems:

1. **SQLite database** (`~/.superforecasting-agent/state.db`) — structured session metadata with FTS5 full-text search
2. **JSONL transcripts** (`~/.superforecasting-agent/sessions/`) — raw forecast transcripts including tool calls for gateway sessions

Existing Hermes-compatible installs may still use `~/.hermes/`; new installs default to `~/.superforecasting-agent/`.

The SQLite database stores:
- Session ID, source platform, user ID
- **Session title** (unique, human-readable name)
- Model name and configuration
- System prompt snapshot
- Full message history (role, content, tool calls, tool results)
- Token counts (input/output)
- Timestamps (started_at, ended_at)
- Parent session ID (for compression-triggered session splitting)

### Forecast Sessions vs Ledger

Forecast sessions are useful for remembering how a forecast discussion unfolded. They are not the product's learning loop.

Use the forecast ledger when the work should be auditable or scored:

- Creating a question with resolution criteria and an outcome space
- Adding source-backed evidence with timestamps and reliability notes
- Appending a probability snapshot and rationale
- Capturing base rates, assumptions, model runs, and source snapshots
- Resolving a question, scoring it, writing a postmortem, and updating calibration lessons

Use sessions for ephemeral research context:

- Resuming the same work thread
- Searching an old research thread for context
- Handing a live discussion from CLI to a messaging platform
- Recovering commands, tool calls, and notes that were never promoted to the ledger

### What Counts Toward Context

Superforecasting Agent stores session history so it can resume research threads, but it does not keep re-sending every byte it has ever handled. On each turn, the model sees the selected system prompt, the current transcript window, relevant ledger context when explicitly fetched, and any content injected for that turn.

Media attachments are handled as turn-scoped inputs:

- Images may be attached natively to the next model call, or pre-analyzed into
  a text description when the active model does not support native vision.
- Audio is transcribed into text when speech-to-text is configured.
- Text documents can have their extracted text included; other document types
  are usually represented by a saved local path and a short note.
- Attachment paths and extracted/derived text can appear in the transcript, but
  the raw image, audio, or binary file bytes are not repeatedly copied into
  future prompts.

For example, if a user attaches a report and asks for a forecast update, the agent may inspect the report once, extract relevant evidence, and write selected claims to the ledger. Future turns do not automatically carry the original file bytes in context. They carry only whatever was written into the transcript, such as the user's request, a short document summary, a local cache path, or ledger evidence identifiers.

The most common cause of context growth is not the media file itself. It is
verbose text: pasted transcripts, full logs, large tool outputs, long diffs,
repeated status reports, and detailed proof dumps. Prefer summaries, file
paths, focused excerpts, and tool-backed lookups over copying large artifacts
into the transcript. For forecasting work, promote compact, source-backed claims into the ledger instead of relying on an ever-growing transcript.

:::tip
Use `/compress` when a session gets long, `/new` for a fresh thread, and
`superforecasting-agent sessions prune` only when you want to delete old ended sessions from
storage. Compression reduces the active context; it is not a privacy delete and does not replace forecast scoring or postmortem writes.
Pass a name to `/new` (e.g. `/new public-health-forecast-review`) to set the new session's
initial title up front — useful for finding it later with `/resume <name>` or
in the `/sessions` picker.
:::

### Session Sources

Each session is tagged with its source platform:

| Source | Description |
|--------|-------------|
| `cli` | Interactive CLI (`superforecasting-agent` or `superforecasting-agent desk`) |
| `telegram` | Telegram messenger |
| `discord` | Discord server/DM |
| `slack` | Slack workspace |
| `whatsapp` | WhatsApp messenger |
| `signal` | Signal messenger |
| `matrix` | Matrix rooms and DMs |
| `mattermost` | Mattermost channels |
| `email` | Email (IMAP/SMTP) |
| `sms` | SMS via Twilio |
| `dingtalk` | DingTalk messenger |
| `feishu` | Feishu/Lark messenger |
| `wecom` | WeCom (WeChat Work) |
| `weixin` | Weixin (personal WeChat) |
| `bluebubbles` | Apple iMessage via BlueBubbles macOS server |
| `qqbot` | QQ Bot (Tencent QQ) via Official API v2 |
| `homeassistant` | Home Assistant conversation |
| `webhook` | Incoming webhooks |
| `api-server` | API server requests |
| `acp` | ACP editor integration |
| `cron` | Scheduled cron jobs |
| `batch` | Batch processing runs |

## CLI Forecast Session Resume

Resume previous forecast threads from the CLI using `--continue` or `--resume`. Resume restores the transcript thread; use `forecast show`, `forecast review`, or `forecast status` to inspect durable ledger state.

### Continue Last Session

```bash
# Resume the most recent CLI session
superforecasting-agent --continue
superforecasting-agent -c

# Or with the explicit desk subcommand
superforecasting-agent desk --continue
superforecasting-agent desk -c
```

This looks up the most recent `cli` session from the SQLite database and loads its full transcript history.

### Resume by Name

If you've given a session a title (see [Forecast Session Naming](#forecast-session-naming) below), you can resume it by name:

```bash
# Resume a named session
superforecasting-agent -c "my project"

# If there are lineage variants (my project, my project #2, my project #3),
# this automatically resumes the most recent one
superforecasting-agent -c "my project"   # resumes "my project #3"
```

### Resume Specific Session

```bash
# Resume a specific session by ID
superforecasting-agent --resume 20250305_091523_a1b2c3d4
superforecasting-agent -r 20250305_091523_a1b2c3d4

# Resume by title
superforecasting-agent --resume "forecast-policy-bill"

# Or with the explicit desk subcommand
superforecasting-agent desk --resume 20250305_091523_a1b2c3d4
```

Session IDs are shown when you exit a CLI session, and can be found with `superforecasting-agent sessions list`.

### Research Recap on Resume

When you resume a session, Superforecasting Agent displays a compact recap of the previous research thread in a styled panel before the input prompt:

<img className="docs-terminal-figure" src="/img/docs/session-recap.svg" alt="Stylized preview of the previous research recap panel shown when resuming a Superforecasting Agent session." />
<p className="docs-figure-caption">Resume mode shows a compact recap panel with recent user and forecaster turns before returning you to the live prompt.</p>

The recap:
- Shows **user messages** (gold `●`) and **forecaster responses** (green `◆`)
- **Truncates** long messages (300 chars for user, 200 chars / 3 lines for forecaster)
- **Collapses tool calls** to a count with tool names (e.g., `[3 tool calls: terminal, web_search]`)
- **Hides** system messages, tool results, and internal reasoning
- **Caps** at the last 10 exchanges with a "... N earlier messages ..." indicator
- Uses **dim styling** to distinguish from the active prompt

To disable the recap and keep the minimal one-liner behavior, set in `~/.superforecasting-agent/config.yaml`:

```yaml
display:
  resume_display: minimal   # default: full
```

:::tip
Session IDs follow the format `YYYYMMDD_HHMMSS_<hex>` — CLI/TUI sessions use a 6-char hex suffix (e.g. `20250305_091523_a1b2c3`), gateway sessions use an 8-char suffix (e.g. `20250305_091523_a1b2c3d4`). You can resume by ID (full or unique prefix) or by title — both work with `-c` and `-r`.

The legacy `hermes` command remains a compatibility alias in forked installs where that entry point is still present.
:::

## Cross-Platform Handoff

Use `/handoff <platform>` from a CLI session to transfer the live research thread to a messaging platform's home channel. The agent picks up exactly where the CLI left off: same session id, full role-aware transcript, tool calls, and any forecast ledger references already mentioned in the thread.

```bash
# Inside a CLI session
/handoff telegram
```

What happens:

1. The CLI validates that `<platform>` is enabled and has a home channel set (run `/sethome` from the destination channel once to configure it).
2. The CLI marks the session pending and **block-polls the gateway**. It refuses if the agent is mid-turn — wait for the current response to finish first.
3. The gateway watcher claims the handoff and asks the destination adapter for a fresh thread:
   - **Telegram** — opens a new forum topic (DM topics if Bot API 9.4+ Topics mode is enabled in the chat, or a forum supergroup topic).
   - **Discord** — creates a 1440-min auto-archive thread under the home text channel.
   - **Slack** — posts a seed message and uses its `ts` as the thread anchor.
   - **WhatsApp / Signal / Matrix / SMS** — no native threads, falls back to the home channel directly.
4. The gateway re-binds the destination key to your existing CLI session id, then forges a synthetic user turn asking the agent to confirm and summarize the active work. The reply lands in the new thread.
5. When the gateway acknowledges success, the CLI prints a `/resume` hint and exits cleanly:

   ```
   ↻ Handoff complete. The session is now active on telegram.
     Resume it on this CLI later with: /resume my-session-title
   ```

6. From that point, the research thread lives on the platform. Reply in the new thread — anyone authorized in that channel shares the same session, and any later real user message in the thread joins seamlessly because thread sessions key without `user_id`.

**Resume back to CLI:** when you want to come back to a desktop, just run `/resume <title>` (or `superforecasting-agent -r "<title>"` from the shell) and pick up where the platform left off.

**Failure modes:**
- No home channel configured → CLI refuses with a `/sethome` hint.
- Platform not enabled / gateway not running → CLI times out at 60s with a clear message and your CLI session stays intact.
- Thread creation fails (permissions, topics-mode off) → falls back to the home channel directly and still completes; no thread isolation but the handoff itself works.
- `adapter.send` fails (rate limit, transient API error) → handoff marked failed with the reason; the row clears so you can retry.

**Limitation worth knowing:** for non-thread-capable platforms with multi-user group home channels, the synthetic turn keys as a DM-style session. This works for self-DM home channels (the typical setup) but isn't ideal for genuinely shared group chats. Threading covers Telegram / Discord / Slack — by far the common case — so most setups never hit this.

## Forecast Session Naming

Give sessions human-readable titles so you can find and resume them easily.

### Auto-Generated Titles

Superforecasting Agent automatically generates a short descriptive title (3–7 words) for each session after the first exchange. This runs in a background thread using a fast auxiliary model, so it adds no latency. You'll see auto-generated titles when browsing sessions with `superforecasting-agent sessions list` or `superforecasting-agent sessions browse`.

Auto-titling only fires once per session and is skipped if you've already set a title manually.

### Setting a Title Manually

Use the `/title` slash command inside any CLI, TUI, or gateway session:

```
/title my research project
```

The title is applied immediately. If the session hasn't been created in the database yet (e.g., you run `/title` before sending your first message), it's queued and applied once the session starts.

You can also rename existing sessions from the command line:

```bash
superforecasting-agent sessions rename 20250305_091523_a1b2c3d4 "forecast-policy-bill"
```

### Title Rules

- **Unique** — no two sessions can share the same title
- **Max 100 characters** — keeps listing output clean
- **Sanitized** — control characters, zero-width chars, and RTL overrides are stripped automatically
- **Normal Unicode is fine** — emoji, CJK, accented characters all work

### Auto-Lineage on Compression

When a session's context is compressed (manually via `/compress` or automatically), Superforecasting Agent creates a new continuation session. If the original had a title, the new session automatically gets a numbered title:

```
"my project" → "my project #2" → "my project #3"
```

When you resume by name (`superforecasting-agent -c "my project"`), it automatically picks the most recent session in the lineage.

### /title in Messaging Platforms

The `/title` command works in all gateway platforms (Telegram, Discord, Slack, WhatsApp):

- `/title My Research` — set the session title
- `/title` — show the current title

## Forecast Session Management Commands

Superforecasting Agent provides a full set of forecast-session management commands via `superforecasting-agent sessions`:

### List Forecast Sessions

```bash
# List recent forecast sessions (default: last 20)
superforecasting-agent sessions list

# Filter by platform
superforecasting-agent sessions list --source telegram

# Show more forecast sessions
superforecasting-agent sessions list --limit 50
```

When forecast sessions have titles, the output shows titles, previews, and relative timestamps:

```
Title                  Preview                                  Last Active   ID
────────────────────────────────────────────────────────────────────────────────────────────────
policy bill forecast   Update the committee-pass forecast        2h ago        20250305_091523_a
inflation path #3      Check the new CPI evidence                yesterday     20250304_143022_e
—                      Review my calibration misses              3d ago        20250303_101500_f
```

When no forecast sessions have titles, a simpler format is used:

```
Preview                                            Last Active   Src    ID
──────────────────────────────────────────────────────────────────────────────────────
Update the committee-pass forecast                  2h ago        cli    20250305_091523_a
Review my calibration misses                        3d ago        tele   20250303_101500_f
```

### Export Forecast Sessions

```bash
# Export all forecast sessions to a JSONL file
superforecasting-agent sessions export backup.jsonl

# Export forecast sessions from a specific platform
superforecasting-agent sessions export telegram-history.jsonl --source telegram

# Export a single session
superforecasting-agent sessions export session.jsonl --session-id 20250305_091523_a1b2c3d4
```

Exported files contain one JSON object per line with full session metadata and all messages.

### Delete a Session

```bash
# Delete a specific session (with confirmation)
superforecasting-agent sessions delete 20250305_091523_a1b2c3d4

# Delete without confirmation
superforecasting-agent sessions delete 20250305_091523_a1b2c3d4 --yes
```

### Rename a Session

```bash
# Set or change a session's title
superforecasting-agent sessions rename 20250305_091523_a1b2c3d4 "inflation update"

# Multi-word titles don't need quotes in the CLI
superforecasting-agent sessions rename 20250305_091523_a1b2c3d4 inflation update
```

If the title is already in use by another session, an error is shown.

### Prune Old Forecast Sessions

```bash
# Delete ended sessions older than 90 days (default)
superforecasting-agent sessions prune

# Custom age threshold
superforecasting-agent sessions prune --older-than 30

# Only prune sessions from a specific platform
superforecasting-agent sessions prune --source telegram --older-than 60

# Skip confirmation
superforecasting-agent sessions prune --older-than 30 --yes
```

:::info
Pruning only deletes **ended** sessions (sessions that have been explicitly ended or auto-reset). Active sessions are never pruned.
:::

### Forecast Session Statistics

```bash
superforecasting-agent sessions stats
```

Output:

```
Total sessions: 142
Total messages: 3847
  cli: 89 sessions
  telegram: 38 sessions
  discord: 15 sessions
Database size: 12.4 MB
```

For forecast performance analytics, use `superforecasting-agent forecast calibration`, `superforecasting-agent forecast performance`, and `superforecasting-agent forecast backtest`. For inherited runtime analytics such as token usage, cost estimates, tool breakdown, and activity patterns, use [`superforecasting-agent insights`](/reference/cli-commands#hermes-insights).

## Forecast Session Search Tool

The agent has a built-in `session_search` tool that performs full-text search across past forecast transcripts using SQLite's FTS5 engine and lets the agent scroll through any session it finds. No LLM calls, no summarization, no truncation. Every shape returns actual messages from the DB.

For forecast work, session search is a recovery aid. If prior evidence, probabilities, or lessons matter, the agent should migrate them into the forecast ledger rather than treating transcript recall as durable belief state.

### Three calling shapes

The tool infers what you want from which arguments you set. There's no `mode` parameter.

**1. Discovery — pass `query`:**

```python
session_search(query="inflation forecast CPI", limit=3)
```

Runs FTS5, dedupes hits by session lineage, returns the top N sessions. Each result carries:

- `session_id`, `title`, `when`, `source`
- `snippet` — FTS5-highlighted match excerpt
- `bookend_start` — first 3 user+forecaster messages of the session (the goal/kickoff)
- `messages` — ±5 messages around the FTS5 match, with the anchor message flagged (the hit in context)
- `bookend_end` — last 3 user+forecaster messages of the session (the resolution/decisions)
- `match_message_id`, `messages_before`, `messages_after`

Bookends plus the match window reconstruct kickoff, relevant context, and closing decisions without paying for the whole transcript. Typical wall time: 15-50ms on a real session DB.

**2. Scroll — pass `session_id` + `around_message_id`:**

```python
session_search(session_id="20260510_174648_805cc2", around_message_id=590803, window=10)
```

Returns a window of ±`window` messages centered on the anchor. No FTS5, no bookends — just the slice. Use after a discovery call when you need more context than the ±5 default window.

- To scroll **forward**: pass `messages[-1].id` back as `around_message_id`
- To scroll **backward**: pass `messages[0].id` back as `around_message_id`
- The boundary message appears in both windows as an orientation marker
- When `messages_before` or `messages_after` is less than `window`, you're at the start or end of the session

Typical wall time: 1–2ms per scroll call.

**3. Browse — no args:**

```python
session_search()
```

Returns recent forecast sessions chronologically (titles, previews, timestamps). Useful when the user asks "what was I working on" without naming a topic.

### FTS5 query syntax

The keyword mode supports standard FTS5 query syntax:

- Simple keywords: `docker deployment` (FTS5 defaults to AND)
- Phrases: `"exact phrase"`
- Boolean: `docker OR kubernetes`, `python NOT java`
- Prefix: `deploy*`

### Optional parameters

- `sort` — `newest` or `oldest`, on top of FTS5 ranking. Omit for relevance-only ordering (the default; suitable for exploratory recall). Use `newest` for "where did we leave X" questions, `oldest` for "how did X start" questions.
- `role_filter` — comma-separated roles to include. Discovery defaults to `user,assistant` (tool output is usually noise). Pass `user,assistant,tool` to include tool output (debugging tool behaviour) or `tool` to search tool output only.

### When It's Used

The agent is prompted to use session search automatically:

> *"When the user references something from a past forecast thread or you suspect relevant prior context exists, use session_search to recall it before asking them to repeat themselves. For forecast work, prefer ledger reads for scoreable beliefs and use session search to recover transcript context."*

Typical triggers: "we did this before", "remember when", "last time", "as I mentioned", "what probability did we discuss", or any reference to a project, domain, or question that is not in the current window.

## Per-Platform Session Tracking

### Messaging Platform Sessions

On messaging platforms, sessions are keyed by a deterministic session key built from the message source:

| Message Type | Default Key Format | Behavior |
|-----------|--------------------|----------|
| Telegram DM | `agent:main:telegram:dm:<chat_id>` | One session per DM chat |
| Discord DM | `agent:main:discord:dm:<chat_id>` | One session per DM chat |
| WhatsApp DM | `agent:main:whatsapp:dm:<canonical_identifier>` | One session per DM user (LID/phone aliases collapse to one identity when mapping exists) |
| Group channel | `agent:main:<platform>:group:<chat_id>:<user_id>` | Per-user inside the group when the platform exposes a user ID |
| Group thread/topic | `agent:main:<platform>:group:<chat_id>:<thread_id>` | Shared session for all thread participants (default). Per-user with `thread_sessions_per_user: true`. |
| Channel | `agent:main:<platform>:channel:<chat_id>:<user_id>` | Per-user inside the channel when the platform exposes a user ID |

When Superforecasting Agent cannot get a participant identifier for a shared chat, it falls back to one shared session for that room.

### Shared vs Isolated Group Sessions

By default, Superforecasting Agent uses `group_sessions_per_user: true` in `config.yaml`. That means:

- Alice and Bob can both talk to the agent in the same Discord channel without sharing transcript history
- one user's long tool-heavy task does not pollute another user's context window
- interrupt handling also stays per-user because the running-agent key matches the isolated session key

If you want one shared "room brain" instead, set:

```yaml
group_sessions_per_user: false
```

That reverts groups/channels to a single shared session per room, which preserves shared transcript context but also shares token costs, interrupt state, and context growth.

### Session Reset Policies

Gateway sessions are automatically reset based on configurable policies:

- **idle** — reset after N minutes of inactivity
- **daily** — reset at a specific hour each day
- **both** — reset on whichever comes first (idle or daily)
- **none** — never auto-reset

Before a session is auto-reset, the agent is given a turn to save important forecast artifacts to the ledger and any useful non-forecast context to memory or skills.

Sessions with **active background processes** are never auto-reset, regardless of policy.

## Storage Locations

| What | Path | Description |
|------|------|-------------|
| Session SQLite database | `~/.superforecasting-agent/state.db` | Session metadata and messages with FTS5 |
| Gateway transcripts | `~/.superforecasting-agent/sessions/` | JSONL transcripts per session plus `sessions.json` index |
| Gateway index | `~/.superforecasting-agent/sessions/sessions.json` | Maps session keys to active session IDs |
| Forecast ledger | `~/.superforecasting-agent/forecasting/forecasting.db` | Scoreable forecast questions, evidence, snapshots, scores, postmortems, alerts, schedules, and lessons |

The SQLite database uses WAL mode for concurrent readers and a single writer, which suits the gateway's multi-platform architecture well.

Legacy `~/.hermes/...` paths remain readable in compatibility mode.

### Database Schema

Key tables in `state.db`:

- **sessions** — session metadata (id, source, user_id, model, title, timestamps, token counts). Titles have a unique index (NULL titles allowed, only non-NULL must be unique).
- **messages** — full message history (role, content, tool_calls, tool_name, token_count)
- **messages_fts** — FTS5 virtual table for full-text search across message content

Forecast ledger tables are managed separately by the `forecasting` package. Session pruning should not be used as a substitute for forecast correction, resolution, or learning cleanup.

## Session Expiry and Cleanup

### Automatic Cleanup

- Gateway sessions auto-reset based on the configured reset policy
- Before reset, the agent saves relevant forecast artifacts to the ledger and saves non-forecast context only when useful
- Opt-in auto-pruning: when `sessions.auto_prune` is `true`, ended sessions older than `sessions.retention_days` (default 90) are pruned at CLI/gateway startup
- After a prune that actually removed rows, `state.db` is `VACUUM`ed to reclaim disk space (SQLite does not shrink the file on plain DELETE)
- Pruning runs at most once per `sessions.min_interval_hours` (default 24); the last-run timestamp is tracked inside `state.db` itself so it is shared across every agent process in the same home directory

Default is **off** — session history is valuable for `session_search` recall, and silently deleting it could surprise users. Enable in `~/.superforecasting-agent/config.yaml`:

```yaml
sessions:
  auto_prune: true          # opt in — default is false
  retention_days: 90        # keep ended sessions this many days
  vacuum_after_prune: true  # reclaim disk space after a pruning sweep
  min_interval_hours: 24    # don't re-run the sweep more often than this
```

Active sessions are never auto-pruned, regardless of age.

### Manual Cleanup

```bash
# Prune forecast sessions older than 90 days
superforecasting-agent sessions prune

# Delete a specific forecast session
superforecasting-agent sessions delete <session_id>

# Export before pruning (backup)
superforecasting-agent sessions export backup.jsonl
superforecasting-agent sessions prune --older-than 30 --yes
```

:::tip
The database grows slowly (typical: 10-15 MB for hundreds of sessions) and session history powers `session_search` recall across past forecast transcripts, so auto-prune ships disabled. Enable it if you're running a heavy gateway/cron workload where `state.db` is meaningfully affecting performance (observed failure mode: 384 MB state.db with about 1000 sessions slowing down FTS5 inserts and `/resume` listing). Use `superforecasting-agent sessions prune` for one-off cleanup without turning on the automatic sweep.
:::
