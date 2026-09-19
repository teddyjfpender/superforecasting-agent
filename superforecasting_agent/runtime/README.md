# Product runtime adapters

Contains command-line setup, authentication interaction, installation, plugins, dashboard hosting and other product orchestration.

## Ownership and boundaries

Move reusable validation and state operations to application, configuration, credentials or storage owners. This package may compose those services but must not become their dependency.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                            | Responsibility                                                            |
| ----------------------------------------------- | ------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)                      | Superforecasting Agent CLI - unified command-line interface.              |
| [models.py](models.py)                          | Canonical model catalogs and lightweight validation helpers.              |
| [\_parser.py](_parser.py)                       | Top-level argparse construction for the Superforecasting Agent CLI.       |
| [\_subprocess_compat.py](_subprocess_compat.py) | Windows subprocess compatibility helpers.                                 |
| [anthropic_setup.py](anthropic_setup.py)        | Interactive Anthropic provider setup and credential selection.            |
| [api_key_setup.py](api_key_setup.py)            | Shared API-key entry and provider model setup.                            |
| [assistant_text.py](assistant_text.py)          | Normalize visible assistant content for the CLI transcript and clipboard. |
| [audit_discovery.py](audit_discovery.py)        | Discover pinned audit components from the environment, plugins, and MCP.  |

## Parser composition

`main.py::build_runtime_parser(include_plugins=False)` constructs the built-in
argparse tree without startup cleanup, argument parsing or command execution.
The executable entrypoint opts into plugin registration when needed. Metadata
consumers must leave plugin discovery disabled: registration can execute external
code and depends on the active profile.

The [generated runtime inventory](../../docs/reference/runtime-commands.md)
uses this same builder. Public routing in `../cli.py` precedes runtime dispatch,
so forecast shorthand and TUI fast paths are documented separately. Parser
callbacks are composition adapters; shared validation and persistence belong in
application owners.

## Subdirectories

- [proxy/](proxy/README.md) — Provider proxy runtime.

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/runtime_cli/test_parser_construction.py tests/runtime_cli/test_plugin_cli_registration.py -q
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The pre-push hook runs the bounded integration tier; use focused tests for
changed behavior and the qualification tier only when explicitly required.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)

Diagnostic capture and upload remain in [debug.py](debug.py). Messaging uses
[diagnostic_service.py](diagnostic_service.py) for summary-only sharing; all
sharing paths attach installed versions and sanitize the composed payload through
the shared [application policy](../application/diagnostics.py).

## Data desk

`data_desk.py` is the thin `data` command and setup adapter. It delegates selection and credentials to the DataDesk application owner. Setup offers a global starter or intentional empty desk and supports preview/customization.
