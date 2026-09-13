# Video generation providers

Groups the video-generation plugin implementations. Each provider owns its request format, asynchronous job handling and output retrieval.

## Ownership and boundaries

Keep provider credentials optional and preserve remote job identity during polling and cancellation. Generated media belongs to the active profile.

## Subdirectories

- [fal/](fal/README.md) — fal integration.
- [xai/](xai/README.md) — xai integration.

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
