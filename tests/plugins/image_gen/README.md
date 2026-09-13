# Plugins / Image Gen tests

Exercises plugins/image gen behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                           | Responsibility                                                            |
| -------------------------------------------------------------- | ------------------------------------------------------------------------- |
| [**init**.py](__init__.py)                                     | init .                                                                    |
| [test_openai_codex_provider.py](test_openai_codex_provider.py) | Tests for the bundled `openai-codex` image_gen plugin.                    |
| [test_openai_provider.py](test_openai_provider.py)             | Tests for the bundled OpenAI image_gen plugin (gpt-image-2, three tiers). |
| [test_xai_provider.py](test_xai_provider.py)                   | Tests for xAI image generation provider.                                  |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/plugins/image_gen/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
