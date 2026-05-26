---
sidebar_position: 9
sidebar_label: "Context References"
title: "Context References"
description: "Attach files, folders, diffs, commits, and URLs inline with @ syntax."
---

# Context References

Type `@` followed by a reference to inject content directly into a CLI message. The runtime expands the reference inline and appends the content under an `--- Attached Context ---` section.

For the forecast desk, context references are a fast way to bring source adapter code, benchmark fixtures, model scripts, resolution criteria, local notes, git diffs, and web pages into a research or engineering turn. They are not ledger writes. If referenced material should become durable evidence, a model run, an assumption, or a calibration lesson, record it through the forecast workflow explicitly.

## Supported References

| Syntax | Description |
|--------|-------------|
| `@file:path/to/file.py` | Inject file contents |
| `@file:path/to/file.py:10-25` | Inject a 1-indexed inclusive line range |
| `@folder:path/to/dir` | Inject directory tree listing with file metadata |
| `@diff` | Inject unstaged working-tree changes |
| `@staged` | Inject staged changes |
| `@git:5` | Inject the last N commits with patches, max 10 |
| `@url:https://example.com` | Fetch and inject web page content |

## Forecast Examples

```text
Review @file:forecasting/source_adapters.py before I add a new evidence feed.
```

```text
Check whether @diff changes the scoring behavior for numeric forecasts.
```

```text
Compare the local resolver note @file:notes/resolution.md with @url:https://example.com/resolution-source.
```

```text
Use @file:data/backtest-fixture.json and @file:forecasting/models.py:40-120 to explain this benchmark result.
```

Multiple references can appear in one message:

```text
Audit @file:forecasting/ledger.py and @file:tests/forecasting/test_ledger.py.
```

Trailing punctuation such as `,`, `.`, `;`, `!`, and `?` is stripped from reference values.

## CLI Tab Completion

In the interactive CLI, typing `@` triggers autocomplete:

- `@` shows all reference types.
- `@file:` and `@folder:` trigger filesystem path completion with file size metadata.
- Bare `@` followed by partial text shows matching files and folders from the current directory.

## Line Ranges

Use line ranges when only a narrow portion of a file is relevant:

```text
@file:forecasting/ledger.py:120-180
@file:tests/forecasting/test_cli.py:42
```

Lines are 1-indexed. Invalid ranges are ignored and the full file is returned.

## Size Limits

Context references are bounded to protect the model context window:

| Threshold | Value | Behavior |
|-----------|-------|----------|
| Soft limit | 25% of context length | Warning appended, expansion proceeds |
| Hard limit | 50% of context length | Expansion refused, original message returned unchanged |
| Folder entries | 200 files max | Excess entries replaced with `- ...` |
| Git commits | 10 max | `@git:N` clamped to range [1, 10] |

For large forecast artifacts, prefer a focused line range or a structured forecast command such as evidence import, benchmark import, or model-run recording.

## Security

### Sensitive Path Blocking

These paths are always blocked from `@file:` references:

- SSH keys and config: `~/.ssh/id_rsa`, `~/.ssh/id_ed25519`, `~/.ssh/authorized_keys`, `~/.ssh/config`
- Shell profiles: `~/.bashrc`, `~/.zshrc`, `~/.profile`, `~/.bash_profile`, `~/.zprofile`
- Credential files: `~/.netrc`, `~/.pgpass`, `~/.npmrc`, `~/.pypirc`
- Forecast env: `$SUPERFORECASTING_AGENT_HOME/.env`
- Legacy env: `$HERMES_HOME/.env`

These directories are fully blocked:

- `~/.ssh/`
- `~/.aws/`
- `~/.gnupg/`
- `~/.kube/`
- `$SUPERFORECASTING_AGENT_HOME/skills/.hub/`
- `$HERMES_HOME/skills/.hub/`

`$HERMES_HOME` remains listed for migrated profiles and compatibility wrappers.

### Path Traversal Protection

All paths resolve relative to the working directory. References that resolve outside the allowed workspace root are rejected.

### Binary File Detection

Binary files are detected through MIME type and null-byte checks. Known text extensions such as `.py`, `.md`, `.json`, `.yaml`, `.toml`, `.js`, and `.ts` bypass MIME-based detection. Binary files are rejected with a warning.

## Platform Availability

Context references are primarily a CLI feature. They work in the interactive CLI where `@` triggers tab completion and references expand before the message is sent.

In messaging platforms such as Telegram and Discord, the `@` syntax is not expanded by the gateway. Messages are passed through as-is. The agent can still inspect files or sources with tools such as `read_file`, `search_files`, and `web_extract`.

## Interaction With Context Compression

Expanded reference content is included in forecast-session context and therefore in compression summaries. This means:

- Large file contents count against context usage.
- Compressed forecast sessions summarize referenced content rather than preserving it verbatim.
- A compressed mention is not a durable evidence snapshot.

For source material that must be audited later, import it into the forecast ledger with timestamp, source metadata, reliability, and relevance notes.

## Error Handling

Invalid references produce inline warnings rather than failures:

| Condition | Behavior |
|-----------|----------|
| File not found | Warning: `file not found` |
| Binary file | Warning: `binary files are not supported` |
| Folder not found | Warning: `folder not found` |
| Git command fails | Warning with git stderr |
| URL returns no content | Warning: `no content extracted` |
| Sensitive path | Warning: `path is a sensitive credential file` |
| Path outside workspace | Warning: `path is outside the allowed workspace` |
