# Shared tool infrastructure

Owns tool selection, definitions, argument handling, dispatch support, cancellation and shared Skills Hub HTTP operations.

## Ownership and boundaries

Tool implementations consume this package. Carry cancellation through worker I/O and check it before publication; keep tool catalogs separate from transport and presentation.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                               | Responsibility                                                          |
| ---------------------------------- | ----------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)         | Tool definition, argument, and dispatch support.                        |
| [runtime.py](runtime.py)           | Public orchestration API for tool discovery and dispatch.               |
| [arguments.py](arguments.py)       | Coerce model-produced arguments against registered tool schemas.        |
| [async_bridge.py](async_bridge.py) | Persistent event-loop ownership for synchronous tool dispatch.          |
| [background.py](background.py)     | Shared background inspection and stop operations over owned registries. |
| [definitions.py](definitions.py)   | Discover tools and build cached schemas for the active session.         |
| [dispatch.py](dispatch.py)         | Execute tool calls through registry, approvals, and plugin hooks.       |
| [errors.py](errors.py)             | Remove structural framing from tool error messages.                     |

## Subdirectories

- [catalogs/](catalogs/README.md) — Tool capability catalogs.

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/tooling/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)

## Progressive discovery

[disclosure.py](disclosure.py) builds a copied, session-scoped view of already
selected schemas. Core tools, forecast-prefixed tools and clarification remain
directly available. Optional tools are exposed through `tool_search`,
`tool_describe` and `tool_call`; discovery never loads a new tool or widens the
selection. Search uses BM25 ranking with thread-owned English stemmers and a
bounded catalog excerpt. Schemas and descriptions remain untrusted data.

The [agent adapter](../../agent/tool_discovery.py) applies this view before the
Chat Completions, Responses, Anthropic and Bedrock transports and routes calls
through normal tool owners and policy hooks. It validates an entire batch before
execution and rechecks selection before each effect. Native provider-owned
runtimes that do not expose the agent's selected tools retain their own catalog.

Configuration in `config.yaml`:

```yaml
tool_discovery:
  enabled: true
  direct_tools: []  # Additional selected tools to keep directly visible.
  listing_chars: 8000  # 0–24000; bounds the embedded optional-tool excerpt.
```

Settings are captured at agent construction; selection/schema changes on that
agent are checked at request and dispatch boundaries. Disabling discovery restores
eager schemas. `direct_tools` cannot enable an unselected tool. Batch execution is
sequential and reports completed results if cancellation or selection changes stop
the remainder. JSON Schema references resolve locally only; invalid or externally
referenced schemas cannot execute through the bridge.
