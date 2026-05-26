---
sidebar_position: 3
---

# Profile Distributions: Share a Forecast Desk

A **profile distribution** packages a forecast desk template as a git repository. It can include the desk's SOUL, configuration defaults, forecasting skills, source connectors, model runners, cron jobs, and MCP wiring.

It does **not** package the installer's forecast ledger. A distribution is for sharing how a desk should work; it is not for shipping another forecaster's questions, probabilities, evidence snapshots, calibration history, or resolved-score record.

If a [profile](./profiles.md) is a local forecasting workspace, a distribution is a versioned template for creating or updating that workspace.

## What Gets Shared

A typical forecast-desk distribution looks like this:

```text
macro-forecast-desk/
├── distribution.yaml
├── SOUL.md
├── config.yaml
├── mcp.json
├── skills/
│   ├── evidence-triage/SKILL.md
│   ├── base-rate-research/SKILL.md
│   └── forecast-postmortem/SKILL.md
├── cron/
│   ├── daily-staleness-check.json
│   └── weekly-calibration-review.json
└── README.md
```

The shared template can define:

- Forecasting protocol and desk identity in `SOUL.md`.
- Model/provider defaults in `config.yaml`.
- Evidence, market-data, research, and backtesting skills in `skills/`.
- Scheduled checks for stale questions, new evidence, and calibration review in `cron/`.
- MCP/source connections in `mcp.json`.
- Required environment variables in `distribution.yaml`.

The installer brings their own API keys, local data, ledger, and calibration record.

## What Never Gets Shared

These paths are user-owned and are never copied from a distribution or overwritten by an update:

```text
forecasting/
memories/
sessions/
logs/
plans/
workspace/
home/
local/
auth.json
.env
state.db*
hermes_state.db
response_store.db*
*_cache/
checkpoints/
sandboxes/
backups/
cache/
```

`forecasting/` is the critical one for this fork. It contains the ledger and related state: active questions, probability histories, evidence snapshots, resolutions, scores, calibration adjustments, domain lessons, and scheduled self-check state. Those records belong to the local desk because the agent can only learn honestly from its own forecast history.

To move a ledger intentionally, use the forecast export/import workflow or a profile backup workflow. Do not publish it as a profile distribution.

## When To Use One

Good fits:

- Share a **macro desk** with evidence feeds, base-rate skills, and daily stale-forecast checks.
- Share a **policy desk** that monitors legislation, agency actions, and resolution criteria.
- Share a **company-risk desk** with credit, product, hiring, or litigation research workflows.
- Share an **internal research desk** that standardizes source handling, model runners, and postmortems across a team.
- Publish a **starter desk** for a domain, where users should build their own ledger over time.

Not a fit:

- Backing up your own profile. Use [`superforecasting-agent profile export` / `import`](../reference/profile-commands.md#profile-export).
- Sharing API keys. `.env` and `auth.json` are intentionally excluded.
- Sharing resolved performance history. That is forecast ledger data, not distribution content.
- Shipping a Metaculus-only workflow as the core product. Metaculus extraction can be a useful source connector, but a desk distribution should work for any well-formed forecast question.

## Install

Install from a git URL or local directory:

```bash
superforecasting-agent profile install github.com/you/macro-forecast-desk --alias
superforecasting-agent profile install https://github.com/you/macro-forecast-desk.git
superforecasting-agent profile install git@github.com:your-org/internal-policy-desk.git
superforecasting-agent profile install ./local-profile-distribution/
```

What happens:

1. The repo is cloned into a temporary directory.
2. `distribution.yaml` is read and validated.
3. Required environment variables are checked against the shell and target profile.
4. Distribution-owned files are copied into `~/.superforecasting-agent/profiles/<name>/`.
5. `.env.EXAMPLE` is generated when required keys are declared.
6. With `--alias`, a wrapper is created so the desk can be launched by name.

The legacy `hermes` command may still work in compatibility installs, but new documentation and scripts should use `superforecasting-agent`.

## Authoring

Start from a working local profile:

```bash
superforecasting-agent profile create macro-forecast-desk
superforecasting-agent -p macro-forecast-desk setup
```

Then edit:

```text
~/.superforecasting-agent/profiles/macro-forecast-desk/SOUL.md
~/.superforecasting-agent/profiles/macro-forecast-desk/config.yaml
~/.superforecasting-agent/profiles/macro-forecast-desk/skills/
~/.superforecasting-agent/profiles/macro-forecast-desk/cron/
~/.superforecasting-agent/profiles/macro-forecast-desk/mcp.json
```

Create `distribution.yaml` at the profile root:

```yaml
name: macro-forecast-desk
version: 1.0.0
description: "Forecast desk for macro, rates, inflation, and policy questions"
hermes_requires: ">=0.12.0"
author: "Your Name"
license: "MIT"

env_requires:
  - name: OPENAI_API_KEY
    description: "Model access"
    required: true
  - name: SERPAPI_KEY
    description: "Web search"
    required: false
  - name: FRED_API_KEY
    description: "Economic time-series data"
    required: false
```

`hermes_requires` is the compatibility field name used by the current profile-distribution runtime. It constrains the Superforecasting Agent version.

Commit and publish:

```bash
cd ~/.superforecasting-agent/profiles/macro-forecast-desk
git init
git add .
git commit -m "v1.0.0"
git remote add origin git@github.com:you/macro-forecast-desk.git
git tag v1.0.0
git push -u origin main --tags
```

## Distribution-Owned Vs User-Owned

On update, distribution-owned paths are refreshed from the source repo. User-owned paths stay local.

| Category | Paths | Update behavior |
|---|---|---|
| Distribution-owned | `SOUL.md`, `config.yaml`, `mcp.json`, `skills/`, `cron/`, `distribution.yaml` | Replaced from the new source |
| Config override | `config.yaml` | Preserved by default; pass `--force-config` to replace it |
| User-owned | `forecasting/`, `memories/`, `sessions/`, `.env`, `auth.json`, `logs/`, `workspace/`, `home/`, `plans/`, `local/`, caches, state DBs | Never copied or overwritten |

Authors can narrow the distribution-owned set:

```yaml
distribution_owned:
  - SOUL.md
  - skills/base-rate-research/
  - skills/evidence-triage/
  - cron/daily-staleness-check.json
```

Use this when a distribution should update only a specific forecasting protocol or skill bundle while leaving other local desk customizations intact.

## Update

```bash
superforecasting-agent profile update macro-forecast-desk
```

Update re-clones the recorded source, refreshes distribution-owned paths, and preserves local user-owned data. The most important preservation rule is the ledger: `forecasting/` stays untouched even if the upstream repo accidentally contains one.

To reset the local config to the distribution default:

```bash
superforecasting-agent profile update macro-forecast-desk --force-config
```

`--force-config` affects `config.yaml`; it does not make forecast ledger state distributable.

## Scheduled Checks

Forecast-desk distributions may include cron jobs for:

- Stale-forecast checks.
- New-evidence scans for active questions.
- Domain-specific alerts.
- Weekly calibration review.
- Resolved-question postmortems.
- Backtest replay jobs.

Keep these jobs auditable. A good cron job should write to the forecast ledger or review queue with timestamps, source references, and an explicit reason for any probability update it proposes.

For team distributions, document each job in the repo README. Installers should know which jobs are source monitoring, which are scoring/review jobs, and which may call paid APIs.

## Security Model

Treat every distribution like code:

- Read `SOUL.md`, `skills/`, `cron/`, and `mcp.json` before installing.
- Prefer tags or commit SHAs for production desks.
- Keep credentials in `.env`; never commit them.
- Put local-only customizations under `local/`.
- Keep the ledger local unless you are deliberately exporting it through a separate backup or audit process.

Private repos use your existing git authentication. SSH keys, credential helpers, and GitHub CLI credentials work the same way they do for normal git operations.

## Inspect

```bash
superforecasting-agent profile info macro-forecast-desk
```

The info command shows the installed distribution name, version, author, source, install time, and environment requirements.

`superforecasting-agent profile list` also includes distribution metadata, so you can distinguish hand-built desks from desks installed from versioned templates.

## Remove

```bash
superforecasting-agent profile delete macro-forecast-desk
```

Deletion removes the local profile, including local user-owned state. That is different from update, which preserves user-owned state. Export anything you need before deleting a desk.

## Patterns

**Personal template**

Use a private repo to keep the same desk protocol across machines while allowing each machine to build its own ledger.

```bash
superforecasting-agent profile install github.com/you/macro-forecast-desk --alias
```

**Team desk**

An internal team can ship shared skills, source connectors, cron checks, and review standards while every analyst keeps a separate probability history.

```bash
superforecasting-agent profile install git@github.com:your-org/policy-forecast-desk.git --alias
```

**Domain starter**

Publish a starter distribution for energy, elections, geopolitics, credit risk, biology, sports, or another question domain. The distribution should provide workflow and tools, not preloaded conclusions.

```bash
superforecasting-agent profile install github.com/you/energy-forecast-desk --alias
```

**Local development**

Test a distribution from a local directory before pushing:

```bash
superforecasting-agent profile install ~/.superforecasting-agent/profiles/macro-forecast-desk --name macro-forecast-desk-test --alias
superforecasting-agent profile delete macro-forecast-desk-test --yes
```

## See Also

- [Profiles](./profiles.md)
- [Profile command reference](../reference/profile-commands.md)
- [Integrations](../integrations/index.md)
