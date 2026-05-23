---
sidebar_position: 4
title: "Tutorial: Team Telegram Forecast Desk"
description: "Set up a Telegram bot for shared forecast review, evidence alerts, and calibration learning."
---

# Set Up a Team Telegram Forecast Desk

This tutorial walks through setting up a Telegram bot for a team that uses Superforecasting Agent. The CLI remains the primary product surface. Telegram is a delivery and collaboration layer for forecast review, watched-source alerts, resolution checks, and calibration learning.

## What We're Building

A Telegram bot that:

- Lets authorized team members ask forecast-scoped questions from chat.
- Delivers scheduled review, watched-source, score, and postmortem alerts.
- Keeps each user in a separate session while sharing the same forecast ledger.
- Uses strict allowlists or pairing so only approved users can interact.
- Supports daily forecast briefs, domain review reminders, and benchmark summaries.

The bot should not become a broad do-anything team bot. Its job is to help the team maintain standing probabilistic beliefs and learn from resolved forecasts.

## Prerequisites

Before starting, make sure you have:

- **Superforecasting Agent installed** on a server or VPS that can stay online. Follow the [installation guide](/docs/getting-started/installation) if needed.
- **A Telegram account** for yourself as the bot owner.
- **An LLM provider configured**, with keys in `~/.superforecasting-agent/.env`.
- **A forecast ledger**, even if it starts empty. Run `superforecasting-agent status` to confirm the forecast desk can start.

:::tip Server size
A small VPS is usually enough for the gateway. The local process handles Telegram, scheduling, logs, and tool routing; model calls happen through your configured provider.
:::

## Step 1: Create a Telegram Bot

Every Telegram bot starts with **@BotFather**, Telegram's official bot-management account.

1. Open Telegram and search for `@BotFather`, or go to [t.me/BotFather](https://t.me/BotFather).
2. Send `/newbot`.
3. Choose a display name, for example `Team Forecast Desk`.
4. Choose a username ending in `bot`, for example `myteam_forecast_bot`.
5. Copy the bot token. You will paste it into the gateway setup.

Set a short description:

```text
Team forecast desk for review alerts, evidence updates, and calibration summaries.
```

Set a command menu:

```text
forecast - Run forecast desk commands
status - Show session and model status
cron - Manage scheduled forecast reviews
help - Show available commands
stop - Stop the current task
```

:::warning
Keep the bot token secret. Anyone with the token can control the bot. If it leaks, use `/revoke` in BotFather and update the gateway config.
:::

## Step 2: Configure The Gateway

You can configure Telegram interactively or by editing environment variables.

### Option A: Interactive Setup

```bash
superforecasting-agent gateway setup
```

Pick **Telegram**, paste the bot token, and enter your own numeric Telegram user ID when prompted.

### Option B: Manual Configuration

Add the token and owner allowlist to `~/.superforecasting-agent/.env`:

```bash
TELEGRAM_BOT_TOKEN=7123456789:AAH1bGciOiJSUzI1NiIsInR5cCI6Ikp...
TELEGRAM_ALLOWED_USERS=123456789
```

Your Telegram user ID is numeric and separate from your `@username`.

1. Message [@userinfobot](https://t.me/userinfobot).
2. Copy the numeric user ID it returns.
3. Put that number in `TELEGRAM_ALLOWED_USERS`.

Legacy installs may still read compatible `~/.hermes/.env` values during migration, but new forecast-desk setup should use `~/.superforecasting-agent`.

## Step 3: Start The Gateway

Run the gateway in the foreground first:

```bash
superforecasting-agent gateway
```

Open Telegram, message the bot, and ask for a forecast-scoped status check:

```text
/forecast status
```

If the bot responds, stop the foreground process with `Ctrl+C`.

### Install As A Service

For a deployment that survives logouts and reboots:

```bash
superforecasting-agent gateway install
superforecasting-agent gateway start
superforecasting-agent gateway status
```

On Linux servers where you want a boot-time system service:

```bash
sudo superforecasting-agent gateway install --system
sudo superforecasting-agent gateway start --system
sudo superforecasting-agent gateway status --system
```

On macOS:

```bash
superforecasting-agent gateway install
superforecasting-agent gateway start
tail -f ~/.superforecasting-agent/logs/gateway.log
```

:::tip Service names
The managed service may still use a compatibility unit name such as `hermes-gateway`. Prefer `superforecasting-agent gateway status`, `start`, `stop`, and `restart` so the CLI chooses the correct profile and service scope.
:::

## Step 4: Set Up Team Access

There are two good authorization models.

### Static Allowlist

Collect team members' numeric Telegram user IDs and add them to the allowlist:

```bash
TELEGRAM_ALLOWED_USERS=123456789,987654321,555555555
```

Restart the gateway:

```bash
superforecasting-agent gateway restart
```

### DM Pairing

DM pairing is better when team membership changes often.

1. A teammate DMs the bot.
2. The bot returns a one-time pairing code.
3. The teammate sends you that code out of band.
4. You approve it on the server:

```bash
superforecasting-agent pairing approve telegram XKGH5N7P
```

Manage paired users:

```bash
superforecasting-agent pairing list
superforecasting-agent pairing revoke telegram 987654321
superforecasting-agent pairing clear-pending
```

Security basics:

- Do not set `GATEWAY_ALLOW_ALL_USERS=true` on a bot with tool access.
- Pairing codes expire and are rate-limited.
- Pairing data is stored with restricted file permissions.
- Treat the Telegram bot as a shared operational surface, not a private scratchpad.

## Step 5: Configure The Team Forecast Desk

### Set A Home Channel

A home channel receives scheduled forecast reviews, alerts, score summaries, and backtest digests.

Use `/sethome` in a Telegram group where the bot is present, or set it manually:

```bash
TELEGRAM_HOME_CHANNEL=-1001234567890
TELEGRAM_HOME_CHANNEL_NAME="Forecast Desk"
```

To find a group chat ID, add [@userinfobot](https://t.me/userinfobot) to the group and copy the reported chat ID.

### Tune Tool Progress

For team chat, brief progress is usually enough. In `~/.superforecasting-agent/config.yaml`:

```yaml
display:
  tool_progress: new
```

| Mode | Telegram behavior |
|------|-------------------|
| `off` | Final responses only |
| `new` | Brief status for each new tool call |
| `all` | More detailed tool activity |
| `verbose` | Full tool output, useful for debugging |

### Keep Style Separate From Forecast State

`SOUL.md` can define communication style, but it should not store forecasts, priors, calibration lessons, or evidence. Those belong in the forecast ledger.

```markdown title="~/.superforecasting-agent/SOUL.md"
# Soul

Be concise, technical, and audit-focused.
For forecast updates, distinguish facts, assumptions, estimates, and rumors.
Never change a probability unless the update is recorded in the forecast ledger.
When evidence is stale, say so directly.
```

For a full style guide, see [Use SOUL.md](/docs/guides/use-soul-with-hermes).

### Add Team Context

Use context files for stable team conventions, not live forecast state.

```markdown title="~/.superforecasting-agent/AGENTS.md"
# Team Forecast Desk Context

- Primary domains: macro, policy, AI infrastructure, and company default risk.
- Use `superforecasting-agent review --stale` before daily standup.
- Probability updates must include evidence refs or source snapshots.
- Resolutions require a cited resolution source and a postmortem if scoreable.
- Do not treat Telegram chat history as forecast memory.
```

## Step 6: Add Forecast Workflows

### Daily Forecast Review

Create a recurring review delivered to the home channel:

```bash
superforecasting-agent cron create "0 8 * * 1-5" \
  "Run the daily team forecast review.

1. Run: superforecasting-agent review --stale --last 1d
2. Run: superforecasting-agent alerts
3. Run: superforecasting-agent lesson list --active
4. Summarize:
   - Forecasts that need research
   - Open watched-source alerts
   - Forecasts closing soon
   - Active calibration lessons to apply
5. Do not update probabilities from this briefing. If no action is needed, respond with [SILENT]." \
  --name "Daily team forecast review" \
  --deliver telegram
```

### Domain Learning Refresh

Use this for domains where resolved forecasts accumulate over time:

```bash
superforecasting-agent schedule add \
  --domain macro \
  --cadence "every 1d" \
  --next-run-at "2026-05-23T06:00:00Z" \
  --trigger-reason "team macro learning refresh" \
  --auto-score \
  --auto-postmortem

superforecasting-agent schedule install-cron \
  --schedule "every 1h" \
  --name "Forecast self-check" \
  --deliver telegram \
  --auto-score \
  --auto-postmortem
```

### Watched Evidence Source

Add watched sources for important questions or domains:

```bash
superforecasting-agent watch add "gdelt:central bank rate cut" \
  --domain macro \
  --topic rates \
  --source-type gdelt

superforecasting-agent watch add "fred:DFF" \
  --domain macro \
  --topic rates \
  --source-type fred
```

Check manually from Telegram:

```text
/forecast watch check --domain macro --topic rates
/forecast alerts
```

### Weekly Backtest Digest

Use this to keep the team honest about whether the forecast process is improving:

```bash
superforecasting-agent cron create "0 9 * * 1" \
  "Run the weekly team backtest and calibration digest.

1. Run: superforecasting-agent backtest --all-benchmarks --probability-source forecast-engine
2. Run: superforecasting-agent performance --last 10
3. Run: superforecasting-agent calibration --by-origin
4. Identify underperforming domains, horizons, or probability buckets.
5. Recommend one calibration lesson to review or promote.
6. Keep the report under 700 words." \
  --name "Weekly team backtest digest" \
  --deliver telegram
```

### Managing Scheduled Work

From the server:

```bash
superforecasting-agent cron list
superforecasting-agent cron status
superforecasting-agent schedule list
superforecasting-agent alerts
```

From Telegram:

```text
/cron list
/cron remove <job_id>
/forecast schedule list
/forecast alerts
```

Cron prompts run in fresh sessions. Include all required paths, domains, topics, and commands in the prompt.

## Production Safety

### Use A Containerized Terminal Backend

For shared bots, run terminal tools in a container:

```yaml title="~/.superforecasting-agent/config.yaml"
terminal:
  backend: docker
  container_cpu: 1
  container_memory: 5120
  container_persistent: true
```

This limits blast radius if a teammate asks the bot to run a risky command. It does not replace allowlists, approvals, or careful source handling.

### Monitor The Gateway

```bash
superforecasting-agent gateway status
superforecasting-agent logs gateway -f
```

On Linux, the service log may also be available through systemd:

```bash
journalctl --user -u hermes-gateway -f
```

That unit name is retained for compatibility. Use the CLI status command to find the profile-specific service if you run multiple installations.

### Update Safely

From the server:

```bash
superforecasting-agent update
superforecasting-agent gateway restart
```

From Telegram, `/update` may be available if your gateway command policy allows it. For production forecast desks, prefer updating from the server so you can inspect logs and restart status.

### Important Paths

| What | Location |
|------|----------|
| Gateway logs | `~/.superforecasting-agent/logs/gateway.log` |
| Cron job output | `~/.superforecasting-agent/cron/output/{job_id}/{timestamp}.md` |
| Cron job definitions | `~/.superforecasting-agent/cron/jobs.json` |
| Pairing data | `~/.superforecasting-agent/pairing/` |
| Session history | `~/.superforecasting-agent/sessions/` |
| Forecast ledger | `~/.superforecasting-agent/forecasting/` or profile-scoped ledger path |

Legacy `~/.hermes` paths may still exist after migration. New configuration should prefer `~/.superforecasting-agent`.

## Going Further

- [Messaging Gateway](/docs/user-guide/messaging) for platform architecture and session behavior.
- [Telegram Setup](/docs/user-guide/messaging/telegram) for Telegram-specific options.
- [Scheduled Tasks](/docs/user-guide/features/cron) for cron expressions and delivery options.
- [Forecast Automation Templates](/docs/guides/automation-templates) for review, source-watch, backtest, and postmortem recipes.
- [SOUL.md Style](/docs/guides/use-soul-with-hermes) for style customization without polluting forecast state.
- [Discord](/docs/user-guide/messaging/discord), [Slack](/docs/user-guide/messaging/slack), and [WhatsApp](/docs/user-guide/messaging/whatsapp) if your team wants more delivery channels.
