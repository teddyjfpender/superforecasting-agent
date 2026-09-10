---
title: "Openclaw Migration — Import OpenClaw settings into Superforecasting Agent"
sidebar_label: "Openclaw Migration"
description: "Import OpenClaw settings into Superforecasting Agent"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Openclaw Migration

Import OpenClaw settings into Superforecasting Agent.

## Skill metadata

| | |
|---|---|
| Source | Optional — install with `superforecasting-agent skills install official/migration/openclaw-migration` |
| Path | `optional-skills/migration/openclaw-migration` |
| Version | `1.1.0` |
| Author | Theodore Pender; Superforecasting Agent; Nous Research |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `Migration`, `OpenClaw`, `Forecasting`, `Memory`, `Import` |
| Related skills | [`superforecasting-agent`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-hermes-agent) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Superforecasting Agent loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# OpenClaw Migration Skill

Import compatible OpenClaw workspace data and settings into Superforecasting Agent.
The helper previews changes, handles conflicts and produces an itemized report;
unsupported service configuration is archived for manual review.

## When to Use

Use when the user wants to migrate an OpenClaw installation or inspect what a
migration would change. This does not migrate active sessions, pair messaging
devices, recreate scheduled jobs or replace the forecast ledger.

## Prerequisites

- Python 3.10 or newer; PyYAML is required for configuration writes.
- Access to the source OpenClaw home and the intended target profile.
- Use `terminal` to run the helper, `read_file` to inspect reports and
  `search_files` to locate a moved installation.
- The optional skill must be installed with its entire `scripts/` directory.
  Its sibling modules are required; copying only the entry script is insufficient.
- For guided decisions, use the native `clarify` tool when available.

Resolve `scripts/openclaw_to_forecast.py` relative to this installed `SKILL.md`.
The usual location is
`~/.superforecasting-agent/skills/migration/openclaw-migration/scripts/`.
Use an absolute `terminal` working directory; do not pass `workdir: "~"`.
The older `openclaw_to_hermes.py` filename remains a compatibility launcher.

## How to Run

The built-in command locates the helper and previews before applying:

```bash
superforecasting-agent claw migrate --dry-run --preset user-data
superforecasting-agent claw migrate --preset user-data
```

For machine-readable previews and category selection, run the standalone
helper from the installed skill directory:

```bash
python3 scripts/openclaw_to_forecast.py --preset user-data --json
```

The standalone helper is a dry run unless `--execute` is present. After the
user's migration and conflict choices are settled:

```bash
python3 scripts/openclaw_to_forecast.py --execute --preset user-data --skill-conflict skip --json
```

For an explicitly requested migration of supported credentials:

```bash
python3 scripts/openclaw_to_forecast.py --execute --preset full --migrate-secrets --skill-conflict skip --json
```

Use `--source` and `--target` for custom homes. The standalone target defaults
to `SUPERFORECASTING_AGENT_HOME`, then `FORECAST_HOME`, then compatibility
`HERMES_HOME`, then `~/.superforecasting-agent`.

## Quick Reference

| Choice | Standalone flag or behavior |
|---|---|
| Preview | Omit `--execute`; add `--json` for a redacted report |
| Apply | `--execute` |
| Keep existing target values | Omit `--overwrite` |
| Replace conflicting target values | `--overwrite`, only for the agreed scope |
| Keep existing skills | `--skill-conflict skip` |
| Replace conflicting skills | `--skill-conflict overwrite` |
| Import skills alongside existing ones | `--skill-conflict rename` |
| Copy workspace instructions | `--workspace-target /absolute/workspace` |
| Select categories | `--include memory,user-profile` without a preset |
| Remove categories from a preset | `--preset user-data --exclude workspace-agents` |
| Report and backup directory | `--output-dir /absolute/report-directory` |

`user-data` includes workspace files, memories, skill imports, messaging
settings, model/TTS preferences and service-configuration groups. `full` adds
`secret-settings` and `provider-keys`; selecting it alone does not enable
credential import. `--migrate-secrets` independently enables supported credential
extraction in the selected groups.

Do not maintain a second exhaustive category or credential list here. The
preview's `selection.available` and `selection.presets`, and the helper's
`--help`, describe the installed version. Provider, Telegram, Discord and Slack
credentials have different destination mappings; inspect the actual report.

## Procedure

1. Establish source and target homes. Prefer the primary OpenClaw workspace;
   the helper also recognizes renamed and configured workspaces. Do not infer
   a destination for workspace instructions from the current directory.
2. Run a preview using the proposed selection. Omit `--output-dir` for a
   preview that does not write report files. Inspect `summary`, `items`,
   `warnings` and `selection` from the JSON output.
3. Call out conflicts, large asset copies and memory overflow. Present the
   concrete command and scope before applying changes. Existing authorization
   remains valid; ask only for decisions that are still unresolved.
4. Resolve conflicts, migration mode and workspace instructions using
   `clarify`. It accepts one `question` and optionally two to four string
   `choices`, not multi-select fields. Use a separate open-ended question only
   when an absolute destination path is needed. If unavailable, ask in text.
5. If `workspace-agents` is skipped because no workspace target was provided,
   resolve that choice before execution: skip it, decide later, or provide a
   destination. A missing path is not itself a decision to skip. Exclude the
   category when the user chooses to omit it.
6. Run the exact selected command after required decisions are resolved.
   Do not silently add `--overwrite` or `--migrate-secrets`.
7. Read the resulting report and summarize actual outcomes. A dry-run item
   marked `migrated` means a proposed action, not an executed write.

Examples of concise decision prompts:

```json
{"question":"How should existing imported skills be handled?","choices":["keep existing skills","overwrite with backup","import under renamed folders"]}
```

```json
{"question":"Copy workspace instructions into a forecast workspace?","choices":["skip workspace instructions","copy to a workspace path","decide later"]}
```

```json
{"question":"Which migration scope should be applied?","choices":["user data and settings","include supported credentials","cancel"]}
```

If the user wants to review conflicting files, inspect them before applying.
A global `--overwrite` affects more than `SOUL.md`; narrow the selection when
only one conflict was approved. Renaming imports leaves existing skills in place.

## Pitfalls

- `--preset` determines the starting selection; `--include` does not augment
  a preset. Use `--exclude` to narrow it, or use `--include` without a preset.
- External workspace settings go to `config.yaml` under `terminal.cwd`.
  Do not write removed `MESSAGING_CWD` settings into `.env`.
- MCP environment, header and auth dictionaries are omitted without
  `--migrate-secrets`; the report identifies servers needing manual credentials.
- Configuration archives and JSON reports redact known credential fields and
  token patterns. This is not a general sanitizer for arbitrary copied documents,
  skill files or directories. Review local artifacts before sharing them.
- Raw service archives and copied directories can require manual recreation.
  Do not describe archived cron, plugin or gateway configuration as activated.
- A configuration conflict or error blocks later configuration writes in the
  same execution. Fix the cause and preview again; do not imply atomic rollback.
- Both output modes return a failure status when the report contains errors.
  Conflicts still require inspection even when the process exits zero.
- A supplied `--output-dir` can write reports and overflow files during a dry
  run. Omit it when a completely read-only preview is required.
- Secret references backed by external files or commands are not automatically
  resolved. Do not execute them or copy unsupported auth/device state.
- Migration does not stop existing OpenClaw or external processes. Do not rename
  the source directory or run `claw cleanup` without authorization for that action.

## Verification

Use `report.summary` for counts and item status for claims. Only executed items
with `status="migrated"` count as applied; list remaining conflicts, errors,
skips and archives separately. Check actual destination files when an outcome
matters, particularly the target profile's `config.yaml` and imported skills.

Report the returned `output_dir` so the user can inspect `report.json`,
`summary.md`, `MIGRATION_NOTES.md`, backups and archives. For memory overflow,
use `details.overflow_file`; do not call it archived without an archive result.
For renamed skills, report the final destination and `details.renamed_from`.
An empty backup field does not prove a backup was made.

Start a new Superforecasting Agent session to load imported skills and settings.
Verify the requested channels separately; device pairing and service activation
remain separate operations. Never claim migration success solely from a zero
exit code or a preview count.
