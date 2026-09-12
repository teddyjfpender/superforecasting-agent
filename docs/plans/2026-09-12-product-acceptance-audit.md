# Product boundary acceptance audit

Scope: the five deliverables in the original repository architecture objective.
The initial audit and dated follow-ups below retain revision-specific evidence;
this is not completion of the whole migration.
Source revision: `de453c2072ac2bc16b721ccfb3e9f60119e3db74`.

| Deliverable | Current evidence | Remaining qualification or work |
| --- | --- | --- |
| Domain, application, infrastructure, transport and product ownership | Shared forecast/session application packages; ownership map; 61 import contracts, with injected forbidden-edge tests. Source dispatch and panel rules have transitive execution/presentation prohibitions. | Fourteen direct forecast-to-tool exceptions remain. Scheduled and batch refresh still import the forecasting tool solely for watched-source acquisition. Quorum provider discovery retains a runtime exception. |
| TUI first consumer of shared services, with CLI parity | Real Ink review/resolution/scoring and recovery checks passed. Native command inventory is enforced across the backend and Ink. The classic slash worker is deleted; host construction uses shared agent factories. | Complete the remaining legacy adapter extractions without changing validation or provenance. Live snapshot restoration still requires host-wide writer quiescence. |
| Reliable development gates | `scripts/dev.py` owns bootstrap/check; hooks and Product quality CI invoke it. Hooks are installed. Strict lint, formatting and types cover extracted owners; import and generated-contract checks block failures. | Strict coverage remains incremental outside extracted owners. Fresh bootstrap was previously verified; this audit inspected the same entrypoint and CI wiring but did not repeat bootstrap on every platform. |
| Presentation-independent runtime host | Configuration/session owner, shutdown, authenticated headless WebSocket and real-desk tests passed (77 tests total across the selected acceptance files). Installed local and remote terminal negotiation and clean host shutdown passed. | Lower-level browser PID identity and confirmed termination remain open. Snapshot restore admission and longer remote recovery qualification remain open. |
| Independent product profiles | Fresh backend, terminal, combined and optional web installations passed outside the checkout. Backend create/update/resolve/score, durable worker execution and numerical fallback passed without Node. Installed terminal scored against both local and remote hosts. | This run qualifies macOS arm64/Python 3.13.12. It does not establish native Windows/Termux behavior or a published release. |

## Retained artifact identity

Built with `scripts/build_profiles.py`; verified with `scripts/verify_profiles.py`.
Artifacts were written to `/tmp/forecast-boundary-audit-wheels`.

- Backend `superforecasting_agent-0.22.0-py3-none-any.whl`:
  `dd1a6a4575deff6e1606e25304615b234b3e343dc6bdb41bfada6e517db5f7aa`
- Terminal `superforecasting_agent_tui-0.1.0-py3-none-any.whl`:
  `6a60e2328b6161b9cecdaf2a899a3a1496933e4ff0c80d9f2c9d4b7cd1484a76`

The installed checks exercise real packaged entrypoints, a durable forecast,
headless authentication and protocol negotiation. They use isolated profiles and
local providers; they do not claim live credential-dependent integration coverage.

Local verification logs: `/tmp/forecast-boundary-audit-build.log`,
`/tmp/forecast-boundary-audit-install.log`, and
`/tmp/forecast-boundary-audit-runtime-tests.log`. The selected runtime tests cover
real desktop lifecycle, host shutdown ownership, headless transport, profile
configuration ownership and injected forbidden imports. Fifteen PTY-related
warnings were reported; passing these tests does not resolve historical native
SSL or late bad-file-descriptor incidents.


## Subsequent ownership work

At source revision `cd6c7f62b`, the shared quality gate enforces 66 import
contracts, all passing. Watched-source acquisition, question reuse, market output
transfer, approval callbacks, Slack transport, card sharing, model building and
triage now have shared owners. The direct forecast-to-tool ratchet has one
remaining exception: supervisor web search. Quorum provider discovery still has
its separate runtime exception. CLI model building and triage no longer invoke
the registered forecast tool.

Failure injection during these extractions also fixed partial model links,
divergent triage label/alert writes and invalid expert-label persistence. Focused
model checks (56) and the final triage/evidence checks (86) passed. These source
checks supplement the earlier installed-product evidence; the wheel identities
above still refer to their original source revision, not these later commits.


## Storage and search follow-up

The shared gate now enforces 72 import contracts. The direct forecasting-to-tools
contract has no exceptions: supervisor search uses shared provider dispatch,
validation and cooperative cancellation. Provider identity and offline model
catalogs also have independent owners. The remaining forecasting runtime
exception is credential-status discovery, whose OAuth refresh behavior still
needs explicit service ownership.

Revision `e6dbb1873` passed the full push gate: 31,873 Python tests passed,
148 skipped, with 66 warnings. The remote branch was verified at that revision.
Subsequent focused storage fixes at `c46588097` and `6cf5435a0` make global auth
fallback non-writing and bind lock reentrancy to process and resource identity.
Their focused checks and shared quality gates passed; final integrated push
validation is recorded in the corresponding push log rather than assumed here.

These source-level checks do not replace installed-profile qualification. The
artifact hashes and platform limits above still belong to the original build.
Historical SSL attribution, live restore coordination, credential discovery
ownership, and further cross-platform recovery remain open in `TODO.md`.
