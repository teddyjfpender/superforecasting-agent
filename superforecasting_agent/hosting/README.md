# Host and resource ownership

Owns hosted sessions, workers, background execution, browser lifetimes, delegation and coordinated shutdown.

## Ownership and boundaries

A resource remains owned until disposal succeeds. Retried cleanup must target the original allocation and never a replacement process, socket or session.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                           | Responsibility                                                                  |
| ---------------------------------------------- | ------------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)                     | Presentation-independent entrypoints for forecast runtime hosting.              |
| [runtime.py](runtime.py)                       | Presentation-independent serving lifetime and resource ownership.               |
| [configuration.py](configuration.py)           | Compatibility import for the host-owned shared configuration reader.            |
| [\_\_main\_\_.py](__main__.py)                     | Launch the headless host with credentials read from a file.                     |
| [aws_credentials.py](aws_credentials.py)       | AWS credential-source and region discovery, independent of client construction. |
| [background.py](background.py)                 | Session-owned background conversations and retryable resource disposal.         |
| [browser_connection.py](browser_connection.py) | Serialize browser endpoint changes and surface incomplete cleanup.              |
| [browser_processes.py](browser_processes.py)   | Record daemon identity at acquisition and require confirmed exit at disposal.   |

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
