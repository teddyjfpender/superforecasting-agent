# Product repository cleanup

## Objective and completion criteria

Consolidate this fork into a modular, DRY, shippable Superforecasting Agent
repository while preserving the current Forecast Desk TUI. The requested work
window is 12 hours; the work is incomplete until the whole scope is verified.

- Move the active runtime into a coherent product package and retire inherited
  module/file names. Verify imports, installed wheels, CLI, profiles, and jobs.
- Remove obsolete inherited assets and redundant implementations after tracing
  their consumers. Preserve required license and contributor attribution.
- Organize root files and documentation; keep setup and README instructions
  consistent with the supported installation and launch paths.
- Preserve TUI input, navigation, rendering, sessions, streaming, approvals,
  forecast workflows, and dashboard PTY integration. Verify tests and live launches.
- Run architecture contracts, protocol/doc generation checks, relevant tests,
  full release checks, and packaging validation before claiming shippability.

## Initial evidence

Started from clean worktree at `b0a15ea05`. No prior cleanup process was identified.
The existing July modularization plan documents earlier boundaries, but the new
request explicitly includes inherited modules and removal of Hermes naming.
The current implementation remains the authority when choosing migration seams.

Local environments were absent. Installed the TUI locked dependencies with
`npm ci --ignore-scripts --no-audit --no-fund` and Python dependencies with
`uv sync --locked --extra dev --extra pty --extra web`.

## Slice 1: TUI renderer identity and root documentation

- Moved the private renderer from `ui-tui/packages/hermes-ink` to
  `ui-tui/packages/forecast-ink`, named `@superforecasting/ink`.
- Updated imports, type declarations, lockfile links, build/profiling scripts,
  launcher installation checks, development prebuilds, Docker paths, and docs.
- Kept renderer behavior intact: all 148 tracked renderer files mechanically
  match their prior contents after only the two name/path substitutions.
- Sorted imports where the new package name changed lint order.
- Moved 13 historical release notes into `docs/releases/` with an index.
- Added a root README directory map and simplified workflow copy.

Verification:

- Before rename: full TUI suite, 185 files passed; 2,010 tests passed, 1 skipped.
- After rename: same full-suite result, exit 0.
- Fresh locked npm install after rename: exit 0.
- Production TUI bundle, TypeScript check, and zero-warning ESLint passed after rename.
- Launcher and dependency-install tests: 41 passed. First run exposed the
  development prebuild path; fixed at its source and reran successfully.
- `git diff --check` passed.
- Logs: `/tmp/superforecasting-tui-baseline.log`,
  `/tmp/superforecasting-tui-migrated.log`,
  `/tmp/superforecasting-tui-launcher-tests.log`.

No commit, push, deployment, or user-home migration has been performed.

## Remaining work

The full objective remains active. Next inspect the Python constants/bootstrap/
time/logging dependencies and consolidate their ownership under the product
package; then migrate CLI/runtime packages and remaining root utilities in
verified slices. Audit obsolete skills/plugins/docs against active use. Full
Python suite, live TUI/PTY behavior, built wheel contents, release checks, and
complete documentation/link audit are still outstanding. Current tests alone do
not prove that the repository is ready to ship.

## Slice 2: product-owned runtime foundations

Moved four root modules into the public package, updating all active consumers:
`bootstrap.py`, `constants.py`, `clock.py`, and `logging.py`. Removed their old
`py-modules` entries and renamed the corresponding module test files. Public API
exports now resolve lazily, so importing startup helpers does not load the ledger
or configuration. Existing public domain exports retain object identity.

The packaged-install harness protection now resolves the top-level product
package instead of treating the relocated constants submodule as a root module.
Update recovery's critical-file list points to the relocated constants file.
Compatibility environment variables and persisted home paths retain their behavior;
function-level naming and other runtime consolidation remain to be done.

Wheel inspection found that `protocol/` was entirely absent from package discovery.
Added it and its subpackages, with a regression check covering discovery of every
protocol package. Built a wheel, installed it into a separate environment, and
imported the four foundations, protocol registry (101 RPCs), and TUI server from
`/tmp` under `python -I`. These imports resolved inside site-packages, not the
checkout. The wheel contains no copies of the four retired root modules.

Verification and findings:

- Bootstrap baseline: 12 passed, 5 platform skips. Startup/launcher/public API
  checks after migration: 55 passed, 5 skips.
- Constants/profile baseline: 164 passed. After move, including harness protection
  and update recovery: 209 passed.
- Consumer tests (metadata, subprocess home, MCP, code execution, TUI launcher):
  391 passed, 6 skips.
- Logging/time baseline: 73 passed. Foundation/cron/skill/subprocess tests after
  moves: 168 passed, 5 platform skips.
- Whole-suite collection: 30,011 selected tests, 2 deselected, no collection errors.
- Architecture contracts: 6 kept, 0 broken.
- Fixed malformed test helper identifiers exposed by compilation and test runs.
- Full collection initially lacked ACP/aiohttp test dependencies; installed
  `--group full-test --extra all --extra messaging` into the local environment.
- Gateway startup tests exposed unclosed SQLite connections under Python 3.13
  (ResourceWarning escalated to PytestUnraisableExceptionWarning). This is unresolved;
  it must be investigated, not suppressed or counted as passing verification.
- Full Python execution and live TUI/PTY smoke remain outstanding.

Logs: `/tmp/superforecasting-runtime-foundation-tests.log`,
`/tmp/superforecasting-constants-tests.log`,
`/tmp/superforecasting-migration-consumers.log`,
`/tmp/superforecasting-migration-collection.log`,
`/tmp/superforecasting-import-contracts.log`,
`/tmp/superforecasting-wheel-build.log`.

## Slice 3: database lifecycle and native home API

A new shutdown regression using two real SQLite connections reproduced a runtime
leak: `GatewayRunner.stop()` looked for `self._db`, but the runner owns
`self._session_db`. Corrected the shutdown lookup while preserving cleanup of
`session_store._db`. Repeated shutdown is covered. Extended the existing gateway
test cleanup fixture to track SessionDB alongside its other SQLite stores, so
startup-only tests release resources even when they do not invoke full shutdown.
The regression failed before the fix; 51 shutdown/startup/restart tests passed
afterward under Python 3.13, with resource warnings still treated as errors.

Migrated the shared home API and every active consumer to `get_agent_home`,
`display_agent_home`, `get_native_agent_home`, `get_default_agent_root`,
`get_agent_dir`, and the context override helpers. Renamed the override ContextVar
and profile-warning test file. Environment and on-disk compatibility aliases are
unchanged; no user data is migrated. 269 profile/home/logging/cron/skill/public API
tests passed. Compileall, six architecture contracts, protocol generation check,
documentation staleness check, and whitespace validation passed.

Full-suite execution started with four workers and `--maxfail=10` to identify
remaining release blockers. Log: `/tmp/superforecasting-full-suite.log`; original
exec handle: 82187. Recheck the actual handle/process before assuming it remains
live. Full-suite status is pending, not green.

## Documentation follow-through during full-suite execution

Updated the Chinese README to use the actual fork clone command, explicit TUI
launch commands, and current operating/development documentation instead of old
planning pages. Removed the upstream promotional badge while retaining license
attribution. The metadata test now verifies attribution rather than requiring a
particular promotional badge. The issue chooser directs users to product
Discussions and current documentation instead of the upstream community.

The full suite is still running on handle 82187; it progressed beyond 11%.
Read-only sampling of its busy worker showed SQLite execution, not a stopped
process. Runtime source has not changed during this run. The README metadata
assertion was updated after collection, so a failure of the previously collected
badge assertion must be rerun against the current test before drawing conclusions.

## Slice 4: session schema and lifecycle hardening

First full-suite run (handle 82187) ended with 4,074 passed, 18 failed,
3 errors, and 4 skipped. Most failures were unclosed session databases in
partial-runtime CLI/ACP tests; one was a FRED routing fixture whose fixed
observations had aged past the live freshness limit.

- Moved SessionDB test-resource ownership into the shared test fixture, removing
  duplicate gateway-only tracking. Resource warnings remain errors. Explicit
  shutdown behavior remains covered independently using real connections.
- Reproduced and fixed SessionDB initialization leaking an opened connection when
  schema setup raises. Original initialization failures still propagate.
- Anchored the FRED routing fixture to its historical reference date; production
  freshness checks remain unchanged. Failure-focused rerun: 176 passed.
- Replaced a source-text test that looked for the characters "30" in `__init__`
  (and passed on a comment despite the real 1-second timeout) with a real
  two-connection lock/retry/write regression. Session baseline: 262 passed.
- Extracted SQL definitions and schema migration methods into
  `superforecasting_agent/storage/schema.py` (351 lines). Three method bodies
  are AST-identical to the originals after normalizing docstring indentation.
  SessionDB retains delegates while further storage decomposition proceeds.
  Post-extraction session suite: 262 passed.
- A fresh-interpreter regression proved that changing the active home after
  import reused the old database path. `_default_db_path` now distinguishes a
  deliberate DEFAULT_DB_PATH override from the original import-time default.
  Explicit overrides remain supported. Expanded session/profile suite:
  379 passed. Ruff and whitespace checks passed.

Second full suite started on exec handle 77679; verify the handle or process before assuming
it remains live. Log:
`/tmp/superforecasting-full-suite-second.log`. No full-suite pass is claimed.

## Live TUI smoke and remaining input verification

Launched `python -m superforecasting_agent tui` in a real PTY with a newly
created temporary home and an allowlist environment containing no provider
credentials. The built renderer displayed the first-run Setup Required screen
and accepted composer/slash input. No provider setup or model call was performed.

Ctrl+C did not exit as expected. Repeated with a direct stdlib `pty.fork()`
harness at 120x40 to remove the tool PTY input transport from the experiment:
the setup screen appeared, but Ctrl+C still did not end the process within
three seconds. This is an unresolved behavior, not a successful quit check.
Both isolated smoke process trees were terminated and verified absent afterward.
Raw direct-PTY output: `/tmp/superforecasting-direct-pty-output.log`; reproduction
script: `/tmp/superforecasting-direct-pty-smoke.py`. The first tool-PTY script is
`/tmp/superforecasting-tui-smoke.py`. Follow up on first-run busy/overlay/input
handling; do not infer that normal configured sessions share this behavior.

The second full Python run remains on handle 77679, past 45%, with errors already
reported inline but not yet summarized. No full-suite pass is claimed.

## Second full-run follow-up

Handle 77679 is terminal: 14,617 passed, 6 failed, 4 errors, 63 skipped,
2 warnings in 411 seconds. Google Chat tests assumed a fixed `Platform.GOOGLE_CHAT`
member even though the adapter is a plugin; changed them to the existing
`Platform("google_chat")` lookup. No core platform was hardcoded.

The backup errors exposed a runtime failure-path leak: `_safe_copy_db` closed
its connections only after a successful backup. A real invalid-database fixture
reproduced open connections after fallback. Both connections are now managed by
stdlib `closing` scopes, including failure to open the destination. Backup and
Google Chat suites passed 268 tests after these changes.

Input investigation used a diagnostic copy of the TUI bundle in `/tmp` only;
no instrumentation was written to product source. Ctrl+C arrived correctly with
empty composer, no session, and no blocking overlay. The diagnostic bundle exited
normally both directly and through the Python launcher. A repeat of the original,
unmodified Python-launcher PTY smoke also exited normally (status 0). The earlier
behavior under the concurrent full-suite load is therefore intermittent; it is
not evidence of a deterministic renderer regression and has not been "fixed"
by an unsubstantiated source change. Keep under-load input verification open.

## Slice 5: session search, retention, topics, and transcript storage

Extracted cohesive storage operations behind unchanged SessionDB signatures and
API docstrings. A temporary AST/token-based carve script verified exact method
body equality, including SQL and docstring literal values, before writing each
slice. No query, transaction, or result-shape changes were combined with moves.

- `storage/search.py`: 328 lines; session-only baseline and migrated suites each
  passed 264 tests.
- `storage/retention.py`: 317 lines; maintenance, pruning, and session file cleanup.
  Expanded state/search tests passed 302 tests.
- `storage/telegram_schema.py`: 102 lines; explicit opt-in migration only.
  `storage/telegram.py`: 337 lines; topic mode and bindings. Topic/handoff baseline
  passed 55 tests; combined post-move suite passed 357 tests.
- `storage/messages.py`: 203 lines; content codec and atomic message writes.
  `storage/transcript.py`: 220 lines; message reads and anchored views. The same
  combined suite passed 357 tests after this separate extraction.

Ruff passed for the shrinking root store and all extracted storage modules.
Root SessionDB remains the public facade while further decomposition proceeds.
Temporary command logs are `/tmp/superforecasting-{search,retention,topic,transcript}-migrated.log`.

## Installed package and documentation follow-through

A wheel audit found `hermes_cli/proxy/` and its adapters absent from the built
package: setuptools discovery included `hermes_cli` but not its subpackages.
Expanded the package-discovery regression to cover runtime and product packages;
it failed on `hermes_cli` before the fix. Added `hermes_cli.*` to discovery.
Public-package and proxy tests then passed 46 tests.

Built `/tmp/superforecasting-storage-wheel/superforecasting_agent-0.20.0-py3-none-any.whl`
and reinstalled it into the separate `/tmp/superforecasting-wheel-smoke` environment.
From `/tmp` with Python isolated mode, proxy/adapters and extracted storage imports
passed. A real temporary SQLite session passed write/read/FTS search/delete.
The wheel includes current storage leaves and excludes the four retired root
foundation modules.

Repeated the unmodified TUI launcher smoke during the third full-suite run.
The first-run screen appeared and Ctrl+C exited status 0. Verified no TUI/gateway
smoke processes remained. This adds a successful under-load observation; it does
not establish a cause for the earlier intermittent delay.

Documentation now leads with `superforecasting-agent tui`, explains product runtime
foundations, and distinguishes the experimental market terminal from the primary
Ink/PTY desk. Moved the loose Gemini plan and Slack/GitHub PRD from root-level
`plans/` and `tasks/` into `docs/plans/`, preserving their contents. Corrected stale
scheduled-routine prose: current `ledger/reviews.py::_refresh_due_question` uses
`commit=False, proposal_only=True`, so the routine saves proposals, not active
probability updates. Checked local links in the touched README/development pages.

Third full Python run started on handle 88141. Log:
`/tmp/superforecasting-full-suite-third.log`. It is still running; no full pass
is claimed. Packaging changes and the expanded discovery test occurred after
full-suite collection and have separate focused verification above.

The same audit found all 63 bundled `plugin.yaml` manifests missing from wheels.
Added manifest package-data patterns. The new wheel at
`/tmp/superforecasting-plugin-wheel/superforecasting_agent-0.20.0-py3-none-any.whl`
contains every manifest byte-for-byte; its installed PluginManager discovers all
63 through the read-only scanner without loading plugin implementations.
Metadata/public-package/plugin tests passed 243 tests, 1 skipped. One obsolete
README assertion was updated to require the canonical TUI command rather than
an exact transitional comment removed from the install example.

Six import architecture contracts passed. Protocol and generated-reference
staleness checks passed. The wheel smoke artifacts above exercise Python
packaging only: they were built with `uv build`, not `scripts/build-release.sh`,
so they are not claimed as full release wheels with bundled TUI/web assets.
Next release verification should use that existing build script and a real
installed-wheel PTY launch, after the running full suite finishes.

At last inspection the third full run (88141) had reached 59% with failures/errors
already reported inline. Await its terminal summary before triage. The README
assertion collected by that run predates the focused correction above, so any
failure there needs current-test verification rather than reverting the README.

## Bundled release TUI verification

Built the real release with the existing `scripts/build-release.sh` from an
isolated source snapshot (4,764 current files plus the already-verified TUI
bundle), using `SKIP_NPM=1`. The main checkout's build inputs were not mutated
while its full suite ran. Source snapshot path is recorded in
`/tmp/superforecasting-release-source-path`; build log is
`/tmp/superforecasting-release-bundle.log`.

The build produced a wheel and sdist. Verified that the wheel includes the
4.5 MB bundled TUI entry, its ES-module marker, proxy code, and plugin manifests.
Installed it into `/tmp/superforecasting-wheel-smoke`, then launched
`python -m superforecasting_agent tui` from `/tmp` in a real PTY with a fresh
allowlist environment and temporary home. The Setup Required screen appeared;
Ctrl+C exited status 0. Reproducer: `/tmp/superforecasting-installed-pty-smoke.py`.
Raw output: `/tmp/superforecasting-installed-pty-output.log`.

This verifies the bundled first-run TUI path without a source checkout or npm
installation. It does not exercise a configured provider conversation or the
optional web bundle (`RELEASE_WITH_WEB` was not enabled).

## Third full-suite result and connection ownership fixes

Third full run completed in 589.88 seconds: 29,776 passed, 57 failed, 147 skipped,
40 errors, 48 warnings. Apart from the already-corrected README assertion, failures
were unclosed SQLite connections, chiefly Kanban and RetainDB. Some warnings were
reported in later unrelated tests when garbage collection occurred.

- Reproduced Kanban scope leakage with real commit and rollback transactions.
  Added `kanban_db.connection()` using stdlib `closing` plus SQLite's transaction
  context; `connect()` retains caller-owned connection semantics. Migrated 301
  short-lived scopes in 15 source/test files. Both regression cases failed before
  and passed after. Full Kanban/tool/dashboard subset: 724 passed, 1 skipped.
- Reproduced RetainDB queue shutdown closing neither its producer nor writer
  connection. Writer-loop `finally` and shutdown now close the calling thread's
  cached connection. The regression checks closure on each owning thread.
  RetainDB and Teams plugin suites: 79 passed.
- Combined metadata, RetainDB, and Kanban suites: 953 passed, 2 skipped. Resource
  warnings remain errors; no warning filters were weakened.
- Moved the scheduled-routines guide into `docs/scheduled-routines.md`, updating
  the live config comment, metadata test, and docs index. Corrected the index's
  stale automatic re-commit claim to match proposal-only scheduled refreshes.

Also built the optional dashboard in the isolated release snapshot with
`RELEASE_WITH_WEB=1`. Wheel build passed and contains its index plus every
referenced build asset, alongside the prebuilt TUI. Log:
`/tmp/superforecasting-release-with-web.log`. `uv lock --check` passed.
These release artifacts precede the connection-ownership fixes above; rebuild
before treating them as final artifacts for the completed cleanup.

## Session store decomposition and namespace migration completed

- Extracted listing (241 lines), replay (179), and session records (378) in
  separate bounded slices, preserving exact method bodies and SQL literals.
  Each post-move session subset passed 357 tests.
- Replaced 53 repetitive forwarding wrappers with ordinary Python method
  bindings. No metaclass or dynamic forwarding was introduced. Compared every
  method signature, name, descriptor type (regular/static/class), and public
  docstring before/after. All were preserved; three private schema docstrings
  previously lost by forwarding wrappers were restored from their functions.
- Moved handoff operations (98 lines), count/export operations into listing
  (now 287 lines), and text helpers (79 lines), preserving method bodies.
- Moved shared WAL fallback and initialization diagnostics into `storage/sqlite.py`
  (156 lines), preserving function bodies. Updated logger-specific test capture.
- Removed stale import/comment residue and compacted related method bindings.
  The former 3,285-line root store became a 374-line facade with independently
  readable storage modules (all below 400 lines).
- Moved the facade to `superforecasting_agent/storage/session.py`, updated active
  imports/patch paths/docs in 78 files, removed its old py-modules entry, and moved
  storage tests to `tests/storage/`, `test_session_storage.py`, and
  `test_storage_sqlite.py`. No active `hermes_state` references remain outside
  historical notes. Full API metadata comparison still passes after the move.

Post-namespace session suite: 357 passed. Broader metadata/Kanban integration:
889 passed, 2 skipped, with one obsolete source-file branding assertion; after
adapting that assertion to the storage package, metadata/public-package tests
passed separately. Six architecture contracts and generated docs check passed.
A new full Python run is next; no full-suite pass is claimed yet.

Fourth full run is active on handle 92320; log:
`/tmp/superforecasting-full-suite-fourth.log`. Revalidate its handle before
assuming it is running. Final focused metadata/public-package result was
166 passed, 1 skipped. No staging, commits, or publishing were performed.

## Runtime package migration and fourth full-suite closeout

The fourth full Python run (92320) finished: 29,875 passed, 1 failed, 147 skipped,
48 warnings in 582.33 seconds. The remaining failure was a test fixture whose
local mock-module variable was incorrectly expanded to a dotted attribute during
the storage rename. Corrected it to `session_module`; its three-test suite passes.
No full Python suite pass is claimed yet.

Prepared the runtime migration in an isolated current-source snapshot recorded
at `/tmp/superforecasting-cli-migration-path` so the fourth full run could finish
against stable main-worktree inputs.

- Centralized installation-root lookup in `superforecasting_agent/paths.py` and
  updated 16 runtime modules, preserving bundled-package asset lookup separately
  from source/install root and profile home. Initial path tests: 310 passed.
- Moved `hermes_cli/` into `superforecasting_agent/runtime/` and its test directory
  into `tests/runtime_cli/`, updating 786 reference-bearing files plus generated
  docs and packaging/CI/build paths. Compile checks and six architecture contracts
  passed. The isolated runtime suite had 5,322 passed, 13 failed, 10 skipped.
- Fixed four relocated-test path references and made mocked Git-update tests
  explicitly simulate a Git install instead of depending on a real `.git`
  directory. Fixed two mock-module locals affected by qualified-name expansion.
  Failure-focused set: 187 passed, 1 skipped.
- Built and installed the migrated wheel into `/tmp/superforecasting-wheel-smoke`.
  From `/tmp`, verified the installation root, discovery of all 63 bundled plugin
  manifests, absence of importable `hermes_cli`/`hermes_state`, and a real PTY TUI
  launch: Setup Required appeared and Ctrl+C exited 0.
- Promoted the checked migration into the main worktree after a concurrent-edit
  guard; 788 changed source/generated files plus the two directory moves.
  No staging, commit, or publication occurred.

Main-checkout testing exposed an unrelated import-time background update check
in `tui_gateway.server`, which could issue Git queries during another test's
subprocess mock. A fresh-interpreter regression failed before the fix. The server
now exposes `start_build_check()`; stdio, HTTP, and WebSocket transports invoke it
at startup instead of on module import. Offline failure remains non-fatal.
Promoted follow-up: 237 passed, 1 skipped. TUI transport/lifecycle suite:
381 passed. Full TUI suite: 185 files, 2,010 passed, 1 skipped (two workers).

Removed redundant nested package-discovery entries and expanded the kernel and
entry-script architecture contracts to include the whole product package.
All six contracts pass. Full repository Ruff and whitespace checks pass.
TUI build/type/lint and final metadata checks are in progress; a fifth full
Python run should follow. The isolated release wheel predates the explicit
transport-startup change and the final private keyword rename, so rebuild before
claiming a final current release artifact.

Final checks for this migration passed: TUI build, type-check, lint (zero warning
allowance), metadata/public-package tests (165 passed, 1 skipped), generated docs,
protocol staleness, and `uv lock --check`.

Fifth full Python run is active on handle 49917. Log:
`/tmp/superforecasting-full-suite-fifth.log`. Revalidate the handle before treating
it as live. Work remains on the wider repository cleanup; no completion or full
Python pass is claimed. The next cleanup slice should preserve this run's source
inputs or work in an isolated copy while it finishes.

## Container layout, launcher ownership, and fifth full-suite closeout

The fifth full Python run (49917) finished: 29,868 passed, 8 failed, 148 skipped,
48 warnings in 599.19 seconds. Artifact:
`.test-results/pytest-20260909T201553Z-91035.xml`. No full Python pass yet.

Prepared and verified the container slice in the existing isolated runtime
snapshot while that run's source inputs remained stable, then promoted 14 files
after completion:

- Image install root is `/opt/superforecasting-agent`; unprivileged user/group
  is `forecast` (numeric default remains 10000). The entrypoint discovers its
  install root relative to its own script, including paths containing spaces.
- Compose and the Hetzner-generated Compose use native UID/GID variable names.
  Compose retains native > FORECAST > HERMES alias precedence. Entry-point
  internal home references now use AGENT_HOME; exported aliases remain intact.
- The official-image root-startup guard recognizes both new and legacy image
  paths and prints the actual entrypoint path. Added path-detection coverage.
- Reversed gateway launcher ownership: the implementation is now in
  `scripts/superforecasting-agent-gateway`; `scripts/hermes-gateway` is a thin
  compatibility wrapper. Existing service identifiers and cleanup remain.
- Docker guide and browser-cache path comment match the image layout.

Verification: 207 focused tests passed, 1 skipped in the isolated copy; shell
syntax and Compose rendering passed. `/tmp/smoke-container-entrypoint.py` ran
real Bash startup against temporary files and stubbed account-management
commands: all three environment-name families passed bootstrap, UID/GID
forwarding, privilege-drop dispatch, argument preservation, direct exec,
credential permissions, and preservation of rotated credentials. Compose
precedence was separately checked with competing aliases for both services.
Both gateway launchers produced identical help before whitespace cleanup.
Docker CLI is installed, but its Colima daemon is unavailable; no image build or
real in-container user/signal verification is claimed.

All eight full-run failures were repaired:

- Release manifest fixture now creates parents for the nested runtime path.
- Release-gate local clones overlay the candidate gate and its actual version
  inputs (pyproject, runtime initializer, changelog), instead of mixing the new
  gate with the committed old directory layout.
- Update-check fixtures patch get_install_root, including a synthetic Git root;
  the fallback test no longer silently skips because of the relocated banner.
- `/save` tests removed unnecessary destructive sys.modules eviction. Reproduced
  the ensuing constants-cache identity failure with an ordered two-file run:
  1 failed / 35 passed before; 36 passed after. Active-home lookup already reads
  the environment at call time, so re-importing application modules was unneeded.

Combined release/update/container/metadata follow-up: 235 passed, 2 skipped.
Full Ruff and whitespace checks pass after removing inherited trailing spaces
from the moved gateway implementation. No staging, commits, or publishing.

Potential next bounded cleanup: root `mini_swe_runner.py` is a development/data
utility, referenced only by its two tests and its own CLI examples, and was not
included in the wheel. Its baseline passes (2 tests). Consider moving development
trajectory utilities out of the root while preserving their wire formats and
keeping the forecast runtime primary. No utility move has been made yet.

Sixth full Python run is active on handle 70082, logging to
`/tmp/superforecasting-full-suite-sixth.log`. Revalidate before assuming it is
running; preserve main source while it runs or prepare the next slice in an
isolated copy. The earlier runtime snapshot is now stale relative to the main
checkout's failure fixes and whitespace cleanup; do not promote it wholesale.
Current release wheel also remains stale, as previously noted.

## Trajectory package and root utility cleanup

The sixth full Python run (70082) finished: 29,879 passed, 1 failed, 147 skipped,
48 warnings in 582.49 seconds. Artifact:
`.test-results/pytest-20260909T202822Z-98894.xml`. The remaining failure was still
`tests/test_constants.py::TestIsContainer::test_negative_case` in a different
suite ordering. Bind the constants module once alongside its imported functions
so cache monkeypatches cannot be redirected by package-attribute replacement.
The ordered constants/save check passes (36 tests), but full validation remains
pending. The earlier `/save` destructive reload removal remains valid.

Prepared the following slices in the isolated runtime snapshot while run six
used stable main-checkout inputs, verified each carve, then promoted 26 files
and removed seven old paths after that run finished:

- `mini_swe_runner.py` moved to `scripts/data_generation/swe_runner.py` with a
  module command, README, and `tests/scripts/test_swe_runner.py`. This development
  utility was not previously included in the wheel. Its two tests and real
  `--help` launch pass. The inherited trajectory wire format is unchanged.
- `toolset_distributions.py` moved to
  `superforecasting_agent/trajectories/distributions.py` (364 lines); batch_runner
  imports and package discovery updated. Distribution/public-package checks:
  19 passed. Old root module removed.
- `trajectory_compressor.py` moved into the native trajectory package and carved
  into a 374-line `compression.py` facade, `compression_types.py` (261),
  `reporting.py` (110), `compression_cli.py` (225), `compression_io.py` (225),
  `summarization.py` (172), and `algorithm.py` (226). Ordinary method bindings
  preserve call signatures; no metaclass or registration layer was introduced.
  Its original 1,508-line root file was removed. Runtime `.env` fallback now
  uses get_install_root so moving the module does not move the development home.
- Compressor/distribution tests moved to `tests/trajectories/`; relevant logging
  test fixtures, sample script imports, metadata, docs, and README map updated.
  Removed the two old py-modules entries; native package discovery covers them.

Mechanical AST comparisons preserved every moved dataclass and method body.
CLI extraction changed only a deferred implementation import to avoid a cycle.
Focused runs passed after each extraction (76 then 91 tests). Combined isolated
checks: 268 passed, 1 skipped; promoted main-checkout set: 302 passed, 1 skipped.
All six architecture contracts, full Ruff, whitespace, and uv lock checks pass.
Empty/populated report stdout matches the original byte-for-byte; hashes and
loaded module path are in `/tmp/superforecasting-report-parity.log`.
CLI help and a directory dry-run pass without model calls.

A fresh current-source snapshot is recorded in
`/tmp/superforecasting-trajectories-release-path` (4,782 files plus verified TUI
bundle). `SKIP_NPM=1 scripts/build-release.sh` produced a wheel and sdist.
Wheel SHA-256: f6b558b37baf360eb115b4ea796b99b990ebe4e2796c5d0a5bfc52419725b195.
Inspection `/tmp/superforecasting-trajectory-wheel-inspection.json` confirms all
nine trajectory modules, 63 plugin manifests, bundled TUI, and absence of old
root compressor/distribution and Hermes runtime/storage paths.

Installed that wheel with --no-deps into the existing isolated smoke venv. From
/tmp with Python -I, trajectory types, metric aggregation, batch distribution
binding, and absence of old imports pass. The deliberately minimal smoke venv
prints a non-fatal missing-websockets warning from optional browser tool
discovery; this is not a complete optional-dependency validation. The first
batch assertion named a non-exported helper and was corrected to the actual
list_distributions import; it was a smoke-script mistake, not a code fix.

Installed TUI PTY: Setup Required appeared. First smoke harness checked waitpid
only once after PTY EOF and hit a cleanup race; no leftover process remained.
A bounded process-reaping wait in the temporary harness resolves the race:
recheck observed Setup Required and Ctrl+C exit status 0. Log:
`/tmp/superforecasting-trajectory-installed-pty-recheck.log`. This remains a
first-run smoke, not a configured-provider conversation test.

Seventh full Python run is active on handle 46021, log
`/tmp/superforecasting-full-suite-seventh.log`, artifact prefix
`.test-results/pytest-20260909T204119Z-6874`. It includes the temporary external
`/tmp/forecast_test_identity.py` diagnostic via PYTHONPATH=/tmp and -p; this logs
constants module identity changes after tests to
`/tmp/superforecasting-constants-identity-gw*.log` without changing app state.
Revalidate the handle before assuming it is live. Main runtime source should
remain stable during this run; prepare further slices separately.

No staging, commits, or publishing. Broader root/runtime decomposition remains,
including batch_runner.py and major CLI/agent files. The goal is still active.

## Batch runner decomposition and restored profile exclusions

The seventh full Python run (46021) finished GREEN: 29,880 passed, 147 skipped,
48 warnings in 598.02 seconds. Artifact:
`.test-results/pytest-20260909T204119Z-6874.xml`. This baseline predates the batch
and profile changes below. Its temporary diagnostic identified the remaining
constants-module identity changes in TestRunPreUpdateBackup: the fixture used
`__import__("sys").modules` eviction in addition to ordinary sys.modules loops.
Removed those unnecessary config/constants deletions. The stable constants-module
binding remains. Ordered backup+constants verification: 40 passed, and the
identity trace now records no changes after its initial entry. Initial diagnostic
invocation via pytest -p collided with the CLI's import-time profile parser;
reran via PYTEST_PLUGINS instead. No parser change was made for that harness issue.

Prepared bounded batch slices in the previous release-source snapshot (marker
`/tmp/superforecasting-batch-migration-path`), verified each, then promoted 28
files and removed root batch_runner.py plus tests/test_batch_runner_checkpoint.py:

- Native `superforecasting_agent/trajectories/batch.py` facade is 361 lines,
  down from the 1,321-line root implementation.
- `batch_statistics.py` (189), `batch_worker.py` (301), `batch_run.py` (356), and
  `batch_cli.py` (180) own statistics, picklable workers, orchestration, and CLI.
- Moved checkpoint tests under tests/trajectories and updated imports, package
  discovery, logging prefix, bootstrap checks, guides, examples, and AGENTS map.
- Preserved moved AST bodies. Two intentional behavior changes were separately
  tested: use the shared build_agent factory with empty resolved runtime and
  credential context while retaining exact explicit constructor settings; fix
  --list_distributions shadowing its function with the boolean flag.
  Both regression tests failed before their fixes. No provider re-resolution or
  model calls occur in those checks. Removed unused _WORKER_CONFIG state/imports.
- Spawn-context multiprocessing smoke invoked the real relocated batch worker
  on an already-completed prompt: native module import, skip result, child exit,
  and absence of output/model work all verified.

Baseline batch set: 44 passed, 5 skipped. Each carve passed the focused set;
final isolated combined check: 315 passed, 6 skipped. All six architecture
contracts remain kept; no ratchet exceptions were added for batch construction.

Found and repaired an earlier storage-namespace rename that accidentally changed
persisted `hermes_state.db` exclusion strings into a Python module path in
profiles.py and profile_distribution.py. Restored the legacy filename in both
exclusion sets, fixture data, and docs. Extended the real archive export check
and exclusion coverage: both failed before restoration. Profile/backup tests:
319 passed. These names refer to user data and must not follow Python renames.
No export or publication was performed while the incorrect lists existed.

Promoted combined follow-up: 634 passed, 6 skipped, 31 warnings. Full Ruff,
whitespace, docs codegen, uv lock, and six architecture contracts pass.

Fresh release-source marker: `/tmp/superforecasting-batch-release-path`.
Built wheel + sdist with verified existing TUI bundle (SKIP_NPM=1).
Wheel SHA-256: 8fc1af5bebecb9d9c62f179e0f0e486c5fbab620c2202e8d43991af49591cd8d.
`/tmp/superforecasting-batch-wheel-inspection.json` verifies 14 trajectory modules,
absence of batch_runner.py, correct legacy DB exclusions, and bundled TUI.
Installed into the isolated smoke venv; Python -I from /tmp verifies facade/worker
module identities, old-module absence, and both exclusions. Optional browser
module discovery still reports missing websockets in that deliberately minimal
--no-deps smoke environment. Installed TUI reached Setup Required and Ctrl+C
exited 0; log `/tmp/superforecasting-batch-installed-pty.log`.

Eighth full Python run is active on handle 52982, log
`/tmp/superforecasting-full-suite-eighth.log`, artifact prefix
`.test-results/pytest-20260909T205712Z-14690`. This run has no temporary diagnostic
plugin. Revalidate its handle and preserve main source while it runs.

The prior trajectory release SOURCE snapshot was reused for batch preparation;
its old wheel/sdist remain historical artifacts, not matching that now-modified
source directory. Use the new batch-release snapshot for the current artifact.

Remaining work includes larger CLI/agent modules, root utilities, and tightening
some documentation trees: CONTRIBUTING.md still shows native nested file paths
as separate root rows and should be consolidated under the public package.
No staging, commits, or publishing. The broader goal remains active.

## Utility ownership, shared atomic writes, and ninth suite

Removed root utils.py and split its 32 symbols by responsibility into native
`environment.py` (129 lines), `urls.py` (76), and `storage/files.py` (305).
Updated 103 caller/metadata/test paths; moved five tests to environment, URL,
and storage ownership. Fresh-process import coverage now checks bootstrap,
environment, and URLs without loading forecasting, constants, or YAML.
CONTRIBUTING's package map now groups native children correctly.

The initial extraction preserved symbol ASTs. Consolidated four identical
atomic-write transactions into `_atomic_text_writer`: temp file ownership,
permissions, fsync, symlink-preserving replacement, and failure cleanup share
one context manager. JSON/YAML serialization payload ASTs remained identical;
formatting all three new modules also preserved their complete ASTs.

Validation: baseline 62 passed; initial move 223 passed, 1 skipped; consumer
set 216 passed. An isolated broader run had one checkpoint mock failure:
its actual function co_filename pointed to the main checkout after test module
cache eviction through the shared editable venv. After promotion to a consistent
main checkout, the combined set passed: 423 passed, 1 skipped. Added an explicit
assert_called_once before reading checkpoint mock arguments. Atomic-write
follow-up: 187 passed. Ruff, whitespace, six architecture contracts, docs
codegen, and uv lock checks pass.

Eighth full suite completed: 29,881 passed, 1 failed, 147 skipped, 48 warnings
in 598.75 seconds. The gateway cleanup unit test called unrelated shared
process/delegation/client cleanup while constructing its runner via __new__;
loop.close later reported EBADF. Isolated those unrelated globals with mocks,
keeping the real loop close and agent-close assertion. Focused check: 9 passed;
also included in the 423-pass set. No production gateway change for this issue.
Do not claim a particular global cleanup function caused the bad descriptor.

Added docs/architecture/runtime-layout.md with old-to-new Python paths,
trajectory commands, renderer ownership, and retained user-data compatibility;
linked it from development and docs index.

Fresh release snapshot marker: /tmp/superforecasting-utilities-release-path.
Wheel and sdist built with the previously verified unchanged TUI bundle.
Wheel SHA-256: 53277dd403be4183380c8ab7e64bb51f61bb73bda3da640cd00a508f5b5129ec.
Inspection: /tmp/superforecasting-utilities-wheel-inspection.json. Installed
--no-deps into /tmp/superforecasting-wheel-smoke; Python -I from /tmp verifies
native utility imports, absent root utils, lightweight imports, and an actual
atomic write through a preserved symlink. Installed TUI reaches Setup Required;
Ctrl+C exits 0. Log: /tmp/superforecasting-utilities-installed-pty.log. This
remains an unconfigured first-run smoke, not a provider conversation.

Ninth full suite is ACTIVE on handle 7031, log
/tmp/superforecasting-full-suite-ninth.log. Main Python source has stayed fixed
since launching it; revalidate the handle before using it. No diagnostic plugin.

Next inspected scope: root mcp_serve.py (902 lines), model_tools.py (957), and
toolsets.py (1123). No edits yet. MCP CLI imports root mcp_serve from native
runtime/mcp_config.py. agent/transports/hermes_tools_mcp_server.py is referenced
in persisted Codex configuration generated by runtime/codex_runtime_plugin_migration.py;
any implementation rename needs an explicit compatibility launcher for existing
configs. Root agent/CLI decomposition also remains outstanding.

The earlier utility TEST snapshot is stale after atomic deduplication; do not
promote it again. Fresh utility RELEASE snapshot is current for source code.
No staging, commits, pushes, or publication. Overall cleanup goal remains active.

## MCP cleanup preparation while ninth suite runs

Ninth suite handle 7031 was polled and confirmed live during this turn; main
Python source remains unchanged. Previous goal turn classified as progress:
new import guide, built/installed utility artifact, and full-suite launch.

Created isolated snapshot at marker /tmp/superforecasting-mcp-cleanup-path.
Baseline transport/config migration: 80 passed. Moved its 239-line implementation
from agent/transports/hermes_tools_mcp_server.py to forecast_tools_mcp_server.py,
leaving a 10-line __main__ compatibility launcher for persisted Codex -m configs.
Updated new-config generation and relocated its test module. Executable ASTs
match exactly after normalizing docstrings; server ID/wire behavior unchanged.
Added launcher tests for native exit codes 0, 1, and 2. Result: 83 passed,
/tmp/superforecasting-mcp-transport-moved.log. These edits are ONLY IN SNAPSHOT;
do not assume promoted. Main full suite must finish before promotion.

Messaging bridge baseline: 88 passed, /tmp/superforecasting-mcp-messaging-baseline.log.
Found pyproject py-modules omits root mcp_serve.py even though runtime/mcp_config.py
imports it for the public serve command. Reproduced against installed utility
wheel from /tmp with Python -I: find_spec('mcp_serve') is None and mcp_command
with mcp_action='serve' raises ModuleNotFoundError(name='mcp_serve'). No server
was started. Moving this implementation under the packaged namespace should
repair this real installed-command failure, not just improve directory layout.

No messaging implementation edits yet. Proposed ownership: session data helpers,
event queue/poller, MCP tool registration, and a small creation/entry facade.
The current root file is 902 lines; keep new leaf modules near 400 or less and
preserve tool schemas and payloads. Tests patch root helper globals extensively;
update patch ownership explicitly when carving rather than adding proxy magic.

## Messaging MCP split and installed repair verified in snapshot

Isolated MCP snapshot now removes root mcp_serve.py and adds native mcp/
server.py (80 lines), data.py (146), events.py (264), conversation_tools.py
(206), event_tools.py (196), and __init__.py. Runtime MCP dispatcher imports
the native server. Script /tmp/split-mcp-messaging.py mechanically verifies
AST equality for every helper, both bridge classes, entrypoint, and all ten
tool definitions after normalizing only data-helper module qualification.
Creation delegates registration in the original tool order. No schema/payload
changes. Relocated tests/test_mcp_serve.py to tests/test_mcp_messaging.py and
updated helper mock ownership and dispatcher patch path explicitly.

Combined MCP tests: 171 passed, /tmp/superforecasting-mcp-split-tests.log.
Full Ruff and all six architecture contracts pass in the snapshot. Source
implementation is still NOT PROMOTED because ninth full suite remains live
(handle 7031, last observed near 68%).

Built wheel+sdist from the MCP snapshot with existing verified TUI bundle.
Inspection: /tmp/superforecasting-mcp-wheel-inspection.json; SHA-256
3527bd1c928f0e888e100535c8addabcafc38eedc744cc0e1b8b603fb672a1dc.
Installed into /tmp/superforecasting-wheel-smoke (replacing utility artifact).
Python -I from /tmp proves mcp_command reaches the native run_mcp_server with
verbose=True and the old transport launcher resolves the same native main.
Forced missing-SDK path exits 1 cleanly with install hint rather than missing
application-module traceback. SDK is actually absent in this deliberately
minimal environment, so this is dispatch/package verification, not a live MCP
protocol session. Installed TUI Setup Required and Ctrl+C exit 0 verified:
/tmp/superforecasting-mcp-installed-pty.log.

Promotion list for next turn, once full suite terminal: copy native mcp/ tree;
agent/transports/{forecast_tools_mcp_server,hermes_tools_mcp_server}.py;
runtime/{mcp_config,codex_runtime_plugin_migration}.py;
tests/test_mcp_messaging.py; tests/agent/transports/test_forecast_tools_mcp_server.py;
tests/runtime_cli/test_codex_runtime_plugin_migration.py. Delete old root
mcp_serve.py and old two test paths. Do not copy runtime/tui_dist or bundled
scripts mutated by release build; no wholesale snapshot promotion. Update the
runtime migration guide for root MCP import and legacy transport launcher.
Then verify combined set in main and collect current full-suite result.

## Ninth full suite green; MCP and tool boundaries promoted

Ninth full Python suite completed and handle 7031 confirmed exit 0:
29,884 passed, 147 skipped, 48 warnings in 604.56 seconds. JUnit:
.test-results/pytest-20260909T211654Z-22359.xml. This full green includes the
utility/atomic-write and cleanup-unit-test changes; it predates MCP promotion.
No full Python suite currently running.

While that run finished, extracted argument coercion (207 lines) and error
sanitization (46) from model_tools.py into superforecasting_agent/tooling/.
All seven function ASTs exactly match originals. Registry and logger behavior
preserved; orchestration imports its two required helpers. model_tools.py is
now 716 lines, down from 957. Focused baseline and moved sets each 77 passed.
Broader check found six remaining tests importing private _coerce_number from
its old owner; corrected those imports. Combined snapshot check: 290 passed.
Full Ruff and six architecture contracts pass.

After full9 exited, promoted exactly 20 files from the MCP snapshot: native
mcp and tooling leaves, transport implementation/compat launcher, two runtime
callers, model_tools.py, and affected tests. Deleted root mcp_serve.py and two
superseded test paths. Did not copy release-generated bundles or scripts.
Main combined verification: 290 passed in 3.82 seconds, log
/tmp/superforecasting-mcp-tool-boundaries-main.log. Main Ruff, six architecture
contracts, whitespace, and docs codegen checks pass. Runtime import guide now
includes MCP paths, persisted transport launcher, and tooling helper ownership.

Latest installed MCP wheel predates the TOOLING extraction and guide edits;
its MCP installed-dispatch/TUI proof remains valid for that slice, but it is not
a complete current-source release artifact. Refresh a clean release build
before claiming current artifact parity. Main source is now available for the
next bounded slice without an active full-run freeze.

Remaining root implementations: model_tools.py, toolsets.py, cli.py,
run_agent.py (plus setup.py build hook). Next natural carves in model_tools:
async bridge owns loop lifecycle, definition discovery/cache owns schema
selection, and dispatch owns tool execution. Read exact current code and tests
before moving; preserve persistent loop ownership and cache invalidation.
No staging, commits, pushes, publication, or goal completion.

## Async tool bridge ownership and tooling test layout

Moved complete async-bridge section from model_tools.py into native
superforecasting_agent/tooling/async_bridge.py. Mechanical full-section AST
comparison passed, including globals, atexit registration, worker holder,
timeout cancellation, and main/worker loop reuse. Removed the now-unused
asyncio/atexit/threading imports. model_tools.py is now 548 lines.

Registry dispatch and send_message_tool import the bridge directly. Registry
error formatting also imports tooling/errors.py directly instead of importing
the full discovery/orchestration module for a sanitizer. Updated callers and
mock paths; no remaining Python references to model_tools._run_async or imports
of the removed loop helpers. Loop tests alone pass without implicit discovery
through the old module. No behavior change to loop lifecycle intended.

Baseline: 163 passed; moved: 163 passed; standalone lifecycle: 12 passed.
Moved five test files under tests/tooling/: test_async_bridge.py,
test_arguments.py, test_errors.py, test_runtime.py, test_definitions_cache.py.
Combined organized suite plus registry, send-message, and messaging MCP:
358 passed in 3.77 seconds, /tmp/superforecasting-tooling-organized-tests.log.
Ruff, whitespace, and six architecture contracts pass. Updated migration guide.
Main source edited directly; no full Python suite currently running.

Next structural decision: remaining model_tools.py consists mostly of
schema discovery/cache (~350 lines) plus dispatch (~180). A clean native
package move should give definitions ownership of _last_resolved_tool_names
and cache globals, with dispatch reading that module's current state. Existing
delegate_tool saves/restores _last_resolved_tool_names by module assignment;
update those references explicitly. Do not re-export that mutable binding as
if it were shared state. Tests patch _compute_tool_definitions and cache globals
and need their new owning module. Root toolsets.py and the large CLI/agent
entrypoints still remain. Current installed wheel predates tooling/async work.
No commits, staging, publishing, or completion claim.

## Native tool orchestration replaces root model_tools.py

Removed root model_tools.py and its py-modules entry. Native tooling/runtime.py
is a 19-line explicit API facade. definitions.py is 354 lines and owns discovery,
compatibility maps, cache, and _last_resolved_tool_names. dispatch.py is 189
lines and reads definitions._last_resolved_tool_names at execution time.
No copied/re-exported mutable state. All moved function ASTs match originals
after normalizing only that explicit module-qualified state read. Script:
/tmp/migrate-tool-runtime.py; original source /tmp/model_tools.before-native.py.

Updated 63 caller/doc/test/metadata files plus focused cleanup. Import aliases
remain locally named model_tools where that avoids unrelated variable churn;
the import paths are native. Delegate save/restore and cache tests explicitly
use runtime.definitions state. Native runtime re-exports the public functions
and static compatibility constants. Registry mocks target the shared registry
object. No remaining actual old model_tools imports outside optional skill
examples. Loggers now use the native runtime name.

Post-update syntax guard covers runtime, definitions, dispatch, arguments,
errors, and async_bridge. Corrected an intermediate string-rewrite artifact
that used a dotted module name as a filesystem path before running consumer
tests. AGENTS and import-migration guide describe actual state ownership.
Definitions module header rewritten to describe its own responsibilities.

Focused tooling/registry/send-message/delegation/transport set: 417 passed.
Broader update, run_agent, and trajectory consumers: 1,548 passed, 3 skipped
in 26.65 seconds; /tmp/superforecasting-tool-runtime-consumers.log. Ruff,
whitespace, six architecture contracts, docs codegen, and uv lock checks pass.

Tenth full Python suite launched after all source changes and focused checks:
/tmp/superforecasting-full-suite-tenth.log. Preserve main source while running;
revalidate live handle from tool output. Full9 remains latest completed full
green (29,884 passed), predating native MCP/tooling source changes. Latest
installed wheel remains stale for tooling; fresh snapshot release verification
is next independent work while full10 runs.

Remaining packaged root implementations: run_agent.py, toolsets.py, cli.py.
setup.py remains build configuration. Broad product cleanup is not complete;
no staging, commits, pushes, or publication.

## Installed native tooling verified; toolset split prepared separately

Full10 handle 65989 confirmed live this turn; main source remains frozen.
Current log /tmp/superforecasting-full-suite-tenth.log, last near 35%.
Fresh immutable release snapshot marker /tmp/superforecasting-tooling-release-path.
Built wheel and sdist using verified existing TUI bundle. Wheel SHA-256:
12222ed01007eb206c8435f3c6ff8c3c6d606c191ecdfa77c67359d92e432682.
Inspection /tmp/superforecasting-tooling-wheel-inspection.json verifies all seven
native tooling modules, absence of root model_tools.py, and bundled TUI.
Installed in /tmp/superforecasting-wheel-smoke. Python -I from /tmp with isolated
home verifies public function identity, definitions ownership, old-module
absence, actual persistent loop reuse, and agent-loop-only tool interception.
Optional browser discovery still warns about absent websockets in the minimal
--no-deps smoke environment. Installed TUI Setup Required and Ctrl+C exit 0:
/tmp/superforecasting-tooling-installed-pty.log. No configured model turn tested.

Separate development snapshot marker /tmp/superforecasting-toolsets-path (do
not mutate the release source). Baseline toolset set: 55 passed. Script
/tmp/migrate-toolsets.py splits root toolsets.py into native tooling/toolsets.py
(347-line resolver + retained developer demo), and catalogs/{capabilities,
forecast,legacy,aliases,core,__init__}. Catalog leaves are 27-206 lines.
All 84 toolset values, insertion order, shared core-list identity, and every
resolver function AST are preserved. Internal _HERMES_CORE_TOOLS renamed
_CORE_TOOLS; persisted hermes-* preset names remain compatible. 45 files updated
for imports/docs/metadata; moved test_toolsets.py into tests/tooling/.

First preparation script import hit the known editable-venv path issue: /tmp
script imported main package rather than snapshot. Explicitly prepended snapshot
cwd to sys.path, reran extraction, and all parity assertions passed. No main
changes from that error. Corrected intermediate dotted filename in update guard
before consumer testing; guard now lists native toolset and catalog modules.
AGENTS core-tool guidance now names capability/forecast catalogs and explains
that legacy core membership does not automatically expose a forecast tool.

Moved set: 55 passed. Snapshot Ruff and six architecture contracts pass.
Broader snapshot consumers launched on handle 20353, log
/tmp/superforecasting-toolsets-consumers.log; check terminal result next turn.
Snapshot edits NOT PROMOTED. /tmp/superforecasting-toolsets-updates lists initial
45 updates but not manually added doc/core guidance changes or new catalog
files; construct explicit promotion list and exclude release/build artifacts.
Delete root toolsets.py and old tests/test_toolsets.py only after full10 terminal
and snapshot checks pass. Keep the immutable tooling release snapshot separate.
No staging, commits, pushes, publication, or goal completion.

## Toolset consumer checks and worktree preservation fix in snapshot
