# Skills tests

Exercises skills behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                                                   | Responsibility                                                                     |
| -------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| [test_darwinian_evolver_skill.py](test_darwinian_evolver_skill.py)                     | Smoke tests for the darwinian-evolver optional skill.                              |
| [test_fetch_transcript.py](test_fetch_transcript.py)                                   | Tests for skills/media/youtube-content/scripts/fetch_transcript.py (issue #22243). |
| [test_google_oauth_setup.py](test_google_oauth_setup.py)                               | Regression tests for Google Workspace OAuth setup.                                 |
| [test_google_workspace_api.py](test_google_workspace_api.py)                           | Tests for Google Workspace gws bridge and CLI wrapper.                             |
| [test_google_workspace_credential_files.py](test_google_workspace_credential_files.py) | Regression test: google-workspace SKILL.md must declare required_credential_files. |
| [test_grounded_citations_skill.py](test_grounded_citations_skill.py)                   | Tests for the grounded-citations bundled skill.                                    |
| [test_hyperliquid_skill.py](test_hyperliquid_skill.py)                                 | Checks: hyperliquid skill.                                                         |
| [test_memento_cards.py](test_memento_cards.py)                                         | Tests for optional-skills/productivity/memento-flashcards/scripts/memento_cards.py |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/skills/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
