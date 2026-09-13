# Web evidence providers

Groups web-search providers registered through the web plugin interface.

## Ownership and boundaries

Return source identity and timestamps honestly. Search snippets and successful requests do not establish canonical settlement evidence.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility |
| -------------------------- | -------------- |
| [\_\_init\_\_.py](__init__.py) | init .         |

## Subdirectories

- [brave_free/](brave_free/README.md) — brave_free integration.
- [ddgs/](ddgs/README.md) — ddgs integration.
- [exa/](exa/README.md) — exa integration.
- [firecrawl/](firecrawl/README.md) — firecrawl integration.
- [parallel/](parallel/README.md) — parallel integration.
- [searxng/](searxng/README.md) — searxng integration.
- [tavily/](tavily/README.md) — tavily integration.
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
