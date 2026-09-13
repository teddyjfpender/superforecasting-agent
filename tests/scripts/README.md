# Scripts tests

Exercises scripts behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                                       | Responsibility                                                                 |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| [test_contributor_audit.py](test_contributor_audit.py)                     | Regression tests for fork-native contributor audit defaults.                   |
| [test_dev_workflow.py](test_dev_workflow.py)                               | The contributor command must fail closed before claiming a clean checkout.     |
| [test_docgen_native_env.py](test_docgen_native_env.py)                     | Environment reference follows the native package beyond runtime/.              |
| [test_generate_skill_docs_links.py](test_generate_skill_docs_links.py)     | Link-rewriting contract of website/scripts/generate-skill-docs.py.             |
| [test_import_boundary_enforcement.py](test_import_boundary_enforcement.py) | Inject forbidden imports to prove the shipped ownership gates reject them.     |
| [test_install_release_verify.py](test_install_release_verify.py)           | Integrity-verification contract of scripts/install-release.sh.                 |
| [test_install_verify_consistency.py](test_install_verify_consistency.py)   | Verification posture of scripts/upgrade.sh + scripts/hetzner-install.sh.       |
| [test_live_service_runner.py](test_live_service_runner.py)                 | The canonical runner must actually admit only explicitly selected live suites. |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/scripts/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
