# firecrawl integration

Implements the firecrawl plugin. Firecrawl web search + content extraction. Supports direct API and Nous-hosted tool-gateway routing for subscribers. Requires FIRECRAWL_API_KEY (or FIRECRAWL_API_URL for self-hosted), or an active Nous subscription with FIRECRAWL_GATEWAY_URL.

## Ownership and boundaries

Register capabilities through the plugin interface. Keep optional dependencies optional and preserve active-profile isolation. Core runtime must not contain branches specific to this plugin.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility                                                |
| -------------------------- | ------------------------------------------------------------- |
| [**init**.py](__init__.py) | Firecrawl web search + extract plugin — bundled, auto-loaded. |
| [plugin.yaml](plugin.yaml) | plugin.                                                       |
| [provider.py](provider.py) | Firecrawl web search + extract — plugin form.                 |

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
