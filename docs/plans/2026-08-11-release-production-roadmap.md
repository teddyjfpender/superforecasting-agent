# Release production roadmap

**Date:** 2026-08-11
**Scope:** artifact quality, nightly verification, supported releases, and the
highest-value upstream ports. Hosting remains covered by
[`2026-07-09-hetzner-productionization.md`](2026-07-09-hetzner-productionization.md).

## Decision

Build a release candidate every night; do not publish a release every night.
Nightly publication would create noisy versions without adding evidence of
quality. A stable `vX.Y.Z` is published only after the same artifact set passes
the tag gate and an operator verifies the emitted assets.

The release states are:

| State | Trigger | Output | Mutates public state |
|---|---|---|---|
| Pull request | code change | Python, E2E, TUI gates | no |
| Nightly candidate | `02:17 UTC` schedule | clean-built formal artifact set, retained 7 days | no |
| Release candidate | strict SemVer tag | wheel, sdist, installer, checksums, manifest, multi-arch image | yes |
| Verified production | operator post-release checks | supported release | no additional mutation |

Scheduled verification must never change active forecast probabilities. It may
only test code and produce disposable artifacts.

## Verified baseline

The baseline was inspected in the live checkout on 2026-08-11:

- Fork branch: `feat/tui-productionization` at `9e69631f2b97` before this work.
- Fork point with upstream: `edb2d910577b` (2026-05-20).
- Current fetched upstream: `origin/main` at `a31be48030f6`; divergence was
  1,305 fork-only / 12,640 upstream-only commits. A wholesale merge is not a
  production strategy.
- Current package version: `0.20.0`; supported Python is now explicitly
  `>=3.11,<3.14`, matching the upstream compatibility fix in `475ecea3e0`.
- The tag workflow already defines a formal artifact set: wheel, sdist,
  `install.sh`, `SHA256SUMS`, `release-manifest.json`, and a multi-architecture
  GHCR image.
- The release workflow used mutable action tags and excluded two tests. This
  branch pins every GitHub Action by commit, removes both exclusions, and fixes
  the remaining snapshot N+1 defect.

## Implemented in this branch

1. **Nightly release candidate.** `.github/workflows/tests.yml` runs all normal
   Python, E2E, and TUI gates, then performs lockfile, protocol, and generated-doc
   checks; builds the TUI, dashboard, wheel, and sdist from clean dependency
   installs; verifies `SHA256SUMS`; installs the emitted wheel in a fresh venv;
   and uploads the artifact set for seven days.
2. **Immutable CI dependencies.** All action references are 40-character commit
   SHAs. A focused test scans every workflow so mutable tags cannot return.
3. **Supported-runtime boundary.** Python 3.14 is refused until it is explicitly
   qualified. `uv.lock` is regenerated against the declared package version,
   and package license metadata uses the upstream PEP 639 form (`e223503b03`).
4. **Release gate parity.** The tag pipeline no longer hides the forecast
   domain-profile test or the hook-preview snapshot test; E2E and a focused
   Python 3.13 compatibility suite now run inside the tag workflow.
5. **Evidence quality port.** Upstream's `grounded-citations` skill is ported
   from the v0.20.0 line (`43c79cd84a`, `4660673a3c`, `a6defd4f15`) and adapted
   to `~/.superforecasting-agent`. It provides stable source numbering,
   draft/source consistency checks, citation coverage, and verbatim evidence
   verification without a new dependency.
6. **Forecast Desk simplification.** The persistent Home conversations rail is
   deleted. `/resume` is the single session-selection surface and supports
   arrows, scrolling, `j/k`, and page jumps.
7. **Reproducible skill packaging.** The wheel data-file collector now excludes
   `__pycache__`, `.pyc`, and `.pyo` files even when a local test run created
   them before the build; the sdist and wheel are both archive-audited.
8. **Bounded SQLite resources.** Forecast-ledger context managers now close
   owned connections; API-server disconnect closes both durable stores; and
   gateway tests close per-test stores. The 30k-test xdist run no longer starves
   later PTY and forecast-ledger checks of file descriptors.
9. **Single, atomic publisher.** Local release helpers are dry-run only and the
   legacy workflow is deleted. The formal workflow smoke-tests an amd64 image,
   signs the Python distributions, publishes only the immutable tag, verifies
   draft assets and image digest, publishes the draft, then advances `latest`.
10. **Proposal-only automation.** Scheduled reviews and background source
    estimators persist evidence and reviewable proposals without changing the
    active forecast. Explicit approval remains the probability commit boundary.

## Release contract

A tag is releasable only when all of these are green:

- Tag is strict `vX.Y.Z`, equals `pyproject.toml`, points at the release commit,
  and has a non-empty changelog entry.
- `uv lock --check`, protocol codegen, generated docs, the hermetic Python suite,
  E2E suite, TUI typecheck/tests/lint, and artifact smoke installation pass.
- Wheel and sdist include the built Ink TUI, web dashboard, install scripts, and
  plugin/skill package data.
- `SHA256SUMS` validates and `release-manifest.json` validates against its schema.
- An amd64 image passes the shared container smoke before the GHCR image is
  built for `linux/amd64` and `linux/arm64`; its manifest digest is recorded in
  the release manifest. The draft assets and immutable image verify before the
  GitHub Release is published or `latest` moves.
- No required job is skipped and no test is deselected in the release workflow.
- The release commit is reachable from the repository's current default branch,
  and the native Windows installer parses and checksum-verifies a published
  asset set before the release publisher may run.

After publication, the operator verifies the remote tag SHA, successful workflow
run, exact release-asset names, checksums, manifest image digest, both image
platforms, and one clean installer launch. A failed check means the release is
not production even if GitHub labels it “Latest”; publish a corrected patch
release rather than replacing a signed/tagged artifact in place.

## Branch verification

Completed on 2026-08-11 against this branch:

- Hermetic Python suite: 29,778 passed, 155 skipped.
- Forecasting slice: 3,207 passed, 2 skipped.
- E2E: 56 passed, 7 skipped.
- Ink TUI: 2,007 passed, 4 skipped; typecheck and build passed; lint held the
  existing 54-warning ratchet with zero errors.
- Strict readiness, lockfile, generated docs/protocol, workflow lint, and
  release-gate tests passed.
- A fresh formal artifact set passed checksums, manifest validation, wheel and
  sdist cache-file audits, Python 3.11 installation, and CLI startup.

## Critical path

### P0 — land this branch

- Run the full Python and TUI suites, actionlint, strict readiness gate, and local
  formal-artifact dry run.
- Review the generated lockfile diff and the release workflow diff.
- Merge only if the required checks actually run; a green skipped check is not a
  release signal.

### P1 — make the nightly operational

- Confirm the first scheduled run on the default branch and download its
  artifacts.
- Compare nightly file names and manifest roles with the tag workflow.
- Add GitHub branch protection requiring Python, E2E, and TUI jobs.
- Add a macOS clean-wheel smoke job only when a release candidate exposes a
  platform-specific failure; the wheel itself is platform-independent today.

### P2 — close runtime reliability gaps

Port upstream changes as isolated contracts, never as a bulk merge:

| Priority | Upstream candidate | Forecasting value | Admission test |
|---|---|---|---|
| P0, ported | grounded citations + fact checking | evidence provenance and auditability | skill test suite, no invented ids, evidence quotes match source text |
| P0, next | `1e8339a48c` preserve live tail during compression | prevents loss of the latest forecast update in long desks | concurrent compression regression with byte-stable live tail |
| P0, next | `63954d508c` recover dropped tool calls | prevents silent incomplete research/update turns | provider fixture with `finish_reason=tool_calls` and empty calls |
| P1 | `3829e34e23` signed outbound lifecycle webhooks | safe automation for alerts, scores, and postmortems | HMAC verification, replay/timestamp failure, secret redaction |
| P1 | `2d16ec7fb7` SecretSource interface and follow-up fixes | safer unattended credentials | no secret persistence/logging; explicit provider enablement |
| P2 | selected compression pool and session-lineage fixes | long-session durability | port only after mapping each invariant to this fork's compression code |

Voice, wake words, desktop installers, A2A orchestration, and general-assistant
surface expansion are deferred. They are real upstream features, but none
improves evidence quality, probability estimation, calibration, or release
reliability enough to outrank the table above.

## Quality budget

The next quality work is deliberately bounded:

1. Reduce the TUI lint warning ratchet from 54 as warnings are touched; do not
   perform a cosmetic rewrite solely to reach zero.
2. Ratchet the Python suite's 48 warnings to zero, starting with unawaited
   mocks and teardown logging after output capture closes.
3. Split large modules only behind unchanged behavior and measured ownership
   boundaries. File size alone is not a defect.
4. Promote only release-path checks with a demonstrated failure mode. The
   nightly reuses existing scripts instead of growing a second release system.
5. Re-run an upstream spot audit monthly and before editing agent compression,
   gateway security, provider recovery, or installation code.

## Production exit criteria

The project is release-ready when three consecutive nightly candidates pass,
the tag pipeline passes without exclusions, a clean install starts the Forecast
Desk, the remote assets and image digest match the manifest, and rollback to the
previous patch release is rehearsed. “Builds locally” is not an exit criterion.
