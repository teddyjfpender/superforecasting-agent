---
sidebar_position: 8
title: "Context Files"
description: "Project context files and SOUL.md prompt identity loading."
---

# Context Files

Superforecasting Agent loads context files that shape how it works in a repository or profile. Use them for project conventions, source-adapter rules, benchmark workflow notes, and forecast-desk behavior. Do not use context files as forecast memory: scoreable forecast state belongs in the forecast ledger.

## Supported Files

| File | Purpose | Discovery |
|------|---------|-----------|
| `.hermes.md` / `HERMES.md` | Inherited project instruction filenames, highest priority | Walks to git root |
| `AGENTS.md` | Project instructions, conventions, architecture | CWD at startup + subdirectories progressively |
| `CLAUDE.md` | Claude Code context files | CWD at startup + subdirectories progressively |
| `SOUL.md` | Global profile identity, tone, and standing behavior | Active agent home only |
| `.cursorrules` | Cursor IDE coding conventions | CWD only |
| `.cursor/rules/*.mdc` | Cursor IDE rule modules | CWD only |

Only one project context type is loaded at startup, in this order:

```text
.hermes.md -> AGENTS.md -> CLAUDE.md -> .cursorrules
```

`SOUL.md` is loaded independently as the profile identity. New profiles use `~/.superforecasting-agent/SOUL.md`; inherited profiles may still use `~/.hermes/SOUL.md` through the bridged `HERMES_HOME` runtime variable.

## AGENTS.md

`AGENTS.md` is the recommended project context file. It should tell the agent how the project is structured, which conventions matter, and which commands are safe to run.

### Progressive Subdirectory Discovery

At session start, the runtime loads the `AGENTS.md` from your working directory. As tools touch subdirectories, `SubdirectoryHintTracker` discovers nested `AGENTS.md`, `CLAUDE.md`, or `.cursorrules` files and appends the relevant guidance to the tool result.

```text
forecast-project/
├── AGENTS.md              # loaded at startup
├── sources/
│   └── AGENTS.md          # loaded when source files are touched
├── backtests/
│   └── AGENTS.md          # loaded when backtest files are touched
└── dashboard/
    └── AGENTS.md          # loaded when dashboard files are touched
```

This keeps startup prompts smaller and preserves prompt-cache stability while still surfacing local rules when they matter.

### Example

```markdown
# Project Context

This repository maintains forecast source adapters and replay benchmarks.

## Architecture
- `forecasting/source_adapters.py` contains source import adapters
- `forecasting/backtesting.py` owns replay scoring
- `tests/forecasting/` contains ledger and CLI regression tests

## Conventions
- Evidence imports must preserve publication and availability timestamps
- Forecast updates must cite evidence/model/reference/assumption records
- Backtests must avoid leakage past each question's evidence cutoff
- Do not mutate resolved benchmark fixtures without adding a changelog note

## Verification
- Run `scripts/run_tests.sh tests/forecasting -q`
```

## SOUL.md

`SOUL.md` controls identity, tone, and standing behavior. It can describe a forecast-desk persona, but it should not store active probabilities, evidence, or lessons learned. Those belong in the ledger so they can be audited and scored.

Location:

- `~/.superforecasting-agent/SOUL.md`
- legacy fallback: `~/.hermes/SOUL.md`
- bridged runtime variable: `$HERMES_HOME/SOUL.md`

Important details:

- a default `SOUL.md` is seeded when a profile is created
- `SOUL.md` is loaded only from the active agent home
- the working directory is not searched for `SOUL.md`
- empty files are ignored
- content is scanned and truncated before prompt injection

See [Personality](/user-guide/features/personality) for profile identity guidance.

## Cursor Rules

Superforecasting Agent can load Cursor IDE's `.cursorrules` and `.cursor/rules/*.mdc` files when no higher-priority project context file is present. This lets existing Cursor project conventions apply without creating a separate `AGENTS.md`.

## Loading Flow

Startup context is assembled by `build_context_files_prompt()` in `agent/prompt_builder.py`:

1. scan the working directory for `.hermes.md`, `AGENTS.md`, `CLAUDE.md`, then `.cursorrules`
2. read the first matching project context file
3. scan for prompt-injection patterns
4. truncate large files
5. assemble under `# Project Context`
6. inject into the system prompt

During a session, `SubdirectoryHintTracker` watches tool-call paths, checks the target directory and up to five parents, loads the first local context file it finds, scans it, truncates it, and appends it to the tool result.

`SOUL.md` is loaded separately from the active agent home.

## Security Scan

Context files are scanned for common prompt-injection patterns before inclusion:

- instruction override attempts
- deception patterns such as "do not tell the user"
- system prompt override claims
- hidden HTML comments or hidden divs
- credential exfiltration attempts
- secret-file access patterns
- invisible Unicode controls

If a threat pattern is detected, the file is blocked:

```text
[BLOCKED: AGENTS.md contained potential prompt injection (prompt_injection). Content not loaded.]
```

The scanner is a guardrail, not a substitute for reviewing context files in shared repositories.

## Size Limits

| Limit | Value |
|-------|-------|
| Max chars per startup file | 20,000 |
| Max chars per discovered subdirectory file | 8,000 |
| Head truncation ratio | 70% |
| Tail truncation ratio | 20% |

Example truncation marker:

```text
[...truncated AGENTS.md: kept 14000+4000 of 25000 chars. Use file tools to read the full file.]
```

## Best Practices

- Keep `AGENTS.md` concise and operational.
- Put forecast state, calibration lessons, and postmortems in the ledger, not in context files.
- Include commands and paths the agent should actually use.
- Add source-adapter, evidence, and backtest rules where they prevent mistakes.
- Use nested `AGENTS.md` files for monorepos.
- Review inherited `.hermes.md` and `HERMES.md` files before relying on them in the fork.
