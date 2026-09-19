# Host and resource ownership

Owns hosted sessions, workers, background execution, browser lifetimes, delegation and coordinated shutdown.

## Ownership and boundaries

A resource remains owned until disposal succeeds. Retried cleanup must target the original allocation and never a replacement process, socket or session.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                           | Responsibility                                                   |
| ---------------------------------------------- | ---------------------------------------------------------------- |
| [runtime.py](runtime.py)                       | Shared host admission, sessions and active command ownership.    |
| [sessions.py](sessions.py)                     | Hosted session lifecycle operations.                             |
| [background.py](background.py)                 | Background execution state and work ownership.                   |
| [delegations.py](delegations.py)               | Delegated execution and parent/child relationships.              |
| [browser_sessions.py](browser_sessions.py)     | Browser allocation lifetime and disposal.                        |
| [browser_processes.py](browser_processes.py)   | Daemon identity, PID reuse safeguards and confirmed termination. |
| [browser_connection.py](browser_connection.py) | Browser endpoint connection ownership.                           |

## POSIX terminal startup

`pty_spawn.spawn_pty` owns allocation through confirmed executable startup. It uses
`posix_spawn` with a new session and an isolated Python helper (`pty_exec.py`), so
application threads and Python locks are not copied into a fork child. The helper
acquires the controlling terminal and closes unrelated inherited descriptors before
exec. Native spawn restores terminal signal defaults and clears the child signal mask;
ignored daemon signals cannot disable Ctrl+C or job control in the TUI. Parent signal
settings remain unchanged. A bounded error pipe preserves ordinary executable/cwd errors. Failure closes
allocations and reaps the direct child; success transfers its PID/master descriptor
to the dashboard's existing PTY process owner. No unsafe fork fallback is used.

This path requires POSIX `posix_spawn(setsid=True)`, `/dev/fd`, and controlling-terminal
ioctls. Native Windows continues to use its existing unavailable/WSL behavior.
Tests live in `tests/hosting/test_pty_spawn.py` and `tests/runtime_cli/test_pty_bridge.py`.
This change does not identify the historical SSL or bad-file-descriptor crash causes.

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/hosting/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
