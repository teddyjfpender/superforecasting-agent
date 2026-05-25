---
sidebar_position: 3
title: "Curator"
description: "Maintain agent-created forecasting skills in the background."
---

# Curator

The curator is a background maintenance pass for agent-created skills. It tracks usage, moves unused skills through `active -> stale -> archived`, and runs an auxiliary-model review that can propose patches or consolidations.

For the forecast desk, skills are procedural playbooks: research routines, source-handling checklists, modeling recipes, domain review steps, and reporting formats. They are not the forecast ledger. The curator may improve or archive skills, but it does not change probabilities, evidence, model runs, resolutions, scores, postmortems, calibration lessons, or domain error profiles.

## How It Runs

The curator is triggered by inactivity, not by a standalone cron daemon. On CLI session start, and on a recurring gateway cron-ticker check, the runtime verifies:

1. Enough time has passed since the last curator run.
2. The process has been idle long enough.

If both are true, it starts a background fork of the agent loop. The fork runs in its own prompt cache and never touches the active conversation.

:::info First-run behavior
On a new install, or the first curator-capable run after upgrading a legacy install, the curator does not run immediately. The first observation records `last_run_at` and defers the first real pass by one full interval.

Preview a pass without mutations:

```bash
superforecasting-agent curator run --dry-run
```
:::

A run has two phases:

1. Automatic transitions. Skills unused for `stale_after_days` become `stale`; skills unused for `archive_after_days` move to the archive directory.
2. LLM review. A short auxiliary-model pass reads agent-created skills and decides whether to keep, patch, consolidate, or archive them.

Pinned skills are off-limits to both automatic transitions and the agent's own `skill_manage` delete action. See [Pinning a Skill](#pinning-a-skill).

## Configuration

Settings live under `curator` in `~/.superforecasting-agent/config.yaml`:

```yaml
curator:
  enabled: true
  interval_hours: 168
  min_idle_hours: 2
  stale_after_days: 30
  archive_after_days: 90
```

Disable the curator with:

```yaml
curator:
  enabled: false
```

Legacy `~/.hermes/config.yaml` profiles remain readable during migration.

## Auxiliary Model

The review pass uses the `auxiliary.curator` model slot. `auto` means it uses the main model. Pin a cheaper or faster model when review latency or cost matters:

```yaml
auxiliary:
  curator:
    provider: openrouter
    model: google/gemini-3-flash-preview
    timeout: 600
```

You can also configure this with:

```bash
superforecasting-agent model
```

Earlier releases used `curator.auxiliary.{provider,model}`. That path remains a compatibility setting but should be migrated to `auxiliary.curator`.

## CLI

```bash
superforecasting-agent curator status
superforecasting-agent curator run
superforecasting-agent curator run --background
superforecasting-agent curator run --dry-run
superforecasting-agent curator backup
superforecasting-agent curator rollback
superforecasting-agent curator rollback --list
superforecasting-agent curator rollback --id <ts>
superforecasting-agent curator rollback -y
superforecasting-agent curator pause
superforecasting-agent curator resume
superforecasting-agent curator pin <skill>
superforecasting-agent curator unpin <skill>
superforecasting-agent curator restore <skill>
```

The same subcommands are available as `/curator` inside a running CLI or gateway session.

The inherited `hermes curator ...` command remains available where compatibility entry points are installed.

## Backups and Rollback

Before every real pass, the curator snapshots the skills tree:

```text
~/.superforecasting-agent/skills/.curator_backups/<utc-iso>/skills.tar.gz
```

Rollback restores the newest snapshot unless you pass an explicit id:

```bash
superforecasting-agent curator rollback
superforecasting-agent curator rollback --list
superforecasting-agent curator rollback --id <ts>
```

The rollback itself is reversible. Before replacing the active skills tree, the curator takes a `pre-rollback to <target-id>` snapshot.

Take a manual snapshot:

```bash
superforecasting-agent curator backup --reason "before-domain-skill-refactor"
```

Snapshots are pruned by `curator.backup.keep`:

```yaml
curator:
  backup:
    enabled: true
    keep: 5
```

Set `curator.backup.enabled: false` to disable automatic snapshots. Manual backup is also gated by that setting.

Legacy profiles may store the same backup structure under `~/.hermes/skills/.curator_backups/`.

## What Agent-Created Means

A skill is considered agent-created if its name is not in:

- `~/.superforecasting-agent/skills/.bundled_manifest`
- `~/.superforecasting-agent/skills/.hub/lock.json`

Everything else in `~/.superforecasting-agent/skills/` is eligible for curator review. That includes:

- skills saved by `skill_manage(action="create")`
- hand-written local skills
- skills added through external directories

:::warning Hand-written skills can look agent-created
Provenance is binary: bundled or hub-installed versus everything else. The curator cannot always distinguish a private hand-authored skill from one created by the self-improvement loop.

Before the first real pass:

1. Run `superforecasting-agent curator run --dry-run`.
2. Pin anything that should not be touched.
3. Or set `curator.enabled: false`.
:::

Migrated profiles may use `~/.hermes/skills/`, `~/.hermes/skills/.bundled_manifest`, and `~/.hermes/skills/.hub/lock.json`.

## Pinning a Skill

Pinning protects a skill from deletion and archival. Once pinned:

- The curator skips it during automatic transitions.
- The LLM review pass is instructed to leave it alone.
- `skill_manage(action="delete")` refuses to delete it and points at the unpin command.

Pin and unpin with:

```bash
superforecasting-agent curator pin <skill>
superforecasting-agent curator unpin <skill>
```

The pinned flag is stored in the skill usage sidecar. Bundled and hub-installed skills are never subject to curator mutation and cannot be pinned through this path.

If you need to freeze a hand-authored skill's content, edit the file permissions or manage it outside the auto-curated skills tree. Pinning blocks tool-driven deletion and archival; it does not prevent direct filesystem edits.

## Usage Telemetry

The curator maintains a sidecar at:

```text
~/.superforecasting-agent/skills/.usage.json
```

Example:

```json
{
  "forecast-election-reference-class": {
    "use_count": 12,
    "view_count": 34,
    "last_used_at": "2026-04-24T18:12:03Z",
    "last_viewed_at": "2026-04-23T09:44:17Z",
    "patch_count": 3,
    "last_patched_at": "2026-04-20T22:01:55Z",
    "created_at": "2026-03-01T14:20:00Z",
    "state": "active",
    "pinned": false,
    "archived_at": null
  }
}
```

Counters increment when:

- `view_count`: the agent calls `skill_view`.
- `use_count`: the skill is loaded into a prompt.
- `patch_count`: `skill_manage` patches, edits, writes, or removes files in the skill.

Bundled and hub-installed skills are excluded from telemetry writes.

Legacy profiles may store this sidecar at `~/.hermes/skills/.usage.json`.

## Per-Run Reports

Every curator run writes a timestamped report directory:

```text
~/.superforecasting-agent/logs/curator/
└── 20260429-111512/
    ├── run.json
    └── REPORT.md
```

`REPORT.md` summarizes transitions, review notes, patches, and consolidations. It is useful for auditing skill-library changes, but it is not a forecast postmortem and does not update calibration memory.

### Rename Map in the Summary

If a run consolidates multiple skills, the summary includes a rename map showing each `old-name -> new-name` pair. The same hint appears under `curator pin` so you can pin the new umbrella skill if needed.

## Restoring an Archived Skill

Restore an archived skill:

```bash
superforecasting-agent curator restore <skill-name>
```

This moves the skill back from `~/.superforecasting-agent/skills/.archive/` to the active tree and resets its state to `active`. The restore refuses if a bundled or hub-installed skill now exists under the same name.

Legacy profiles may restore from `~/.hermes/skills/.archive/`.

## Disabling Per Environment

The curator is on by default. To disable it:

- For one profile, set `curator.enabled: false` in `~/.superforecasting-agent/config.yaml`.
- For just one run window, use `superforecasting-agent curator pause`; use `resume` to re-enable.

The curator also refuses to run if `min_idle_hours` has not elapsed.

## See Also

- [Skills System](/user-guide/features/skills) for procedural forecasting playbooks
- [Memory](/user-guide/features/memory) for auxiliary recall outside the forecast ledger
- [Bundled Skills Catalog](/reference/skills-catalog)
