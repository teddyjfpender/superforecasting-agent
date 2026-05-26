---
sidebar_position: 13
title: "Script-Only Scheduled Jobs"
description: "Run deterministic watchdog scripts on schedule and deliver non-empty output without calling a model."
---

# Script-Only Scheduled Jobs

Use script-only jobs when the check is deterministic and the script output already is the alert. This is useful for forecast-desk source monitors, data-pipeline heartbeats, local health checks, and other scheduled checks that should not spend model tokens.

Superforecasting Agent still uses the inherited cron scheduler for this mode, but the job skips the agent loop. The scheduler runs a Bash or Python script, delivers stdout when it is non-empty, and stays silent when there is nothing to report.

<!-- ascii-guard-ignore -->
```
   ┌──────────────────┐          ┌──────────────────┐
   │ scheduler tick   │  every   │ run script       │
   │ (every N minutes)│ ──────▶ │ (bash or python) │
   └──────────────────┘          └──────────────────┘
                                          │
                                          │ stdout
                                          ▼
                                 ┌──────────────────┐
                                 │ delivery router  │
                                 │ (alert target)   │
                                 └──────────────────┘
```
<!-- ascii-guard-ignore-end -->

- **No model call.** Zero tokens and no forecast-research loop.
- **Script is the job.** Emit output to alert; emit nothing for a silent tick.
- **Same scheduler.** Pausing, resuming, listing, manual runs, logs, and delivery targets work like other scheduled jobs.
- **Forecast-desk fit.** Use it for source-change monitors and pipeline checks that can later trigger review or evidence ingestion.

## When to Use It

Good script-only jobs include:

- Watch a source file, RSS feed, or API endpoint and alert only when its signature changes.
- Check whether a forecast data pipeline produced a fresh CSV, JSON, or model artifact.
- Ping when a scheduled backtest export, data snapshot, or resolver feed is missing.
- Report local disk, memory, GPU, or service-health failures.
- Send CI/CD output when a deployment or test run affects a forecast workflow.

Use an LLM-driven scheduled job when the system must decide what the evidence means, summarize a long source, choose which items matter, or draft a rationale. Use `forecast schedule` when the desired action is forecast lifecycle work such as reviewing stale questions, scoring resolved forecasts, or writing postmortems.

## Create One from Chat

You can ask the forecast desk to create a deterministic monitor. The agent writes the script, schedules it with `no_agent=true`, and records the cadence.

### Example transcript

> **You:** alert me on Telegram if the inflation data snapshot has not changed by 10am every weekday
>
> **Superforecasting Agent:** *(writes `~/.superforecasting-agent/scripts/inflation-snapshot-watchdog.sh`, then calls `cronjob(...)` with `no_agent=true`)*
>
> Set up. Runs every weekday at 10:00, alerts Telegram only when the snapshot is stale. Script: `inflation-snapshot-watchdog.sh`. Job ID: `abc123`.

Under the hood, the agent makes two tool calls:

```python
# 1. Write the check script
write_file(
    path="~/.superforecasting-agent/scripts/inflation-snapshot-watchdog.sh",
    content='''#!/usr/bin/env bash
snapshot="$HOME/.superforecasting-agent/data/inflation/latest.json"
if [ ! -s "$snapshot" ]; then
  echo "Inflation snapshot missing: $snapshot"
  exit 0
fi
age_hours=$(( ($(date +%s) - $(stat -c %Y "$snapshot")) / 3600 ))
if [ "$age_hours" -ge 24 ]; then
  echo "Inflation snapshot is ${age_hours}h old: $snapshot"
fi
# Empty stdout = silent tick; no message sent.
''',
)

# 2. Schedule it. no_agent=True skips the LLM on every tick.
cronjob(
    action="create",
    schedule="0 10 * * 1-5",
    script="inflation-snapshot-watchdog.sh",
    no_agent=True,
    deliver="telegram",
    name="inflation-snapshot-watchdog",
)
```

From that point on, the scheduler runs the script and pipes stdout to the delivery target if there is anything to say.

### What the agent should choose

For requests like "alert me when source X changes" or "every N minutes check Y and tell me if Z", the `cronjob` tool should choose `no_agent=True` when the script can fully determine the message. It should use the normal LLM-driven path when interpretation is needed.

### Managing watchdogs from forecast sessions

The agent can pause, resume, edit, and remove jobs the same way it creates them:

> **You:** stop the inflation snapshot watchdog for tonight
>
> **Superforecasting Agent:** *(calls `cronjob(action='pause', job_id='abc123')`)*
>
> Paused. Resume with "turn it back on" or via `superforecasting-agent cron resume abc123`.

> **You:** change it to every 30 minutes while the CPI release window is open
>
> **Superforecasting Agent:** *(calls `cronjob(action='update', job_id='abc123', schedule='every 30m')`)*

The full lifecycle is available to the agent without requiring you to learn the CLI flags.

## Create One from the CLI

The CLI path gives you the same result with three commands:

```bash
# 1. Write your script
cat > ~/.superforecasting-agent/scripts/inflation-snapshot-watchdog.sh <<'EOF'
#!/usr/bin/env bash
# Alert when a data snapshot is missing or stale. Silent otherwise.
SNAPSHOT="$HOME/.superforecasting-agent/data/inflation/latest.json"
if [ ! -s "$SNAPSHOT" ]; then
  echo "Inflation snapshot missing: $SNAPSHOT"
  exit 0
fi
AGE_HOURS=$(( ($(date +%s) - $(stat -c %Y "$SNAPSHOT")) / 3600 ))
if [ "$AGE_HOURS" -ge 24 ]; then
  echo "Inflation snapshot is ${AGE_HOURS}h old: $SNAPSHOT"
fi
EOF
chmod +x ~/.superforecasting-agent/scripts/inflation-snapshot-watchdog.sh

# 2. Schedule it
superforecasting-agent cron create "0 10 * * 1-5" \
  --no-agent \
  --script inflation-snapshot-watchdog.sh \
  --deliver telegram \
  --name "inflation-snapshot-watchdog"

# 3. Verify
superforecasting-agent cron list
superforecasting-agent cron run <job_id>
```

New setups should use `~/.superforecasting-agent/scripts/`. The inherited `~/.hermes/scripts/` path is still supported as a migration compatibility path.

## How Script Output Maps to Delivery

| Script behavior | Result |
|-----------------|--------|
| Exit 0, non-empty stdout | stdout is delivered verbatim |
| Exit 0, empty stdout | Silent tick; no delivery |
| Exit 0, stdout contains `{"wakeAgent": false}` on the last line | Silent tick |
| Non-zero exit code | Error alert is delivered |
| Script timeout | Error alert is delivered |

The "silent when empty" behavior is the key pattern: a source monitor can run every few minutes, while the forecast desk only sees a message when something changed or failed.

## Script Rules

Scripts must live under the scheduler script directory, normally `~/.superforecasting-agent/scripts/`. This is enforced at job-creation time and run time; absolute paths, `~/` expansion, and path traversal patterns are rejected.

Interpreter choice is by file extension:

| Extension | Interpreter |
|-----------|-------------|
| `.sh`, `.bash` | `/bin/bash` |
| anything else | `sys.executable` |

Shebangs are ignored. Keeping interpreter selection explicit reduces the surface the scheduler trusts.

## Schedule Syntax

Same as other scheduled jobs:

```bash
superforecasting-agent cron create "every 5m"        # interval
superforecasting-agent cron create "every 2h"
superforecasting-agent cron create "0 9 * * *"       # standard cron: 9am daily
superforecasting-agent cron create "30m"             # one-shot: run once in 30 minutes
```

See the [cron feature reference](/user-guide/features/cron) for the full syntax.

## Delivery Targets

`--deliver` accepts every configured gateway target. Common shapes:

```bash
--deliver telegram                       # platform home channel
--deliver telegram:-1001234567890        # specific chat
--deliver telegram:-1001234567890:17585  # specific Telegram forum topic
--deliver discord:#ops
--deliver slack:#forecast-desk
--deliver signal:+15551234567
--deliver local                          # save to ~/.superforecasting-agent/cron/output/
```

For bot-token platforms such as Telegram, Discord, Slack, Signal, SMS, and WhatsApp, no running gateway is required at script-run time. The scheduler calls the platform endpoint directly using credentials in the fork-native home. Legacy `~/.hermes/.env` and `~/.hermes/config.yaml` are still read during migration.

## Editing and Lifecycle

```bash
superforecasting-agent cron list
superforecasting-agent cron pause <job_id>
superforecasting-agent cron resume <job_id>
superforecasting-agent cron edit <job_id> --schedule "every 10m"
superforecasting-agent cron edit <job_id> --agent
superforecasting-agent cron edit <job_id> --no-agent --script inflation-snapshot-watchdog.sh
superforecasting-agent cron remove <job_id>
```

Everything that works on LLM jobs also works on script-only jobs.

## Worked Example: Disk Space Alert

```bash
cat > ~/.superforecasting-agent/scripts/disk-alert.sh <<'EOF'
#!/usr/bin/env bash
# Alert when / or /home is over 90% full.
THRESHOLD=90
df -h / /home 2>/dev/null | awk -v t="$THRESHOLD" '
  NR > 1 && $5+0 >= t {
    printf "Disk %s full on %s\n", $5, $6
  }
'
EOF
chmod +x ~/.superforecasting-agent/scripts/disk-alert.sh

superforecasting-agent cron create "*/15 * * * *" \
  --no-agent \
  --script disk-alert.sh \
  --deliver telegram \
  --name "disk-alert"
```

Silent when both filesystems are under 90%; fires exactly one line per over-threshold filesystem when one fills up.

## Comparison with Other Patterns

| Approach | What runs | When to use |
|----------|-----------|-------------|
| `cronjob --no-agent` | Your script on the inherited scheduler | Deterministic source monitors, watchdogs, alerts, and metrics |
| `forecast schedule` | Forecast lifecycle review | Stale forecasts, watched evidence, scoring, postmortems, and calibration refreshes |
| `cronjob` with an LLM prompt | Agent with optional pre-check script | Message content requires interpretation |
| OS cron plus `curl` to a [webhook subscription](/user-guide/messaging/webhooks) | Your script on the OS schedule | The scheduler or gateway itself might be unhealthy |

For critical system-health watchdogs that must fire even when the gateway is down, use OS-level cron with a plain `curl` to a webhook subscription or an external alerting endpoint. Use the in-gateway scheduler when the monitored thing is external and delivery should reuse the forecast desk's configured channels.

## Related

- [Automate Forecast Reviews with Cron](/guides/automate-with-cron) - LLM-driven and ledger-aware scheduled workflows.
- [Scheduled Tasks (Cron) reference](/user-guide/features/cron) - full schedule syntax, lifecycle, and delivery routing.
- [Webhook Subscriptions](/user-guide/messaging/webhooks) - HTTP entry points for external schedulers.
- [Gateway Internals](/developer-guide/gateway-internals) - delivery-router internals.
