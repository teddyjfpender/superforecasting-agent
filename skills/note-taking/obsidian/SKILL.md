---
name: obsidian
description: Read, search, create, and edit notes in the Obsidian vault, and publish forecast learnings into it.
platforms: [linux, macos, windows]
---

# Obsidian Vault

Use this skill for Obsidian vault work: reading notes, listing notes, searching note files, creating notes, appending content, adding wikilinks, and publishing the forecast desk's learnings into the vault.

## Native tools (preferred)

When the `obsidian` plugin is enabled (`superforecasting-agent plugins enable obsidian`), prefer its native tools — they resolve the vault path themselves, are traversal-safe, and understand frontmatter and wikilinks:

- `obsidian_read_note` — read a note by vault-relative path (`.md` optional).
- `obsidian_write_note` — create a note (folders auto-created, optional YAML frontmatter). Refuses to overwrite unless `overwrite=true`.
- `obsidian_append_note` — append markdown to a note, optionally at the end of a named `heading` section. Creates the note if missing.
- `obsidian_search` — `kind="files"` matches note names, `kind="content"` greps bodies (case-insensitive regex), optional `folder` restriction.
- `obsidian_sync_learnings` — publish the forecast ledger into the vault: one note per calibration lesson, one dossier per question (description, current probability, analyst-note timeline), and a `Forecasting/Forecast Desk Index` linking everything. Idempotent: regenerated content lives between managed `superforecasting` markers, so human annotations around it survive re-syncs. The ledger DB stays the source of truth — never treat vault notes as authoritative forecast state.

After material forecast work (new lessons, resolutions, postmortems), offer to run `obsidian_sync_learnings` so the user's vault reflects the desk's current opinions. The CLI equivalent is `superforecasting-agent obsidian sync`.

## Wikilinks

Obsidian links notes with `[[Note Name]]` syntax. When creating notes, use these to link related content — e.g. link a market-thesis note to its question dossier under `Forecasting/Questions/`.

## Vault path

The vault-path convention is the `OBSIDIAN_VAULT_PATH` environment variable, for example from `~/.superforecasting-agent/.env`. If it is unset, `~/Documents/Obsidian Vault` is used when it exists. Native tools resolve this automatically; `superforecasting-agent obsidian path` prints it.

## Fallback: generic file tools

If the plugin is not enabled, fall back to the generic file tools with a concrete absolute vault path (file tools do not expand `$OBSIDIAN_VAULT_PATH`; vault paths may contain spaces, so prefer file tools over shell commands):

- **Read** — `read_file` with the resolved absolute note path.
- **List** — `search_files` with `target: "files"`, `pattern: "*.md"` under the vault path.
- **Search contents** — `search_files` with `target: "content"`, the regex as `pattern`, and `file_glob: "*.md"`.
- **Create** — `write_file` with the full markdown content.
- **Append / targeted edits** — `read_file` then `patch` for anchored changes; `write_file` when rewriting the whole note is clearer. For a simple append with no stable context, `terminal` is acceptable if it is the clearest safe option.
