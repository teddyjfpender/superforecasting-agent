# tavily integration

Implements the tavily plugin. Tavily web search + content extraction + crawl. Search + extract are mainstream; crawl is unique to Tavily among built-in providers. Requires TAVILY_API_KEY — sign up at https://app.tavily.com/home.

## Ownership and boundaries

Register capabilities through the plugin interface. Keep optional dependencies optional and preserve active-profile isolation. Core runtime must not contain branches specific to this plugin.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility                                                     |
| -------------------------- | ------------------------------------------------------------------ |
| [**init**.py](__init__.py) | Tavily web search + extract + crawl plugin — bundled, auto-loaded. |
| [plugin.yaml](plugin.yaml) | plugin.                                                            |
| [provider.py](provider.py) | Tavily web search + content extraction + crawl — plugin form.      |

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
[ownership map](../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
