# Plugin integrations

Contains bundled integrations discovered through general, model-provider and specialized plugin surfaces.

## Ownership and boundaries

Use registration interfaces rather than plugin-specific branches in core runtime. New memory providers ship externally; model-provider discovery is separate from general plugin loading.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility |
| -------------------------- | -------------- |
| [\_\_init\_\_.py](__init__.py) | init .         |

## Subdirectories

- [browser/](browser/README.md) — browser.
- [context_engine/](context_engine/README.md) — Context engine integrations.
- [disk-cleanup/](disk-cleanup/README.md) — disk-cleanup integration.
- [google_meet/](google_meet/README.md) — google_meet integration.
- [image_gen/](image_gen/README.md) — image gen.
- [kanban/](kanban/README.md) — kanban.
- [meeting_common/](meeting_common/README.md) — Shared meeting integration.
- [memory/](memory/README.md) — Memory provider integrations.
- [model-providers/](model-providers/README.md) — model-providers.
- [observability/](observability/README.md) — observability.
- [obsidian/](obsidian/README.md) — obsidian integration.
- [platforms/](platforms/README.md) — platforms.
- [teams_pipeline/](teams_pipeline/README.md) — teams_pipeline integration.
- [video_gen/](video_gen/README.md) — video gen.
- [web/](web/README.md) — web.

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
[ownership map](../docs/architecture/ownership-map.md)
and [engineering backlog](../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
