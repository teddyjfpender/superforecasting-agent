# Plugins tests

Exercises plugins behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                               | Responsibility                                                                          |
| ------------------------------------------------------------------ | --------------------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)                                         | init .                                                                                  |
| [test_achievements_plugin.py](test_achievements_plugin.py)         | Checks: achievements plugin.                                                            |
| [test_disk_cleanup_plugin.py](test_disk_cleanup_plugin.py)         | Tests for the disk-cleanup plugin.                                                      |
| [test_google_meet_audio.py](test_google_meet_audio.py)             | Tests for plugins.google_meet.audio_bridge (v2).                                        |
| [test_google_meet_node.py](test_google_meet_node.py)               | Tests for the google_meet node primitive.                                               |
| [test_google_meet_plugin.py](test_google_meet_plugin.py)           | Tests for the google_meet plugin.                                                       |
| [test_google_meet_realtime.py](test_google_meet_realtime.py)       | Tests for plugins.google_meet.realtime.openai_client (v2).                              |
| [test_kanban_dashboard_plugin.py](test_kanban_dashboard_plugin.py) | Tests for the Kanban dashboard plugin backend (plugins/kanban/dashboard/plugin_api.py). |

## Subdirectories

- [browser/](browser/README.md) — browser.
- [image_gen/](image_gen/README.md) — image gen.
- [memory/](memory/README.md) — memory.
- [model_providers/](model_providers/README.md) — model providers.
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
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
