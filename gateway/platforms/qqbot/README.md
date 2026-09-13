# QQ bot transport

Contains the QQ adapter with onboarding, message keyboards, upload handling, cryptography and protocol constants.

## Ownership and boundaries

Preserve the platform identity and upload lifecycle across retries. Keep generic session and forecasting policy out of this transport package.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                   | Responsibility                                                                   |
| -------------------------------------- | -------------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)             | QQBot platform package.                                                          |
| [adapter.py](adapter.py)               | QQ Bot platform adapter using the Official QQ Bot API (v2).                      |
| [chunked_upload.py](chunked_upload.py) | QQ Bot chunked upload flow.                                                      |
| [constants.py](constants.py)           | QQBot package-level constants shared across adapter, onboard, and other modules. |
| [crypto.py](crypto.py)                 | AES-256-GCM utilities for QQBot scan-to-configure credential decryption.         |
| [keyboards.py](keyboards.py)           | QQ Bot inline keyboards + approval / update-prompt senders.                      |
| [onboard.py](onboard.py)               | QQBot scan-to-configure (QR code onboard) module.                                |
| [utils.py](utils.py)                   | QQBot shared utilities — User-Agent, HTTP helpers, config coercion.              |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/gateway/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
