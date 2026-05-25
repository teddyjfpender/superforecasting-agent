---
sidebar_position: 10
title: "Tutorial: GitHub Repository Forecast Monitor"
description: "Monitor GitHub repositories as evidence sources for release, security, and execution-risk forecasts."
---

# Tutorial: GitHub Repository Forecast Monitor

GitHub activity can be a high-signal source for forecasts about software releases, company execution, open-source adoption, security exposure, and infrastructure risk. This guide shows how to monitor repositories on a schedule and turn repository changes into forecast evidence, alerts, and review work.

This is not a general automated code-review workflow. The goal is to support scoreable forecasts such as:

- Will project X ship version 2.0 before July 1?
- Will a critical vulnerability be patched before the disclosure deadline?
- Will a vendor deprecate an API this quarter?
- Will an open-source dependency add a required feature before our planning date?

## What You'll Build

```text
Cron schedule -> Superforecasting Agent -> GitHub CLI -> forecast evidence and alerts
```

The workflow polls repositories from a server or laptop. It works behind NAT and does not require a public endpoint. For real-time GitHub events, use [GitHub Webhook Forecast Evidence](./webhook-github-pr-review.md).

## Prerequisites

- **Superforecasting Agent installed**. See the [installation guide](/docs/getting-started/installation).
- **Gateway running** if you want scheduled delivery:

  ```bash
  superforecasting-agent gateway install
  superforecasting-agent gateway start
  ```

- **GitHub CLI (`gh`) installed and authenticated**:

  ```bash
  brew install gh
  gh auth login
  ```

- **At least one forecast question** that GitHub activity can inform.

If you do not want messaging yet, use `--deliver local` and inspect `~/.superforecasting-agent/cron/output/`.

## Step 1: Create A Forecast Question

Create a question with explicit resolution criteria before wiring automation around it:

```bash
superforecasting-agent new \
  "Will example-org/example-app publish v2.0.0 before 2026-08-01?" \
  --resolution-criteria "Resolved yes if a v2.0.0 GitHub release is published in example-org/example-app before 2026-08-01T00:00:00Z." \
  --resolution-source "https://github.com/example-org/example-app/releases" \
  --close-time "2026-07-31T23:59:59Z" \
  --resolution-time "2026-08-01T00:00:00Z" \
  --domain software \
  --topic release-risk \
  --tag github
```

The command prints a forecast id such as `fq_123456789abc`. Use that id in later commands.

## Step 2: Verify GitHub Access

From the server running the gateway:

```bash
gh release list --repo example-org/example-app --limit 5
gh pr list --repo example-org/example-app --state open --limit 5
gh issue list --repo example-org/example-app --state open --limit 5
```

If those commands work in your shell, scheduled jobs can use them too. If they fail, fix `gh auth login`, PATH, or repository permissions before involving the model.

## Step 3: Capture Manual Evidence

Before automating, capture one manually observed signal:

```bash
superforecasting-agent research fq_123456789abc \
  "https://github.com/example-org/example-app/pull/4242" \
  --claim "Release-blocking migration PR is open and marked ready for review." \
  --claim-type fact \
  --source-name "GitHub PR #4242" \
  --source-type github \
  --reliability 0.8 \
  --relevance 0.7 \
  --stance increases
```

Then update the forecast only if the signal changes your probability:

```bash
superforecasting-agent update fq_123456789abc \
  --probability 0.64 \
  --rationale "Release probability increased because the blocking migration PR is ready for review and the release branch is active." \
  --evidence-ref ev_123456789abc \
  --use-active-lessons \
  --require-citations
```

## Step 4: Add Watched Sources

Use watched sources for specific pages or feeds that should create alerts when they change.

```bash
superforecasting-agent watch add \
  "https://github.com/example-org/example-app/releases" \
  --question fq_123456789abc \
  --source-type url

superforecasting-agent watch add \
  "https://github.com/example-org/example-app/pulls?q=is%3Apr+is%3Aopen+label%3Arelease-blocker" \
  --question fq_123456789abc \
  --source-type url
```

Run a manual check:

```bash
superforecasting-agent watch check --question fq_123456789abc
superforecasting-agent alerts
```

## Step 5: Create A Scheduled Repository Scan

Use a cron job for a richer periodic summary. The job should recommend forecast work, not silently mutate probabilities.

```bash
superforecasting-agent cron create "0 */4 * * *" \
  "Scan GitHub repository signals for forecast question fq_123456789abc.

Repository:
- example-org/example-app

Resolution source:
- https://github.com/example-org/example-app/releases

Commands to run:
1. gh release list --repo example-org/example-app --limit 10
2. gh pr list --repo example-org/example-app --state open --json number,title,labels,updatedAt,url --limit 20
3. gh issue list --repo example-org/example-app --state open --json number,title,labels,updatedAt,url --limit 20

Look for:
- New releases, release candidates, or tag movement
- Release-blocker PRs or issues
- Maintainer comments suggesting schedule slip or acceleration
- Security advisories or dependency breaks

Output:
- One paragraph on whether the forecast needs review
- Evidence URLs worth ingesting
- Suggested next commands

Do not update the probability. If nothing material changed, respond with [SILENT]." \
  --name "github-release-risk-monitor" \
  --deliver telegram
```

Verify it is scheduled:

```bash
superforecasting-agent cron list
```

Run it on demand:

```bash
superforecasting-agent cron run github-release-risk-monitor
```

## Step 6: Schedule Domain Learning

For a portfolio of software release forecasts, add a domain review loop:

```bash
superforecasting-agent schedule add \
  --domain software \
  --topic release-risk \
  --cadence "every 1d" \
  --next-run-at "2026-05-23T08:00:00Z" \
  --trigger-reason "repository signal review" \
  --auto-score \
  --auto-postmortem
```

When forecasts resolve, score and postmortem them. This is how the desk learns whether GitHub signals were overweighted or missed.

```bash
superforecasting-agent calibration --domain software --by-origin
superforecasting-agent errors --domain software --topic release-risk
superforecasting-agent lesson list --scope-type domain --scope-ref software
```

## Useful Schedules

| Schedule | Use |
|----------|-----|
| `0 */4 * * *` | Poll active release-risk forecasts every four hours |
| `0 8 * * 1-5` | Weekday morning repository signal review |
| `0 9 * * 1` | Weekly portfolio review |
| `30m` | High-signal repository during a close-date window |

## Troubleshooting

### `gh: command not found`

The gateway may run with a minimal PATH. Install `gh` in a system-visible location, restart the gateway, and check:

```bash
superforecasting-agent gateway restart
superforecasting-agent logs gateway -f
```

### Scheduled output is too generic

Make the prompt more concrete:

- Add exact forecast ids.
- Include the resolution source.
- List the GitHub commands to run.
- Tell the job what should count as material evidence.
- Require evidence URLs and suggested next commands.

### Cron job doesn't run

```bash
superforecasting-agent gateway status
superforecasting-agent cron list
superforecasting-agent cron status
```

### GitHub rate limits

Authenticated GitHub API usage is usually enough for forecast monitoring. High-volume repositories should use lower polling frequency, narrower queries, or webhooks.

## What's Next?

- [GitHub Webhook Forecast Evidence](./webhook-github-pr-review.md) for real-time GitHub events.
- [Forecast Automation Templates](/docs/guides/automation-templates) for source watches, backtests, and postmortems.
- [Daily Forecast Brief](/docs/guides/daily-forecast-brief) for team-facing review digests.
- [Profiles](/docs/user-guide/profiles) for isolating a dedicated forecast-desk profile.
