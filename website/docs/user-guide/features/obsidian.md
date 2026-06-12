# Obsidian Vault Integration

The `obsidian` plugin turns an Obsidian vault into the forecast desk's publishing surface: the agent can read, write, append, and search notes natively, and `obsidian_sync_learnings` publishes the ledger's learnings — calibration lessons, question dossiers, and an index — as a linked knowledge graph.

## Enable

```bash
superforecasting-agent plugins enable obsidian
```

Set the vault location (or rely on the `~/Documents/Obsidian Vault` fallback):

```bash
# e.g. in ~/.superforecasting-agent/.env
OBSIDIAN_VAULT_PATH="/path/to/your/vault"
```

## Tools

| Tool | What it does |
| --- | --- |
| `obsidian_read_note` | Read a note by vault-relative path (`.md` optional) |
| `obsidian_write_note` | Create a note with optional YAML frontmatter; refuses overwrite unless asked |
| `obsidian_append_note` | Append markdown, optionally at the end of a named heading section |
| `obsidian_search` | Search note names (`kind="files"`) or bodies (`kind="content"`, regex) |
| `obsidian_sync_learnings` | Publish ledger learnings into the vault (see below) |

All paths are vault-relative and traversal-safe — the tools never read or write outside the vault.

## Learnings sync

`obsidian_sync_learnings` (CLI: `superforecasting-agent obsidian sync`) publishes under `Forecasting/` in the vault:

- **`Lessons/`** — one note per calibration lesson: the distilled opinion, scope, confidence, status, and evidence refs.
- **`Questions/`** — one dossier per question: description, resolution criteria, current probability, rationale, and the analyst-note timeline, wikilinked to lessons that share its domain.
- **`Forecast Desk Index`** — the entry point linking everything.

Syncs are idempotent. Generated content lives between `superforecasting` managed markers, so your own annotations above or below the block survive re-syncs. The ledger database remains the source of truth — the vault is a view, never an input.

## CLI

```bash
superforecasting-agent obsidian status   # vault path + note counts
superforecasting-agent obsidian sync     # publish lessons + dossiers
superforecasting-agent obsidian sync --active-only --scope lessons
superforecasting-agent obsidian path     # print resolved vault path
```
