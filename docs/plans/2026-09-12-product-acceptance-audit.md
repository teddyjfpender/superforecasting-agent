# Product boundary acceptance audit

Scope: the five deliverables in the original repository architecture objective.
Implementation and installed artifacts audited at source revision
`bbe02caae45e2fee7507530148635139a75974f5`. This replaces earlier snapshots of
this audit; their evidence remains in Git history and the architecture work log.
The first full-suite push was blocked by six stale test-owner references
(31,955 passed, 148 skipped). The closeout corrects those references without
changing production code. The final push must pass the same full-suite gate;
its result is recorded in `/tmp/forecast-product-closeout-push.log`.

## Requirement-by-requirement evidence

| Deliverable | Implementation and enforcement | Verification |
| --- | --- | --- |
| Domain, application, infrastructure, transport and product ownership | `forecasting/application` owns forecast operations; `superforecasting_agent/application` owns shared command/session operations; configuration, credentials, storage and hosting have separate packages. `protocol` owns transport declarations. The ownership map identifies owners and forbidden dependencies. | Fresh bootstrap passes all 76 import contracts. Application services have transitive presentation prohibitions. Direct forecasting-to-tools and forecasting-to-runtime exception lists are empty. Injected forbidden-edge tests prove contracts reject violations, including the new credential service boundary. |
| TUI first consumer of shared services, CLI parity | TUI forecast RPC and CLI review/resolution consume the same application operations. Shared command catalog, validation, configuration and session operations serve native TUI and CLI consumers. Native command ownership is checked against the Ink catalog. The classic slash worker and its subprocess entrypoint are deleted; the entire TUI gateway cannot import classic CLI presentation. | Configured-command and host-ownership regression suites exercise shared validation, admission, cancellation and session identity. Installed real Ink clients complete forecast scoring through both local and authenticated remote hosts. The verifier checks durable ledger results, not only rendered success text. |
| Reliable development gates | `python3 scripts/dev.py bootstrap` creates the contributor environment, installs Git hooks and runs shared checks. `check` runs correctness lint, scoped strict lint/format/types, import contracts, generated protocol checks and TUI lint/types. Pre-commit and pre-push invoke the shared implementation; every push runs the full Python suite. Product quality CI invokes the same bootstrap/build/verification commands. | Bootstrap passed from a fresh worktree, including hook installation, all 76 contracts and TUI checks. Strict checks include complete configuration, storage, hosting, application and credential directories; inherited code outside the strict scope remains incrementally covered. CI wiring was inspected; hosted CI was not monitored. |
| Presentation-independent runtime host | `RuntimeHost` owns worker and command admission, session registry/store, configuration, sign-in lifetime, restart and shutdown. Credential discovery/refresh/persistence is independent of interactive login. Versioned protocol and capability negotiation serve local stdio and authenticated headless WebSocket transports. | Host tests exercise failed stop/restart, retained cleanup handles, durable turn finalization failures and session ownership. Installed local/remote terminal negotiation, unauthorized-host rejection, scoring and clean exit passed. Profile leases exclude restore/import during active managed use, retain admission on failed shutdown, and allow crash recovery; focused restore/finalization regression tests passed. |
| Independently testable distributions | Backend/CLI and terminal ship as separate wheels. Backend has no bundled TUI assets or Node requirement. Terminal can install independently; combined installs discover it. Web hosting remains an optional integration. | Fresh backend, terminal, combined and optional-web environments passed outside the checkout on Python 3.11.15 and 3.13.12. Backend lifecycle, durable worker and numerical fallback ran without Node. Both runs upgraded retained 0.21.2 data to 0.22.0 while preserving question/history/evidence/session/configuration. |

## Reproduction and retained artifacts

From a fresh checkout:

```sh
python3 scripts/dev.py bootstrap
python3 scripts/build_profiles.py --profile all --out /tmp/forecast-final-boundary-wheels
python3 scripts/verify_profiles.py /tmp/forecast-final-boundary-wheels --python 3.11.15 --upgrade-from /path/to/superforecasting_agent-0.21.2-py3-none-any.whl
python3 scripts/verify_profiles.py /tmp/forecast-final-boundary-wheels --python 3.13.12 --upgrade-from /path/to/superforecasting_agent-0.21.2-py3-none-any.whl
```

Local artifacts: `/tmp/forecast-final-boundary-wheels`, built from the source
revision above. The backend wheel was built through its source distribution.

| Artifact | SHA-256 |
| --- | --- |
| `superforecasting_agent-0.22.0-py3-none-any.whl` | `505ae53a78824f81991593108ac12a9a998d178df471e5694d521755bf5f3a7a` |
| `superforecasting_agent-0.22.0.tar.gz` | `579a5ecceafd5d7c7b78bb3a8fa43bbb7533caa8ec150f5c766bdeacfefd5a2a` |
| `superforecasting_agent_tui-0.1.0-py3-none-any.whl` | `074dd752498d50e83e762d424ef27dbf26faffd44be51e801de8b16c2df0123d` |
| Retained `superforecasting_agent-0.21.2-py3-none-any.whl` | `09c3ec93d5dec5e26353922c2162f50d5702e4c5264a846643470c9fa4abfaca` |

Local verification logs:

- `/tmp/forecast-final-bootstrap.log`
- `/tmp/forecast-final-profile-build.log`
- `/tmp/forecast-final-profile-python311.log`
- `/tmp/forecast-final-profile-python313.log`
- `/tmp/forecast-credential-negative-boundary.log`
- `/tmp/forecast-credential-owner-verified-push.log`

The negative credential-boundary test passed after the artifact build; it changes
only the regression test matrix, not artifact implementation. Other focused
credential checks passed 2,533 tests with two skips; profile-finalization checks
passed 287 tests. These supplement rather than replace the full-suite push gate.

## Evidence limits and subsequent work

Installed verification is macOS arm64, with isolated profiles and controllable
local providers. It proves packaged local/headless-host behavior and authentication,
not native Linux, Windows or Android/Termux qualification. It is not package
publication or verification of live third-party credentials. The independent
terminal package is still 0.1.0, so successor-terminal upgrades remain future work.

Historical native SSL attribution, longer remote recovery sessions, lower-level
SDK/browser cleanup qualification and broader inherited strict-check coverage
remain explicit follow-ups in `TODO.md`. They do not change the original
architecture acceptance criteria into a requirement to complete every inherited
runtime cleanup or operate live forecasting cohorts. Existing compatibility
aliases are retained, with fork-native owners and product entrypoints.
