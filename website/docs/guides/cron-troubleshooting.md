---
sidebar_position: 12
title: "Cron Troubleshooting"
description: "Diagnose scheduled forecast reviews, alert delivery, script jobs, and cron runtime issues."
---

# Cron Troubleshooting

When a scheduled job is not behaving as expected, work through these checks in order. Most issues fall into timing, gateway state, delivery, script permissions, or skill loading.

---

## Jobs Not Firing

### Check 1: Verify the job exists and is active

```bash
superforecasting-agent cron list
```

Look for the job and confirm its state is `[active]`, not `[paused]` or `[completed]`. If it shows `[completed]`, the repeat count may be exhausted; edit the job to reset it.

For ledger-native reviews, also inspect:

```bash
forecast schedule list
forecast review
```

### Check 2: Confirm the schedule is correct

A misformatted schedule may be rejected or treated as a one-shot. Test the expression:

| Your expression | Should evaluate to |
|----------------|-------------------|
| `0 9 * * *` | 9:00 AM every day |
| `0 9 * * 1` | 9:00 AM every Monday |
| `every 2h` | Every 2 hours from now |
| `30m` | 30 minutes from now |
| `2026-06-01T09:00:00` | June 1, 2026 at 9:00 AM UTC |

If the job fires once and disappears from the list, it was a one-shot schedule.

### Check 3: Is the gateway running?

General cron jobs are fired by the gateway background ticker. A regular CLI forecast session does not automatically fire cron jobs.

```bash
superforecasting-agent gateway status
superforecasting-agent cron tick
```

If jobs should fire automatically, run the gateway in the foreground with `superforecasting-agent gateway` or start the installed service with `superforecasting-agent gateway start`. Use `superforecasting-agent cron tick` for one-off debugging.

### Check 4: Check the system clock and timezone

Jobs use the local timezone. Verify the clock and compare `next_run` values:

```bash
date
superforecasting-agent cron list
```

---

## Delivery Failures

### Check 1: Verify the delivery target

Delivery targets are case-sensitive and require the platform to be configured.

| Target | Requires |
|--------|----------|
| `telegram` | `TELEGRAM_BOT_TOKEN` in `~/.superforecasting-agent/.env` |
| `discord` | `DISCORD_BOT_TOKEN` in `~/.superforecasting-agent/.env` |
| `slack` | `SLACK_BOT_TOKEN` in `~/.superforecasting-agent/.env` |
| `whatsapp` | WhatsApp gateway configured |
| `signal` | Signal gateway configured |
| `matrix` | Matrix homeserver configured |
| `email` | SMTP configured in `config.yaml` |
| `sms` | SMS provider configured |
| `local` | Write access to `~/.superforecasting-agent/cron/output/` |
| `origin` | Delivers to the chat where the job was created |

Legacy `~/.hermes/.env`, `~/.hermes/config.yaml`, and `~/.hermes/cron/output/` are still accepted as compatibility paths during migration.

Other supported platforms include `mattermost`, `homeassistant`, `dingtalk`, `feishu`, `wecom`, `weixin`, `bluebubbles`, `qqbot`, and `webhook`. You can also target a specific chat with `platform:chat_id` syntax such as `telegram:-1001234567890`.

If delivery fails, the job may still run; check `superforecasting-agent cron list` for the latest error field.

### Check 2: Check `[SILENT]` and empty-output behavior

If a cron job produces no output or the agent responds with `[SILENT]`, delivery is suppressed. This is intentional for monitoring jobs and source checks, but a prompt like "respond with [SILENT] if nothing changed" can also hide output if your condition is wrong.

For script-only jobs, empty stdout means no delivery by design.

### Check 3: Platform token permissions

Each messaging platform bot needs permission to post in the target:

- Telegram: bot must be allowed to post in the target group or channel.
- Discord: bot must have permission to send in the target channel.
- Slack: bot must be added to the workspace/channel and have `chat:write` scope.

### Check 4: Response wrapping

Cron responses may be wrapped with a header and footer when `cron.wrap_response: true` in `config.yaml`. Disable wrapping if a platform or downstream parser does not handle it:

```yaml
cron:
  wrap_response: false
```

---

## Forecast Schedule Issues

### Check 1: Review the ledger schedule

```bash
forecast schedule list
forecast schedule run --dry-run
forecast review
```

Use the forecast scheduler for stale forecasts, watched evidence, auto-scoring, postmortem learning, and calibration refreshes. Use the general cron scheduler for raw script jobs or LLM prompts that are not ledger-owned.

### Check 2: Auto-learning flags

If a scheduled review should score resolved questions or write postmortems, confirm the schedule was created with the right flags:

```bash
forecast schedule list --json
forecast schedule add --domain macro --auto-score --auto-postmortem
```

Auto-score and auto-postmortem are opt-in so the ledger does not silently write learning artifacts without an explicit schedule policy.

### Check 3: Watched-source alerts

If watched sources do not create alerts:

```bash
forecast watch list
forecast schedule run
forecast alerts
```

Check that the watched source has a valid adapter, credentials if needed, and a previous snapshot to compare against.

---

## Skill Loading Failures

### Check 1: Verify skills are installed

```bash
superforecasting-agent skills list
```

Skills must be installed before they can be attached to cron jobs. If a skill is missing, install it with `superforecasting-agent skills install <skill-name>` or via `/skills` in the CLI.

### Check 2: Check skill names

Skill names are case-sensitive and must match the installed folder name. Confirm the exact name from:

```bash
superforecasting-agent skills list
```

### Check 3: Skills that require interactive tools

Cron jobs run headlessly with some interactive toolsets disabled. If a skill relies on interactive prompts, direct message sending, or recursive cron creation, it may not work in a cron context.

---

## Job Errors and Failures

### Check 1: Review recent job output

If a job ran and failed, inspect:

1. The chat or channel where the job delivers, if delivery succeeded.
2. `~/.superforecasting-agent/logs/agent.log` and `~/.superforecasting-agent/logs/errors.log`.
3. The job metadata from `superforecasting-agent cron list`.

Legacy `~/.hermes/logs/` remains a compatibility path for migrated profiles.

### Check 2: Common error patterns

**"No such file or directory" for scripts**

```bash
ls ~/.superforecasting-agent/scripts/your-script.py
superforecasting-agent cron edit <job_id> --script your-script.py
```

Scripts should live under the scheduler script directory. New setups should use `~/.superforecasting-agent/scripts/`; inherited `~/.hermes/scripts/` jobs still work during migration.

**"Skill not found" at job execution**

The skill must be installed on the machine running the scheduler. If you move between machines, reinstall it with `superforecasting-agent skills install <skill-name>`.

**Job runs but delivers nothing**

Usually this is a delivery target issue or intentionally suppressed output. Check the delivery target, `[SILENT]` conditions, and script stdout.

**Job hangs or times out**

The scheduler uses an inactivity-based timeout, configurable with `HERMES_CRON_TIMEOUT`. The env var name is inherited for compatibility. Long-running jobs should collect data in scripts and emit only the result the forecast desk needs.

### Check 3: Lock contention

The scheduler uses file-based locking to prevent overlapping ticks. If two gateway instances are running, jobs may be delayed or skipped.

```bash
ps aux | grep superforecasting-agent
ps aux | grep hermes   # legacy process name compatibility check
```

Keep one active gateway process.

### Check 4: Permissions on jobs.json

Jobs are stored in the cron state directory:

```bash
ls -la ~/.superforecasting-agent/cron/jobs.json
chmod 600 ~/.superforecasting-agent/cron/jobs.json
```

If you migrated from the inherited runtime, also check `~/.hermes/cron/jobs.json`.

---

## Performance Issues

### Slow job startup

Each LLM cron job creates a fresh agent session, which may involve provider authentication and model loading. For time-sensitive schedules, add buffer time or use script-only jobs for data collection.

### Too many overlapping jobs

The scheduler executes jobs sequentially within each tick. Stagger schedules such as `0 9 * * *` and `5 9 * * *` instead of running everything at the same minute.

### Large script output

Scripts that dump megabytes of output will slow down processing and may hit token limits if an LLM job consumes them. Filter at the script level and emit only the evidence, alert, or metric needed for review.

---

## Diagnostic Commands

```bash
superforecasting-agent cron list
superforecasting-agent cron run <job_id>
superforecasting-agent cron edit <job_id>
superforecasting-agent logs
superforecasting-agent skills list
forecast schedule list
forecast review
forecast alerts
```

---

## Getting More Help

If the issue persists:

1. Run the job with `superforecasting-agent cron run <job_id>` and watch for delivery errors.
2. Check `~/.superforecasting-agent/logs/agent.log` and `~/.superforecasting-agent/logs/errors.log`.
3. Capture the job ID, schedule, delivery target, expected behavior, actual behavior, and relevant log lines.

For the complete reference, see [Automate Forecast Reviews with Cron](/docs/guides/automate-with-cron) and [Scheduled Tasks (Cron)](/docs/user-guide/features/cron).
