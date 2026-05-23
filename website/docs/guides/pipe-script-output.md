---
sidebar_position: 12
title: "Pipe Script Output to Alert Channels"
description: "Send text from scripts, cron jobs, CI hooks, and monitors through the configured forecast-desk delivery router."
---

# Pipe Script Output to Alert Channels

`superforecasting-agent send` is a small scriptable CLI for pushing text to any configured delivery target. It is useful when a source monitor, data pipeline, CI job, or local watchdog needs to notify the forecast desk without starting a model call.

Use it for:

- Source-monitor alerts that should trigger forecast review.
- Data-pipeline completion or failure notifications.
- Backtest, calibration, and resolver-feed job summaries.
- System monitoring such as memory, disk, GPU temperature, and service health.
- Quick one-shot messages from a terminal.
- Piping any tool's output anywhere, such as `make test | superforecasting-agent send --to slack:#forecast-desk`.

The command reuses the same credentials and platform adapters that `superforecasting-agent gateway` uses, so there is no second notification configuration to maintain.

The legacy `hermes send` command remains available as a compatibility alias in inherited installs.

---

## Quick Start

```bash
# Plain text to the home channel for a platform
superforecasting-agent send --to telegram "data snapshot imported"

# Pipe in stdout from anything
echo "forecast data feed stale" | superforecasting-agent send --to telegram:-1001234567890

# Send a file
superforecasting-agent send --to discord:#ops --file /tmp/backtest-report.md

# Attach a subject/header line
superforecasting-agent send --to slack:#forecast-desk --subject "[Backtest]" --file build/backtest.log

# Thread target: Telegram topic or Discord thread
superforecasting-agent send --to telegram:-1001234567890:17585 "resolver feed changed"

# List every configured target
superforecasting-agent send --list

# Filter by platform
superforecasting-agent send --list telegram
```

---

## Argument Reference

| Flag | Description |
|------|-------------|
| `-t, --to TARGET` | Destination. See [target formats](#target-formats). |
| `message` | Message text. Omit to read from `--file` or stdin. |
| `-f, --file PATH` | Read the body from a file. `--file -` forces stdin. |
| `-s, --subject LINE` | Prepend a header/subject line before the body. |
| `-l, --list` | List available targets. Optional positional platform filter. |
| `-q, --quiet` | No stdout on success; useful in scripts. |
| `--json` | Emit the raw JSON result of the send. |
| `-h, --help` | Show the built-in help text. |

### Target Formats

| Format | Example | Meaning |
|--------|---------|---------|
| `platform` | `telegram` | Send to the platform's configured home channel |
| `platform:chat_id` | `telegram:-1001234567890` | Specific numeric chat, group, or user |
| `platform:chat_id:thread_id` | `telegram:-1001234567890:17585` | Specific thread or Telegram forum topic |
| `platform:#channel` | `discord:#ops` | Human-friendly channel name resolved against the channel directory |
| `platform:+E164` | `signal:+15551234567` | Phone-addressed platforms such as Signal, SMS, and WhatsApp |

Any configured messaging adapter can be a target: `telegram`, `discord`, `slack`, `signal`, `sms`, `whatsapp`, `matrix`, `mattermost`, `feishu`, `dingtalk`, `wecom`, `weixin`, `email`, and others.

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Send or list succeeded |
| `1` | Delivery failed at the platform level |
| `2` | Usage, argument, or config error |

Exit codes follow the standard Unix convention so scripts can branch on them.

---

## Message Body Resolution

`superforecasting-agent send` resolves the message body in this order:

1. Positional argument: `superforecasting-agent send --to telegram "hi"`
2. `--file PATH`: `superforecasting-agent send --to telegram --file msg.txt`
3. Piped stdin: `echo hi | superforecasting-agent send --to telegram`

When stdin is a TTY and no body was provided, the command does not wait for input; it returns a clear usage error so scripts do not hang.

---

## Real-World Examples

### Monitoring: Source Snapshot Stale

Replace ad-hoc platform API calls in forecast-source watchdogs with one portable line:

```bash
#!/usr/bin/env bash
snapshot="$HOME/.superforecasting-agent/data/rates/latest.json"
if [ ! -s "$snapshot" ]; then
  superforecasting-agent send --to telegram --subject "Forecast source stale" \
    "Rates snapshot missing: $snapshot"
fi
```

Because `superforecasting-agent send` reuses the forecast desk's config, the same script works on any host where the fork is installed.

:::tip Keep critical host alerts independent
For watchdogs that might fire when the Python runtime or gateway itself is unhealthy, keep a minimal external alert path such as `curl` to your monitoring provider. `superforecasting-agent send` is best for forecast-desk notifications where the local runtime is expected to be healthy.
:::

### CI/CD: Build and Test Results

```bash
if ./scripts/run_backtest.sh; then
  superforecasting-agent send --to slack:#forecast-desk "backtest finished"
else
  tail -n 100 backtest.log | superforecasting-agent send \
    --to slack:#forecast-desk --subject "backtest failed"
  exit 1
fi
```

### Cron: Daily Data Report

```bash
0 9 * * * /usr/local/bin/generate-forecast-metrics.sh \
  | /home/me/.superforecasting-agent/bin/superforecasting-agent send \
      --to telegram --subject "Forecast metrics $(date +%Y-%m-%d)"
```

### Long-Running Tasks: Ping When Done

```bash
./run_model_refresh.sh && \
  superforecasting-agent send --to telegram "model refresh done" || \
  superforecasting-agent send --to telegram "model refresh failed (exit $?)"
```

### Scripting with `--json` and `--quiet`

```bash
superforecasting-agent send --to telegram --quiet "keepalive" || {
  echo "Telegram delivery failed" >&2
  exit 1
}

msg_id=$(superforecasting-agent send --to discord:#ops --json "build started" \
  | jq -r .message_id)
```

---

## Does It Need the Gateway Running?

Usually no. For bot-token platforms such as Telegram, Discord, Slack, Signal, SMS, WhatsApp Cloud API, and most others, `superforecasting-agent send` calls the platform REST endpoint directly using credentials from `~/.superforecasting-agent/.env` and `~/.superforecasting-agent/config.yaml`. Legacy `~/.hermes/.env` and `~/.hermes/config.yaml` remain compatibility paths during migration.

A live gateway is only required for plugin platforms that depend on a persistent adapter connection. In that case the command returns a clear error; start it with `superforecasting-agent gateway start` and retry.

---

## Listing and Discovering Targets

```bash
superforecasting-agent send --list
superforecasting-agent send --list telegram
superforecasting-agent send --list --json
```

The listing is built from `~/.superforecasting-agent/channel_directory.json`, which the gateway refreshes while running. If you see "no channels discovered yet", start the gateway once with `superforecasting-agent gateway start` so it can populate the cache.

Human-friendly names such as `discord:#ops` and `slack:#forecast-desk` are resolved against this cache at send time, so you do not need to memorize numeric IDs.

---

## Comparison with Other Approaches

| Approach | Multi-platform | Reuses forecast-desk creds | Needs gateway | Best for |
|----------|----------------|----------------------------|---------------|----------|
| `superforecasting-agent send` | Yes | Yes | No for bot-token platforms | Raw script output and one-shot notifications |
| Raw `curl` to each platform | Each scripted separately | Manual | No | Critical watchdogs independent of this runtime |
| `cron` job with `--deliver` | Yes | Yes | No for bot-token platforms | Scheduled checks and agent jobs |
| `send_message` agent tool | Yes | Yes | No for bot-token platforms | Delivery from inside an agent loop |
| `forecast schedule` | Optional alert delivery | Yes | Scheduler-dependent | Forecast self-checks, scoring, postmortems, and calibration refreshes |

Use `superforecasting-agent send` when the message already exists. Use `cronjob(action='create', prompt=...)` when an agent needs to decide what to say. Use `forecast schedule` when the scheduled work should operate on the forecast ledger.

---

## Related

- [Automate Forecast Reviews with Cron](/docs/guides/automate-with-cron) - scheduled jobs whose output can deliver to any configured platform.
- [Gateway Internals](/docs/developer-guide/gateway-internals) - the delivery router shared with cron delivery.
- [Messaging Platform Setup](/docs/user-guide/messaging/) - one-time configuration for each platform.
