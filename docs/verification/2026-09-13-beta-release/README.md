# Beta release verification

## Scope and owners

Backend candidate 0.22.4 and terminal 0.1.1 are published together through
`production-release.yml`. Tag-triggered runs default to beta; stable publication
requires an explicit `channel=stable` dispatch. Beta releases never advance
GitHub or container `latest` aliases. Publication waits for six native jobs to
verify checksummed draft downloads, fresh installations, historical upgrades,
profile/skill/plugin migrations and terminal recovery.

## Dependency remediation

The 28 previously open alerts affected these lockfiles. All four now report zero
npm audit vulnerabilities; counts describe registry audit coverage, not a security
proof or live qualification of optional integrations.

| Owner | Exposure | Remediation |
| --- | --- | --- |
| `ui-tui` | Development dependencies (ESLint YAML parsing, Vitest/mocker and filesystem tooling); not the bundled runtime dependency graph | Compatible lockfile updates |
| `web` | Dashboard dependency graph, including HTML sanitization and color parsing; YAML is build tooling | Compatible lockfile updates |
| `website` | Documentation build/dev server dependencies, including SVG processing, YAML, URI parsing, browser queries and request parsing | Compatible updates and `qs` 6.16.0 override for Express's older transitive pin |
| `scripts/whatsapp-bridge` | Optional runtime, including native image processing and Express request parsing | Compatible updates and the same patched `qs` override |

Run `npm audit` from each directory to reproduce the registry check. The bridge
remains outside supported beta scope; dependency remediation does not qualify a
live messaging integration.

## CI diagnosis

- Bedrock tests imported an SDK absent from the full-test dependency group; the
  group now includes the bounded SDK pin already used by the Bedrock extra.
- The Copilot removal test patched a compatibility module after production code
  moved to the canonical credential owner. Its resolver is now patched where used.
- CI bypassed the canonical test runner and omitted terminal dependencies. Shared
  isolation, bounded workers and current TUI builds now apply in CI as locally.
- The artifact-build job installs its pinned process-ownership harness dependency
  explicitly; dependencies in other jobs or installed product environments do not
  populate the verification driver's interpreter.
- Windows checks flagged intentionally Linux-only TLS cleanup and guarded alarm
  access. The Linux restriction is explicit; optional signal lookup is portable.
- Nix built the package but failed its version-content check. Capture complete
  output before matching to avoid early-reader pipe termination and expose actual
  errors. Nix remains experimental for this beta; dependency updates also require
  refreshed Nix fixed-output hashes before a new Nix qualification claim.

## Release evidence

Publication receipts and final artifact checksums will be linked here after the
formal workflow completes. Existing candidate artifacts are not release evidence.

## Linux qualification follow-up

The first formal run exposed 30-second calibration timeouts, a 240-second
portfolio-export timeout and a gateway surviving client death. Read transactions
and question-scoped score queries remove repeated connection setup and whole-ledger
scans; synthetic calibration fixtures now use one batch transaction. Shutdown
deadlines cover broken-output/dispatch exits and precede potentially blocking cleanup.

The native cancellation test also now waits for command completion rather than
the earlier streamed `(stopped)` preview. A store regression verifies that output
text cannot clear cancellation before the backend's terminal acknowledgement.

The [evaluation identity review](evaluation-review.json) records the exact
changed functions. Scoring formulas, outcome validation, frozen adjustments and
trial evaluation remain AST-identical. The explicit compatibility registry admits
only reviewed identities; existing trial records are not rewritten.

The `v0.22.1` tag remains unpublished after qualification failures. The `v0.22.2`
run was cancelled in favor of the Linux fixes; neither tag is moved or reused.

## Additional qualification findings

The first v0.22.3 formal attempt received HTTP 403 while the Windows check fetched
public GitHub release metadata, before downloading or validating a wheel. The
controlled installer fixtures passed. CI now supplies its read-only token to the
metadata cmdlet; artifact downloads use a separate cmdlet without that header.
The HTTP response alone does not establish whether the original rejection was a
shared-runner rate limit.

The same run exceeded the generic 30-second test deadline during pure-Python
five-fold calibration validation. These three full-grid statistical experiments
now have explicit 120-second budgets. Their datasets, folds, fitted models and
numerical assertions are unchanged; no production scoring code changed.

## Browser shutdown follow-up

The bounded v0.22.3 retry again exceeded the calibration deadline and exposed
an unclosed browser WebSocket transport plus a slow full-clone gate fixture.
The tag remains unpublished and unchanged; 0.22.4 includes the follow-up fixes.

A deterministic regression reproduced the owner returning while its socket close
was still pending. `stop()` had removed the reference needed by the connection's
finally block, allowing loop teardown to cancel unfinished closure. The reference
now remains available until the owner also awaits closure. A second regression
verifies that a socket returned after a stop request is closed without attaching
a page. These tests establish the ownership defect; the original CI warning did
not include a complete allocation traceback.

The dirty-tree regression now uses a small committed Git fixture with successful
codegen stubs, asserting that its one untracked file alone causes rejection. The
separate protocol/docgen integration and missing-toolchain tests remain intact.

Local follow-up verification passed 21 real-Chrome supervisor tests; one existing
OOPIF case remains explicitly skipped. All eight deterministic supervisor ownership
tests passed, as did the focused release, calibration and trial-compatibility checks.

Tag-position fixtures retain the full Git history through sparse local clones,
checking out only their gate/version inputs. This removes unrelated source/skill
checkout work without changing the tag ancestry and mismatch assertions.
