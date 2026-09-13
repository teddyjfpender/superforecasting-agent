# Browser provider integrations

Groups browser providers behind the shared browser extension interface.

## Ownership and boundaries

Track each allocated browser session through failed setup and disposal. Use shared hosting ownership instead of deleting arbitrary processes or borrowed endpoints.

## Subdirectories

- [browser_use/](browser_use/README.md) — browser_use integration.
- [browserbase/](browserbase/README.md) — browserbase integration.
- [firecrawl/](firecrawl/README.md) — firecrawl integration.

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
