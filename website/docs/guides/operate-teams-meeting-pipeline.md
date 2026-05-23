---
title: "Operate the Teams Meeting Forecast Pipeline"
description: "Runbook, go-live checklist, and operator worksheet for Microsoft Teams meeting evidence capture."
---

# Operate the Teams Meeting Forecast Pipeline

Use this guide after you have enabled the Teams Meetings integration from [Teams Meetings](/docs/user-guide/messaging/teams-meetings).

For the Superforecasting Agent fork, the Teams meeting pipeline is a secondary evidence-capture surface. Its job is to turn meeting transcripts, recordings, and follow-up artifacts into forecast review work:

- identify forecast questions discussed in a meeting
- capture factual claims and assumptions as evidence candidates
- flag decisions that change close dates, resolution criteria, or source reliability
- deliver review alerts to the forecast desk
- avoid silently changing probabilities from a meeting review note

This page covers operator CLI flows, subscription maintenance, failure triage, go-live checks, and rollout worksheets.

## Core Operator Commands

### Validate the config snapshot

```bash
superforecasting-agent teams-pipeline validate
```

Run this after any config, credential, webhook URL, or delivery-target change.

### Inspect token health

```bash
superforecasting-agent teams-pipeline token-health
superforecasting-agent teams-pipeline token-health --force-refresh
```

Use `--force-refresh` when you suspect stale Microsoft Graph auth state.

### Inspect subscriptions

```bash
superforecasting-agent teams-pipeline subscriptions
```

### Renew near-expiry subscriptions

```bash
superforecasting-agent teams-pipeline maintain-subscriptions
superforecasting-agent teams-pipeline maintain-subscriptions --dry-run
```

### Inspect recent jobs

```bash
superforecasting-agent teams-pipeline list
superforecasting-agent teams-pipeline list --status failed
superforecasting-agent teams-pipeline show <job-id>
```

### Replay a stored job

```bash
superforecasting-agent teams-pipeline run <job-id>
```

Use replays to reproduce extraction or delivery failures. Do not treat replayed summaries as new evidence unless the pipeline stores a distinct evidence record.

### Dry-run meeting artifact fetches

```bash
superforecasting-agent teams-pipeline fetch --meeting-id <meeting-id>
superforecasting-agent teams-pipeline fetch --join-web-url "<join-url>"
```

## Automating Subscription Renewal

Microsoft Graph subscriptions expire in at most 72 hours. If nothing renews them, meeting notifications silently stop after 3 days and the pipeline looks broken. This is the main operational failure mode for Graph-backed Teams integrations.

You must run `maintain-subscriptions` on a schedule in production.

### Option 1: Superforecasting Agent cron

Use this if the gateway and scheduler are already running. The `--no-agent` mode runs a deterministic script rather than a model call.

Create the script:

```bash
mkdir -p ~/.superforecasting-agent/scripts
cat > ~/.superforecasting-agent/scripts/maintain-teams-subscriptions.sh <<'EOF'
#!/usr/bin/env bash
exec superforecasting-agent teams-pipeline maintain-subscriptions
EOF
chmod +x ~/.superforecasting-agent/scripts/maintain-teams-subscriptions.sh
```

Register the job:

```bash
superforecasting-agent cron create "0 */12 * * *" \
  --name "teams-pipeline-maintain-subscriptions" \
  --no-agent \
  --script maintain-teams-subscriptions.sh \
  --deliver local
```

Verify:

```bash
superforecasting-agent cron list
superforecasting-agent cron status
```

### Option 2: systemd timer

Create `/etc/systemd/system/superforecasting-agent-teams-pipeline-maintain.service`:

```ini
[Unit]
Description=Superforecasting Agent Teams meeting evidence subscription maintenance
After=network-online.target

[Service]
Type=oneshot
User=superforecast
EnvironmentFile=/etc/superforecasting-agent/env
ExecStart=/usr/local/bin/superforecasting-agent teams-pipeline maintain-subscriptions
```

Create `/etc/systemd/system/superforecasting-agent-teams-pipeline-maintain.timer`:

```ini
[Unit]
Description=Run Teams meeting evidence subscription maintenance every 12 hours

[Timer]
OnBootSec=5min
OnUnitActiveSec=12h
Persistent=true

[Install]
WantedBy=timers.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now superforecasting-agent-teams-pipeline-maintain.timer
systemctl list-timers superforecasting-agent-teams-pipeline-maintain.timer
```

### Option 3: Plain crontab

```cron
0 */12 * * * /usr/local/bin/superforecasting-agent teams-pipeline maintain-subscriptions >> /var/log/superforecasting-agent/teams-pipeline-maintain.log 2>&1
```

Make sure the cron environment has the `MSGRAPH_*` credentials. The simplest pattern is to call a wrapper script that sources `~/.superforecasting-agent/.env` before running the command.

### Verify renewal

After the first scheduled run:

```bash
superforecasting-agent teams-pipeline subscriptions
superforecasting-agent teams-pipeline maintain-subscriptions --dry-run
```

Most dry runs should show no subscriptions expiring soon. If the webhook stops working after roughly 72 hours, check renewal first.

## Routine Runbook

### After first setup

Run these in order:

```bash
superforecasting-agent teams-pipeline validate
superforecasting-agent teams-pipeline token-health --force-refresh
superforecasting-agent teams-pipeline subscriptions
```

Trigger or wait for a real meeting event, then confirm the stored job:

```bash
superforecasting-agent teams-pipeline list
superforecasting-agent teams-pipeline show <job-id>
```

The first end-to-end event should prove:

- the transcript or recording was fetched
- the evidence review note was generated
- forecast-relevant claims were called out as evidence candidates
- the delivery target received the review note
- no probability update was written without an explicit `superforecasting-agent update`

### Daily or periodic checks

- Run `superforecasting-agent teams-pipeline maintain-subscriptions --dry-run`.
- Inspect `superforecasting-agent teams-pipeline list --status failed`.
- Verify the Teams delivery target is still the expected forecast-desk chat or channel.
- Check whether meeting summaries are producing evidence candidates rather than generic meeting notes.

### Before changing webhook URLs or delivery targets

- Update the public notification URL or Teams target config.
- Run `superforecasting-agent teams-pipeline validate`.
- Renew or recreate affected subscriptions.
- Confirm new events land in the expected sink.
- Run one end-to-end meeting test before relying on the new target.

## Forecast Evidence Handling

Meeting transcripts are useful but messy evidence. Operators should enforce these rules:

- A meeting review note can suggest evidence; it should not update probabilities by itself.
- Speaker statements are claims, not automatically facts.
- Meeting dates and transcript availability must be preserved.
- If a meeting changes a forecast assumption, add or update the assumption record.
- If a meeting contains resolution evidence, resolve and score through the forecast ledger.

Recommended follow-up commands:

```bash
superforecasting-agent research fq_123456789abc \
  "teams-meeting:<job-id>" \
  --claim "Engineering owner stated the release blocker is resolved." \
  --claim-type estimate \
  --source-name "Teams meeting transcript" \
  --source-type meeting_transcript \
  --reliability 0.6 \
  --relevance 0.8 \
  --stance increases

superforecasting-agent update fq_123456789abc \
  --probability 0.66 \
  --rationale "Updated after meeting evidence indicated the release blocker was resolved, with uncertainty because the claim is internal and not yet reflected in the public release source." \
  --evidence-ref ev_123456789abc \
  --use-active-lessons \
  --require-citations
```

## Failure Triage

### No jobs are being created

Check:

- `msgraph_webhook` is enabled.
- The public notification URL points to `/msgraph/webhook`.
- The client state in the subscription matches `MSGRAPH_WEBHOOK_CLIENT_STATE`.
- Subscriptions still exist remotely and are not expired.
- The subscription renewal job has run in the last 12 hours.

### Jobs stay in retry or fail before summarization

Check:

- transcript permissions and availability
- recording permissions and artifact availability
- `ffmpeg` availability if recording fallback is enabled
- Graph token health
- gateway logs with `superforecasting-agent logs gateway -f`

### Summaries are produced but not delivered to Teams

Check:

- `platforms.teams.enabled: true`
- `delivery_mode`
- `incoming_webhook_url` for webhook mode
- `chat_id` or `team_id` plus `channel_id` for Graph mode
- Teams auth config if Graph posting is used

### Meeting summaries are too generic

Tighten the prompt or pipeline config around forecast work:

- require affected forecast ids, domains, or topics
- require factual claims, estimates, rumors, and assumptions to be labeled
- require suggested `research`, `assumption`, `resolve`, or `update --preview` commands
- require `[SILENT]` when no active forecast is affected

### Duplicate or unexpected replays

Check:

- whether you manually replayed a job with `superforecasting-agent teams-pipeline run`
- whether the sink record already exists for that meeting
- whether a resend path is enabled in local config
- whether duplicate Graph deliveries were retried by Microsoft

## Go-Live Checklist

- [ ] Graph credentials are present and correct.
- [ ] `msgraph_webhook` is enabled and reachable from the public internet.
- [ ] `MSGRAPH_WEBHOOK_CLIENT_STATE` is set and matches subscriptions.
- [ ] Transcript subscription is created.
- [ ] Recording subscription is created if STT fallback is required.
- [ ] `ffmpeg` is installed if recording fallback is enabled.
- [ ] Teams outbound delivery target is configured and verified.
- [ ] Optional Notion, Linear, or file sinks are configured only if they support forecast review.
- [ ] `superforecasting-agent teams-pipeline validate` returns an OK snapshot.
- [ ] `superforecasting-agent teams-pipeline token-health --force-refresh` succeeds.
- [ ] `maintain-subscriptions` is scheduled. Without this, Graph subscriptions silently expire within 72 hours.
- [ ] A real end-to-end meeting event has produced a stored job.
- [ ] At least one evidence review note has reached the intended forecast-desk delivery sink.
- [ ] Operators know how to turn a meeting claim into forecast evidence without mutating probability silently.

## Delivery-Mode Decision Guide

| Mode | Use when | Tradeoff |
|------|----------|----------|
| `incoming_webhook` | you only need simple posting into Teams | simplest setup, less control |
| `graph` | you need channel or chat posting through Graph | more control, more auth and target config |

## Operator Worksheet

Fill this out before rollout:

| Item | Value |
|------|-------|
| Public notification URL | |
| Graph tenant ID | |
| Graph client ID | |
| Webhook client state | |
| Transcript resource subscription | |
| Recording resource subscription | |
| Teams delivery mode | |
| Teams chat ID or team/channel | |
| Forecast ledger profile | |
| Forecast domains or topics covered | |
| Store path override, if any | |
| Owner for daily checks | |

## Change Review Worksheet

Use this before changing the deployment:

| Question | Answer |
|----------|--------|
| Are we changing the public webhook URL? | |
| Are we rotating Graph credentials? | |
| Are we changing Teams delivery mode? | |
| Are we moving to a new Teams chat or channel? | |
| Do subscriptions need to be recreated or renewed? | |
| Do we need a fresh end-to-end verification run? | |
| Which active forecast domains or questions could be affected? | |

## Related Docs

- [Teams Meetings setup](/docs/user-guide/messaging/teams-meetings)
- [Microsoft Teams bot setup](/docs/user-guide/messaging/teams)
- [Forecast Automation Templates](/docs/guides/automation-templates)
- [Daily Forecast Brief](/docs/guides/daily-briefing-bot)
