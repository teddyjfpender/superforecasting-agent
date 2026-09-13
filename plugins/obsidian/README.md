# obsidian integration

Implements the obsidian plugin. Native Obsidian vault integration — read, write, append, and search notes, plus the forecast desk's second brain: sync the ledger's concept graph (questions with cruxes/links, lessons, theses, cruxes, postmortems, entities) into wikilinked pages, query a question's vault neighbourhood before forecasting, and ingest the operator's page annotations back as triage-gated evidence. Vault path comes from OBSIDIAN_VAULT_PATH, else the managed workspace vault ~/.superforecasting-agent/docs/vault (created on first use). Generated notes keep agent content inside managed markers so human edits outside them survive re-syncs.

## Ownership and boundaries

Register capabilities through the plugin interface. Keep optional dependencies optional and preserve active-profile isolation. Core runtime must not contain branches specific to this plugin.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility                                                             |
| -------------------------- | -------------------------------------------------------------------------- |
| [**init**.py](__init__.py) | obsidian plugin — native vault integration for notes, learnings, opinions. |
| [cli.py](cli.py)           | CLI commands for the obsidian plugin.                                      |
| [ingest.py](ingest.py)     | Vault → agent: operator note deltas ingested AS EVIDENCE, triage-gated.    |
| [manifest.py](manifest.py) | The vault delta manifest — the watch-signature pattern applied to pages.   |
| [plugin.yaml](plugin.yaml) | plugin.                                                                    |
| [prune.py](prune.py)       | The pruning doctrine — deep pruning against context rot.                   |
| [starter.py](starter.py)   | Starter knowledge base seeded into a fresh forecasting vault.              |
| [sync.py](sync.py)         | Sync the forecast desk's learnings into the Obsidian vault.                |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/plugins/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
