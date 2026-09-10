Toolset broader consumer handle 20353 completed: 477 passed in 27.18 seconds.
Snapshot Ruff, six architecture contracts, docs codegen, and uv lock checks pass.
Main full10 handle 65989 remains live (last near 99%); source still frozen.
JUnit path .test-results/pytest-20260909T213355Z-30959.xml. Poll actual handle
before promotion; a 99% log is not a terminal process.

Inspected remaining entrypoints: cli.py is 15,005 lines; run_agent.py is 4,450.
Found concrete data-loss risks in CLI worktree cleanup: exit cleanup forced
removal of dirty worktrees; >72h stale cleanup bypassed unpushed-commit checks;
orphan cleanup force-deleted unmerged generated branches. Existing
 tests/cli/test_worktree.py often exercises copied helper implementations rather
than production code, so its prior green result did not protect these behaviors.

Added snapshot-only tests/cli/test_worktree_preservation.py using actual CLI
functions and real temporary Git repositories. Baseline: 6 failed, 1 passed;
tracked/untracked exit work, old tracked/untracked/committed work, and unmerged
orphan branches were deleted. No user checkout was used for destructive tests.

Snapshot cli.py now checks git status (including untracked and ignored files),
preserves unreadable/dirty worktrees, never lets age override unpushed/local work,
uses non-force git worktree removal, checks removal return codes before branch
cleanup, and uses git branch -d for both ordinary and orphan cleanup. The manual
hint no longer suggests --force. _active_worktree ownership unchanged. Added
regressions for staged/ignored files, clean exit/stale removal, and failed removal
preserving its branch and avoiding a false success report.

Focused security + preservation: 20 passed. Existing worktree suite alongside
those regressions: 61 passed in 4.49 seconds, /tmp/superforecasting-worktree-all.log.
Snapshot Ruff passes. Preserve the distinction: old cloned helper tests are not
independent production coverage and need replacement during the modular cleanup.
Original pre-fix CLI source: /tmp/cli.before-worktree-preservation.py.

These changes share the isolated toolsets snapshot, marker
/tmp/superforecasting-toolsets-path. Include cli.py and the new preservation test
in its eventual explicit promotion, in addition to the toolset files documented
above. None of this slice has reached main yet. Main source remains at the native
model_tools replacement while full10 completes. No publication/staging/commits.

## Full10 closeout; toolsets and worktree hardening promoted; CLI carve

Full10 handle 65989 confirmed terminal exit 1: 29,877 passed, 10 failed,
147 skipped, 48 warnings in 604.69 seconds. Nine failures patched dispatch's
private _READ_SEARCH_TOOLS at the new public API rather than its owning module;
one metadata test read deleted root mcp_serve.py. Updated the hook fixture to
patch native dispatch with {tool_name} (actually suppresses the unrelated tracker;
the old empty set did not). Metadata test now checks server identity in server.py,
home resolution in data.py, and command/config examples in user docs.
Follow-up: 170 passed, 1 skipped, /tmp/superforecasting-full10-fixes.log.

After full10 exited, promoted 53 explicit toolset/worktree snapshot files,
including all native catalog/resolver modules, cli.py hardening, preservation
regressions, caller paths, and doc guidance. Preserved the two main full10 test
fixes; they were not in the snapshot promotion list. Removed root toolsets.py and
old tests/test_toolsets.py. Main combined result: 708 passed, 1 skipped in 26.85s,
/tmp/superforecasting-toolsets-main.log. Ruff/contracts/docs/whitespace passed.

Then extracted nine worktree functions without body changes from cli.py into
runtime/worktree_setup.py (204 lines) and runtime/worktrees.py (256 lines).
Script /tmp/extract-cli-worktrees.py asserts each function AST unchanged.
Original /tmp/cli.before-worktree-extraction.py. Active worktree state now belongs
to worktrees.py; CLI assigns that module field and retains imported function
aliases for its callers. CLI shrank from 15,020 to 14,589 lines. Tests initially
had one stale symlink-source assertion; pointed it at worktree_setup.py.
Update syntax guard includes both new files; runtime migration guide updated.

Focused carve tests: 130 passed, one stale source-path assertion fixed. Entire
CLI + Windows support + metadata follow-up: 1,026 passed, 1 skipped in 9.67s,
/tmp/superforecasting-worktree-cli-consumers.log. Final lint/contracts/docgen/lock
checks are in /tmp/superforecasting-worktree-final-*.log; verify completion.

Latest installed tooling wheel is stale for toolsets and worktree changes.
Fresh immutable release snapshot/install/TUI verification remains next work.
Full9 is still last completed all-green Python run; full10 failures were fixed
focused but a subsequent full run is needed for the combined current tree.
Old tests/cli/test_worktree.py still contains copied helper implementations;
replace that misleading coverage with production-function tests in a later slice.
No staging, commits, publication, or completion claim.

## Current installed release and native CLI/test cleanup preparation

Full11 handle 42906 confirmed live this turn; main source remains frozen.
Fresh immutable release snapshot marker /tmp/superforecasting-worktrees-release-path.
Wheel+sdist built with unchanged verified TUI bundle. SHA-256:
20fa9900f42016c630f05369af97ee20235683f813fc898c31b2c5e98b2c8c08.
Inspection /tmp/superforecasting-worktrees-wheel-inspection.json: six catalogs,
native resolver/worktree modules, no root toolsets.py or model_tools.py.
Installed Python -I from /tmp verifies 84 presets, forecast-desk resolution,
shared legacy membership-list identity, and native worktree function ownership.
Installed TUI Setup Required and Ctrl+C exit 0 verified, log
/tmp/superforecasting-worktrees-installed-pty.log. Still first-run only.

Prepared replacement for tests/cli/test_worktree.py in
/tmp/superforecasting-worktree-tests/test_worktree.py. Old 1,030-line suite
contained copied setup/cleanup/include/pruning helpers plus assertions on
standalone expressions; its purported concurrent test was a serial loop.
New 131-line suite directly calls native modules and uses actual temporary Git
repos: detection, no-commit/outside-repo failures, isolated files/branches,
gitignore non-duplication, cleanup with three remote states, missing-path safety,
include copying/linking, stale clean age thresholds, and orphan branch handling.
All 18 cases pass. Existing separate security/preservation tests retain negative
path-boundary and dirty/unmerged-work protection coverage. No production code
removed to make tests green; no new copied production implementation.

New isolated source snapshot marker /tmp/superforecasting-cli-native-path.
It includes the replacement worktree tests and canonical class rename:
ForecastCLI now owns the full class implementation; empty ForecastCLI(HermesCLI)
wrapper removed; HermesCLI = ForecastCLI is the compatibility import alias.
Full class AST matches after normalizing just the class/name references.
Metadata tests assert native __name__ and alias identity. Snapshot AGENTS and
runtime migration guide updated. Windows symlink-only test explicitly skips
when directory-symlink privilege is platform-dependent.

Snapshot combined CLI, metadata, TUI resume, and gateway tests:
1,189 passed, 1 skipped in 17.09 seconds; /tmp/superforecasting-cli-native-tests.log.
Ruff and six architecture contracts pass. Changes are NOT PROMOTED. Once full11
is terminal, explicit promotion list is cli.py, tests/cli/test_worktree.py,
tests/test_project_metadata.py, AGENTS.md, docs/architecture/runtime-layout.md.
Do not overwrite main worklog from this snapshot. Immutable release source is
separate and still matches current main production code before this rename.
No staging, commits, publication, or completion.

## CLI support helpers carved in pending native-class snapshot

Full11 handle 42906 confirmed live this turn; main production source remains
unchanged (last log near 81%). Continued only in /tmp/superforecasting-cli-native-path.
Extracted five functions from cli.py into runtime/assistant_text.py (reasoning
and tool-tag stripping, multimodal text conversion, clipboard text) and
runtime/session_maintenance.py (session/checkpoint startup retention hooks).
Script /tmp/extract-cli-support.py asserts each moved function AST identical.
CLI aliases keep existing caller signatures and patch surfaces. Snapshot CLI
shrinks 14,581 -> 14,412 lines, after its earlier canonical class rename.

Text baseline: 9 passed. Combined CLI/text/metadata/TUI resume/gateway set:
1,198 passed, 1 skipped in 13.38 seconds, /tmp/superforecasting-cli-support-tests.log.
Ruff and six architecture contracts pass. Moved the display test from
 tests/run_agent/test_strip_reasoning_tags_cli.py to
 tests/runtime_cli/test_assistant_text.py and imported the leaf directly.
Fresh process verifies both helpers load without cli, run_agent, or forecasting
initialization and normalizes a mixed text block correctly. Added both leaves
to post-update syntax guard; guard + display tests: 108 passed in 15.64 seconds,
/tmp/superforecasting-cli-support-guard-tests.log. Migration guide updated.

Expanded eventual promotion list (after full11 terminal): cli.py,
AGENTS.md, docs/architecture/runtime-layout.md, tests/cli/test_worktree.py,
tests/test_project_metadata.py, runtime/main.py, runtime/assistant_text.py,
runtime/session_maintenance.py, tests/runtime_cli/test_assistant_text.py; delete
old tests/run_agent/test_strip_reasoning_tags_cli.py. Prefix runtime/ paths with
superforecasting_agent/. Do not overwrite main worklog from snapshot.

Next larger seam inspected: load_cli_config is ~394 lines and depends on cached
_hermes_home, Path(__file__), YAML, env aliases, and redaction side effects.
Any move must preserve active-home and installation-root resolution, explicit
ignore-user-config semantics, and initialization ordering. No edits to it yet.
Installed worktrees release remains current for main, predating pending CLI
class/helper changes. No staging, commits, publication, or completion claim.

## Full11 fixes and native CLI/configuration slice promoted

Full11 handle 42906 confirmed exit 1: 29,897 passed, 4 failed, 147 skipped,
48 warnings in 607.59 seconds. Three tests imported moved _HERMES_CORE_TOOLS
from the resolver; changed them to catalogs.core._CORE_TOOLS. Yuanbao's test
used importlib.import_module('toolsets'); updated the dynamic import path.
Focused four-file set: 178 passed, /tmp/superforecasting-full11-fixes.log.
No production defect indicated by these four stale test references.

In the pending native-CLI snapshot, split load_cli_config into
runtime/interactive_config.py (274 lines) and interactive_defaults.py (144).
Root CLI wrapper supplies cached home, installation-relative project filename,
ignore-user-config decision, and redaction callback explicitly. Defaults factory
creates a fresh nested dict per load. Script /tmp/extract-interactive-config.py
verifies defaults expression AST and every retained loader statement after only
parameter/default-factory substitutions. Startup ordering and environment bridge
side effects retained. Baseline: 110 passed. First moved set found five source
inspection tests pointing at wrapper instead of implementation; corrected env-map
inspection ownership. Replaced auxiliary source-substring test with actual YAML
load and returned-config/environment assertions, isolating os.environ through
monkeypatch. Moved set: 110 passed. Broad consumers: 1,339 passed, 1 skipped.

After full11 ended and focused fixes passed, promoted 13 explicit snapshot files:
canonical ForecastCLI + legacy alias; real worktree test replacement; assistant
text/session maintenance modules; interactive config/defaults modules; updated
metadata/config tests, guard, and guides. Deleted old run_agent-located display
test. Four main full11-fix test files were not overwritten. Main combined suite:
1,447 passed, 1 skipped in 27.78 seconds, /tmp/superforecasting-cli-native-main.log.
CLI is now 14,028 lines. Still a large implementation; no completeness claim.

Docs check flagged config-and-env.md stale after moving an env read into the
scanned native package. Regenerated via scripts.docgen; the additional
_HERMES_GATEWAY read is now attributed to runtime.interactive_config. No manual
editing of generated reference. Final main Ruff/contracts/doccheck/lock/whitespace
checks in /tmp/superforecasting-cli-native-main-*.log; check terminal status.

Latest installed worktrees wheel now predates this canonical CLI/config slice.
Fresh release/install/TUI verification is next. Full9 remains latest completed
all-green Python run; full10 and full11 stale-reference failures fixed focused.
No full suite active at this log entry; next full run should cover this combined
state once final gates complete. Old cli-native and toolset snapshots are stale
relative to main test fixes; never wholesale promote them.
No staging, commits, pushes, publication, or completion.

## Installed native CLI verified; agent session persistence prepared

Full12 handle 32305 confirmed live; main source remains frozen. Fresh immutable
release snapshot marker /tmp/superforecasting-native-cli-release-path. Built
wheel+sdist with verified unchanged TUI bundle. SHA-256:
01cafd9abb7f89b9d6a49358a264b97d15a8b31621cb8cf68e495196123814a9.
Inspection /tmp/superforecasting-native-cli-wheel-inspection.json confirms native
CLI class/alias and four support/config modules. Installed Python -I from /tmp
with isolated home proves ForecastCLI is HermesCLI with native __name__, fresh
nested defaults across loads, real YAML merge, and terminal timeout env bridge.
Installed TUI Setup Required and Ctrl+C exit 0: /tmp/superforecasting-native-cli-installed-pty.log.
This remains first-run verification, not a configured provider conversation.

New independent snapshot marker /tmp/superforecasting-agent-persistence-path.
Baseline entire tests/run_agent: 1,368 passed, 3 skipped in 17.15 seconds.
Extracted eight methods into agent/session_persistence.py (308 lines): transcript
cleanup/override, session save orchestration, SQLite flushes, last-assistant
trimming, content cleanup/redaction, and JSON session log writes. AIAgent binds
functions with ordinary imports and retains two staticmethod descriptors.
run_agent.py shrinks 4,450 -> 4,180 lines. Updated atomic-write mock owner to the
new module and removed create=True so a wrong target cannot be silently created.

Script /tmp/extract-agent-persistence.py verifies every method AST after removing
only the two class-specific staticmethod decorators. Initial naive dedenting
was rejected by parity checks because it changed docstring and embedded
multiline-message whitespace. Fixed extraction to preserve multiline STRING
token interiors exactly; final full AST comparisons pass, including literal
strings. Early aborted attempts did not change root runner code. No behavioral
shortcut taken to satisfy tests. Final moved suite: 1,368 passed, 3 skipped in
15.91 seconds, /tmp/superforecasting-agent-persistence-moved.log.
Ruff and all six architecture contracts pass.

Snapshot update syntax guard includes agent/session_persistence.py; migration
guide describes new ownership. Storage/update consumer log:
/tmp/superforecasting-agent-persistence-consumers.log. Docs check log:
/tmp/superforecasting-agent-persistence-docgen.log. Check terminal outputs.
Pending explicit promotion after full12 terminal: run_agent.py,
agent/session_persistence.py, tests/run_agent/test_run_agent.py,
superforecasting_agent/runtime/main.py, docs/architecture/runtime-layout.md.
No wholesale snapshot copies; main worklog and any full12 fixes must survive.
No staging, commits, publication, or goal completion.


## Full12 green; persistence and API errors integrated

Full12 completed: 29,878 passed, 147 skipped, 48 warnings in 582.44 seconds.
Log /tmp/superforecasting-full-suite-twelfth.log; JUnit
.test-results/pytest-20260909T220225Z-54434.xml. Covers native CLI/config,
worktree preservation, native tooling/catalogs and MCP changes. No source was
changed while this full run was active.

Prepared six additional provider-error/diagnostic methods in agent/api_errors.py
(159 lines), retaining exact function ASTs including multiline string values and
two staticmethod descriptors. Snapshot run_agent.py is now 4,044 lines (from
4,450 before these two extractions). Initial agent suite: 1,367 passed, 1 failed,
3 skipped. Failure was a source-location assertion for callable credential
formatting, replaced by behavioral verification that the bound method returns
its placeholder without invoking the credential callable. Follow-up callable,
OAuth recovery, streaming and update checks: 184 passed in 15.86 seconds.
Logs /tmp/superforecasting-agent-api-errors-{tests,followup,ruff,architecture,docgen}.log.
Ruff, six architecture contracts and generated docs passed. Persistence storage
and update consumers also completed: 370 passed in 32.10 seconds.

After full12 terminated, promoted only seven explicitly reviewed files from the
persistence snapshot: run_agent.py, both agent leaf modules, their two existing
test files, update syntax guard and architecture guide. Main worklog preserved.
Main integrated verification follows. The installed native CLI release now
predates these two agent extractions. No staging, commits or publication.


## Integrated agent leaves and image preprocessing

Main persistence/API-error integration: 1,523 passed, 3 skipped in 28.11 seconds,
/tmp/superforecasting-agent-extractions-main.log. Ruff, six import contracts,
generated docs, lock consistency and diff whitespace passed.

Extracted eight image-preprocessing methods to agent/image_preprocessing.py
(295 lines initially). Mechanical method AST checks preserved signatures,
strings and staticmethod descriptors. All agent/image-routing tests passed:
1,399 passed, 3 skipped in 15.57 seconds. Then, in a separate simplification,
verified that the Anthropic and general non-vision preprocessing statement ASTs
were identical (excluding docstring) and replaced the Anthropic body with a
module-level call to the shared implementation. The direct call preserves
existing behavior even if a subclass overrides the other bound method.
Removed four now-unused root imports. Final image leaf 271 lines; root agent
3,785 lines. Updated syntax guard and ownership guide.
Combined agent/image/update check: 1,498 passed, 3 skipped in 23.96 seconds,
/tmp/superforecasting-agent-images-shared.log. All gates passed again.

Full13 launched handle 40029, /tmp/superforecasting-full-suite-thirteenth.log.
Main production source frozen until terminal result; inspect live before edits.
Fresh immutable release marker /tmp/superforecasting-agent-leaves-release-path.
Built wheel+sdist, SHA-256
702c01a7e49195c8fa464b6b72ecd514ff1ad96fb6e9fa95d441a6b8c96d549f.
Wheel inspection confirms byte parity for root agent and all three new leaves.
Installed Python -I under isolated HOME/from /tmp verifies bound native modules,
callable credential handling, image no-op identity, real session JSON writes and
preservation of longer existing history. Log
/tmp/superforecasting-agent-leaves-installed-check.log. Minimal --no-deps smoke
venv emits the known missing-websockets discovery warning; full browser tool
installation is outside this smoke. Installed PTY check pending terminal output.

Next isolated work snapshot marker /tmp/superforecasting-agent-status-path is
for status-output extraction while full13 runs; nothing from it promoted yet.
No staging, commits, pushes or goal completion.


## Status-output extraction and standalone skill-home repair prepared

Installed agent-leaves TUI smoke completed: Setup Required visible, Ctrl+C exit
0, /tmp/superforecasting-agent-leaves-installed-pty.log. No configured provider
conversation or paid model request performed.

Independent snapshot /tmp/superforecasting-agent-status-path (k38j5cfg) contains
pending status and skill changes, not yet promoted. Status baseline entire
agent suite: 1,368 passed, 3 skipped in 17.08 seconds. Moved ten output-sink,
lifecycle-notification and retry-buffer methods to agent/status_output.py
(198 lines), preserving exact ASTs and multiline strings via
/tmp/extract-agent-status.py. Snapshot root agent now 3,623 lines; main remains
3,785. After move: 1,368 passed, 3 skipped in 15.66 seconds. Consumer TUI gateway,
ACP, oneshot and update checks: 287 passed in 18.20 seconds.
/tmp/superforecasting-agent-status-{baseline,moved,consumers,ruff,architecture,docgen}.log.
Ruff, six architecture contracts and docgen checks passed. Syntax guard and
runtime-layout guide include status_output. No source changes in main while
full13 is running.

Found a real standalone grounded-citations fallback bug: when the main package
cannot be imported, its helper honored only HERMES_HOME, silently ignoring
SUPERFORECASTING_AGENT_HOME and FORECAST_HOME. Four precedence regression cases
proved 2 failures (native/forecast) and 2 controls passing before the fix.
/tmp/superforecasting-skill-home-red.log. Fixed the stdlib fallback to match the
native > forecast > legacy > default precedence. Renamed Google Workspace's
private helper to _workspace_home.py and citations' to _citation_home.py, updating
all local imports plus tests. Different names also avoid sharing a same-named
helper in sys.modules when both script families run in one Python process.
These helpers remain skill-local because each skill must run independently of
an installed product package. Existing Google Workspace fallback already had
correct precedence and its body remains unchanged.

Grounded-citation, Google Workspace and metadata suite: 241 passed, 1 skipped in
3.38 seconds, /tmp/superforecasting-skill-home-green.log. Ruff passed. Standalone
-S subprocess from /tmp (no site packages) actually registered a fixture citation
and wrote its ledger under the native home, leaving legacy path absent:
/tmp/superforecasting-skill-home-standalone.json. No network request performed.
Root product-doc local Markdown/HTML link check found no missing targets.

Pending explicit promotion once full13 terminates:
- run_agent.py, agent/status_output.py, superforecasting_agent/runtime/main.py,
  docs/architecture/runtime-layout.md
- skills/productivity/google-workspace/scripts/{_workspace_home.py,setup.py,
  google_api.py,gws_bridge.py}; delete its old _hermes_home.py
- skills/research/grounded-citations/scripts/{_citation_home.py,sources.py};
  delete its old _hermes_home.py
- tests/skills/test_google_oauth_setup.py,
  tests/skills/test_grounded_citations_skill.py, tests/test_project_metadata.py
Preserve main worklog and any full13 fixes; do not wholesale copy snapshot.
The installed wheel covers main before these pending changes. Full13 handle
40029 remains to check live at this entry. No staging, commits or publication.


Additional snapshot cleanup: removed an unused direct AIAgent import from
runtime/oneshot.py; its actual construction already uses build_agent(runtime=...).
Removed the corresponding import-contract exception and changed the ownership
map's remaining count from 21 to 20. All six contracts and Ruff passed; one-shot
CLI/resume and factory tests: 40 passed in 2.18 seconds. First invocation used a
nonexistent tests/agent/test_agent_factory.py and ran zero tests (exit 5); corrected
to tests/test_agent_factory.py before reporting success.
/tmp/superforecasting-oneshot-factory-{tests,contracts,ruff}.log.
Add three explicit files to pending promotion: superforecasting_agent/runtime/oneshot.py,
pyproject.toml, docs/architecture/ownership-map.md. No lockfile dependency change.
Snapshot whole-suite collection running in /tmp/superforecasting-status-snapshot-collection.log.
Full13 confirmed alive at 94 percent via handle 40029 and process 62274;
no restart and no main source mutation.


## Full13 green and reviewed snapshot promoted

Full13 completed with exit 0: 29,878 passed, 147 skipped, 48 warnings in 611.71
seconds. /tmp/superforecasting-full-suite-thirteenth.log; JUnit
.test-results/pytest-20260909T221813Z-62264.xml. This verifies the integrated
persistence/API-error/image-preprocessing leaves before the pending status/skill
changes. No source was changed during the full run.

Snapshot full collection: 30,028/30,030 collected (2 deselected), no import errors,
21.22 seconds. /tmp/superforecasting-status-snapshot-collection.log.
Moved inherited Kanban PDF unchanged to docs/plans/kanban-v1-spec.pdf and updated
both runtime references and Korean documentation references. SHA-256 preserved:
708469e633223b2e52478b008d6a5fbe75b8da305cabfdd8248c0d02913455f7.
Kanban checks: 549 passed, 1 skipped in 6.20 seconds. Generated docs and lock check
passed. No PDF content changes.

After authoritative full13 terminal exit, promoted exactly 20 reviewed files
listed in /tmp/superforecasting-status-promotion.json, removed only the three
replaced skill-helper/PDF paths. Main worklog preserved. Integrated main checks
follow. Installed agent-leaves wheel now predates this last integration.
No active full-suite process at this point. No staging/commits/publication.


Integrated status/skill/oneshot/document move checks: 2,485 passed, 5 skipped in
41.47 seconds, /tmp/superforecasting-status-integration-main.log. All Ruff,
architecture, docgen, lock and whitespace gates passed. Fresh release marker
/tmp/superforecasting-status-release-path; SHA-256
ac25a882847d6777861a865e861079a15afb5e4b49c86bd5f1d0d56e833e6d4b.
Wheel inspection confirms agent/status_output.py byte parity and both native
skill-helper data files, with no old /scripts/_hermes_home.py files. Installed
isolated retry-buffer suppression and single delivery check passed; installed
TUI Setup Required + Ctrl+C exit 0 passed. Logs
/tmp/superforecasting-status-installed-{check,pty}.log. No configured LLM call.

Next session-lifecycle extraction being prepared in main after a baseline run;
no full suite active. /tmp/extract-agent-lifecycle.py is prepared, not executed
at this entry. Baseline log /tmp/superforecasting-session-lifecycle-baseline.log.
Existing cleanup tests cover process termination and hard/soft lifecycle
semantics; two patch-owner sites need updates when the leaf moves. One existing
negative test patches tools modules although close uses imported aliases, so
that test should patch actual call owners to make its invariant effective.
No staging, commits or publication.


## Session lifecycle extracted; full14 launched

Baseline agent/resource/cache/shutdown checks: 1,483 passed, 3 skipped in 17.83
seconds, /tmp/superforecasting-session-lifecycle-baseline.log. Extracted five
methods (memory shutdown/commit, completed-turn sync, client eviction, full
close) into agent/session_lifecycle.py (215 lines). Exact AST and literal-string
parity checked by /tmp/extract-agent-lifecycle.py. Root runner 3,623 -> 3,429 lines.
Updated syntax guard and runtime ownership guide. Existing root cleanup imports
remain at this slice; inspect external consumers before removing unused aliases.

Updated cleanup mocks to the new actual binding owner. Also repaired the existing
negative cache-eviction test: it patched tools modules, but the implementation
calls imported aliases, so the old patch could miss forbidden cleanup. It now
patches agent.session_lifecycle directly. The existing positive full-shutdown
control patches that same owner. Moved full targeted set: 1,483 passed, 3 skipped
in 15.93 seconds, /tmp/superforecasting-session-lifecycle-moved.log. Ruff, six
contracts, docgen and whitespace gates passed.

Temporary /tmp/codex_lifecycle_negative.py pytest plugin replaced release_clients
with a deliberately broken implementation inside ONE separate test process;
corrected invariant fails as intended with recorded cleanup of idle-resume-test-2.
/tmp/superforecasting-session-lifecycle-negative.log (1 expected failure).
No production file mutated for the negative control. Normal test + update checks
then passed: 100 passed in 14.16 seconds,
/tmp/superforecasting-session-lifecycle-followup.log. External networking remained
blocked by tests; no real provider conversation or paid request occurred.

Full14 launched handle 8160, /tmp/superforecasting-full-suite-fourteenth.log.
Do not mutate main source until its authoritative terminal result; work in a
fresh snapshot if continuing another carve. The status release wheel remains
last installed artifact (ac25a882...), predating only this lifecycle carve.
All preceding status, skill, oneshot and document changes are integrated; prior
status snapshot is stale and must never be wholesale promoted. No outstanding
pending promotion. No staging, commits, pushes or publication. Goal incomplete.


## Full14 green; HTTP clients and credential recovery integrated

Full14 completed exit 0: 29,882 passed, 147 skipped, 48 warnings in 579.45 seconds.
/tmp/superforecasting-full-suite-fourteenth.log; JUnit
.test-results/pytest-20260909T223401Z-70345.xml. Covers native skill-home repair,
status output, standalone helper renames, document move, and session lifecycle.
Main source remained frozen during the run.

Isolated client snapshot marker /tmp/superforecasting-agent-clients-path.
Baseline entire agent set: 1,368 passed, 3 skipped in 16.44 seconds. Twelve shared
and per-request HTTP client methods moved into agent/openai_clients.py (212 lines),
exact AST/string parity; after move 1,368 passed, 3 skipped in 15.46 seconds.
Consumer update/cache/resource/factory checks: 174 passed in 22.22 seconds.
/tmp/superforecasting-agent-clients-{baseline,moved,consumers,ruff,contracts}.log.
Then five provider refresh/rotation methods moved to agent/credential_recovery.py
(246 lines before helper reuse), exact AST/string parity; 1,368 passed, 3 skipped
in 17.46 seconds, /tmp/superforecasting-credential-recovery-moved.log.

Found Nous refresh bypassing its existing native environment helpers by reading
HERMES_* values directly. Extended the existing refresh test with conflicting
native/legacy settings; it failed with (90, 3.0) instead of (180, 5.5), proving
the bug. Reused nous_min_key_ttl_seconds/nous_timeout_seconds from runtime.nous_env
and removed the duplicate parsing. Full agent/auth/update checks then passed:
1,530 passed, 3 skipped in 29.28 seconds.
/tmp/superforecasting-nous-refresh-native-red.log;
/tmp/superforecasting-credential-recovery-native-green.log. Ruff, contracts and
docgen checks passed. Syntax guard and ownership guide updated.

After full14 terminal, promoted six explicit files from the client snapshot.
Main runner now 3,040 lines. No other snapshot files promoted; worklog retained.
Main integrated tests follow. Old root cleanup imports intentionally retained:
agent.chat_completion_helpers still calls _ra().cleanup_vm/cleanup_browser.

Current installed artifact, built before the six-file promotion, includes the
session lifecycle carve. Marker /tmp/superforecasting-lifecycle-release-path;
SHA-256 371ca658b5e760da3dbabd8e265771ad71e3000534f9a14cf6bf134f315f7ae6.
Wheel byte parity checked; installed scoped eviction-vs-shutdown check passes,
installed Setup Required + Ctrl+C exit0 passes. Logs
/tmp/superforecasting-lifecycle-installed-{check,pty}.log.

An additional /tmp/superforecasting-configured-tui-probe.py uses the existing
PTY/VT harness with installed package, isolated home, dummy credentials and a
loopback mock provider. First attempt's first-paint predicate used wrong casing
(Forecast vs Superforecasting), timed out although configured home rendered;
process group cleaned. Corrected predicate uses fixture-local; second attempt
currently testing prompt/stream response, handle 47507. Inspect authoritative
result. This is fixture-backed transport validation, not a real-provider quality
or forecasting workflow claim. No staging, commits, pushes or goal completion.


## Client/auth main checks and configured TUI streaming coverage

Main integrated client/recovery checks: 1,605 passed, 3 skipped in 35.49 seconds,
/tmp/superforecasting-client-recovery-main.log. Separate exit-code-gated Ruff,
contracts, docgen and whitespace checks all passed.

Configured installed TUI fixture now succeeds. The second probe sent prompt text
and Enter in one PTY write, which the input handler treated as a paste; it left
the prompt in the composer and timed out without an inference request. Split
text entry, wait for it to render, then send Enter as its own event. Third probe
rendered LOCAL FIXTURE RESPONSE from /v1/chat/completions with stream=true and
model fixture-local; Ctrl+C exit0. A metadata /api/show probe and a later
nonstream auxiliary request were also served locally. All credentials were
throwaway fixture values under an isolated temporary home. Logs/screens:
/tmp/superforecasting-configured-tui-probe.log,
/tmp/superforecasting-configured-tui-response-screen.txt,
/tmp/superforecasting-configured-tui-requests.json.
This installed probe used the lifecycle wheel, preceding the client/recovery
promotion; it is not evidence for a real model's forecast quality.

Added tests/tui_pty/test_configured_chat.py (local HTTP fixture + real PTY/VT,
existing harness reused) so CURRENT MAIN is covered end-to-end: configured home,
composer input, separately delivered Enter, actual streamed request carrying the
unique typed user prompt, rendered unique response, clean quit. No agent or
transport implementation is mocked; only the model service is local/deterministic.
This fills the setup-only PTY coverage gap without changing TUI source.
New test passed in 3.17 seconds; Ruff passed.
/tmp/superforecasting-configured-chat-test.log. Entire tests/tui_pty now running
in /tmp/superforecasting-configured-chat-pty-suite.log; inspect terminal outcome.
No active full suite at this entry. No staging, commits or publication.


Entire real-terminal suite passed: 26 passed in 6.45 seconds,
/tmp/superforecasting-configured-chat-pty-suite.log. It now covers a configured
prompt round trip in addition to existing setup, resize, shutdown and gateway
respawn checks. No TUI source changes.

Full15 launched handle 90646, /tmp/superforecasting-full-suite-fifteenth.log.
Main source frozen until terminal result. No pending snapshot promotion;
agent-clients snapshot is stale relative to main's new configured-chat test and
must not be wholesale promoted.

Fresh current-main release marker /tmp/superforecasting-client-recovery-release-path;
SHA-256 62960fa5658875ea3430eef25dd3b56cb374e1ccfa8d71963fd08d26b8506a71.
Built wheel+sdist; byte parity for root agent/openai_clients/credential_recovery
verified and wheel installed into /tmp/superforecasting-wheel-smoke. Re-running
the configured local-provider PTY probe against this CURRENT artifact; log
/tmp/superforecasting-client-recovery-installed-chat.log. Inspect result before
claiming completion of the refreshed installed check.

Potential next naming cleanup inspected only: optional-skills/migration/
openclaw-migration/scripts/openclaw_to_hermes.py is still a 3,145-line actual
implementation, referenced by runtime/claw, tests and generated skill docs. No
changes yet. A future native implementation name should retain an explicit
legacy CLI shim and account for installed-old-skill lookup compatibility. Root
agent is 3,040 lines; classic CLI remains large. Overall 12-hour goal incomplete.
No staging, commits, pushes or publication.


Refreshed installed configured-chat probe completed exit 0 on the current
62960fa5... wheel: typed prompt, local /v1/chat/completions stream=true response,
rendered transcript and clean Ctrl+C exit verified. Log
/tmp/superforecasting-client-recovery-installed-chat.log. No configured probe
process remains active. Full15 is independently live (handle 90646, process
78475; last observed around 22 percent). Preserve source until it terminates.
No pending code promotion or unfinished targeted test; the full run is pending.


## Full15 green; first OpenClaw migration slices integrated

Full15 completed exit 0: 29,883 passed, 147 skipped, 48 warnings in 607.67 seconds.
/tmp/superforecasting-full-suite-fifteenth.log; JUnit
.test-results/pytest-20260909T224855Z-78465.xml. Covers client/credential recovery,
native Nous setting fix, and new real-terminal configured-chat test. Main source
was frozen throughout. Goal time accounting at this point is about 4.24 hours,
not the requested 12; substantial work remains, especially classic CLI and
remaining legacy implementation surfaces.

OpenClaw isolated snapshot marker /tmp/superforecasting-openclaw-cleanup-path.
Baseline migration/hardening/CLI/setup tests: 148 passed in 3.02 seconds.
Deduplicated setup/CLI module loading into runtime/openclaw_loader.py. The shared
loader has the same AST as the original CLI loader after function-name
normalization; setup retains its missing-script guard. Tests: 148 passed in
2.29 seconds. Loader still uses the old module identity until the later native
entrypoint migration; do not claim the filename rename completed.

Extracted eleven standalone file/value helpers to _forecast_migration_files.py
(113 lines), exact function ASTs preserved. The entry script adds its sibling
directory to sys.path for importlib-based loading as well as direct execution.
Initial post-move run: 11 failures/137 passes because remaining entry methods
still reference yaml; retained yaml as an explicit export from the helper so
there is still one optional dependency import. Corrected suite: 148 passed in
2.56 seconds. No changes leaked from the isolated snapshot during failure.

Moved 21 option/data/class/function declarations to _forecast_migration_options.py
(284 lines), exact ASTs and ordering preserved, including ItemResult dataclass
and shared preset dictionaries. Original names are re-exported from the entry.
Tests: 148 passed in 2.13 seconds. Full migration/update/metadata consumers:
408 passed, 1 skipped in 26.07 seconds. Ruff, six import contracts and docgen
passed. Original and modularized standalone --help are byte-identical under
python -S from /tmp (no site packages). Logs
/tmp/superforecasting-openclaw-{baseline,loader-tests,files-tests,files-fixed,
options-tests,consumers,ruff,contracts,docgen,standalone-help}.log.

After full15 terminal, promoted eight explicit files: the two runtime callers,
shared loader, update guard, runtime guide, migration entry and its two sibling
helpers. Main worklog retained. Main integration checks follow. No active full
suite at this entry. Installed 62960fa5... artifact predates only these slices.

Native migration filename, further decomposition and skill guide modernization
are NOT completed. Current SKILL description exceeds 60 characters, section
order is old, preset/secret lists are stale relative to code. Last file author
from local git history is Theodore Pender; preserve upstream Nous attribution
when updating authorship. No actual operator migration was performed, and these
authoring changes do not invoke the skill's user-migration approval workflow.
No staging, commits, pushes, publication or goal completion.

### OpenClaw report, text, channel and provider ownership

Main integration of the initial eight OpenClaw files passed 408 tests, 1 skipped
in 25.90 seconds (/tmp/superforecasting-openclaw-main.log). Then extracted report
redaction and serialization declarations into _forecast_migration_reports.py
(139 lines), preserving the whole AST block and re-exporting previous names.
Focused migration/hardening/CLI/setup checks: 148 passed in 2.66 seconds.
Ruff and whitespace checks clean. Log /tmp/superforecasting-openclaw-reports-tests.log.

Extracted six brand/Markdown/memory merge declarations into
_forecast_migration_text.py (174 lines); ASTs unchanged. Removed only accumulated
blank gaps from previous top-level extractions. Focused checks: 148 passed
(/tmp/superforecasting-openclaw-text-tests.log).

Extracted eleven channel/environment methods into
_forecast_migration_channels.py (248 lines). Class-body imports preserve binding;
_get_channel_field retains its staticmethod descriptor. Function AST comparison
preserves every body, annotation, and string literal. Focused checks: 148 passed
in 1.98 seconds (/tmp/superforecasting-openclaw-channels-tests.log).

Extracted four provider-key/model/TTS methods into
_forecast_migration_providers.py (336 lines), also exact method AST preservation.
Ruff passes. Focused test log /tmp/superforecasting-openclaw-providers-tests.log;
terminal result recorded below. Extraction scripts are in /tmp/extract-migration-
{text,channels,providers}.py and are not product files.

Follow-up issue identified by reading the migration flow: messaging-settings
still writes MESSAGING_CWD to .env, although runtime configuration documents that
setting as removed in favor of terminal.cwd in config.yaml. Existing migration
test explicitly expects the old setting. No behavior change made during these
moves; add focused regression and handle existing config conflicts/dry-run
before correcting it. Native entry filename and skill documentation remain
unfinished. Full15 predates these OpenClaw slices; no full16 run yet.
Provider extraction terminal: 148 passed in 2.01 seconds; whitespace clean.
Migration entry now 2,015 lines (originally 3,145), with six focused siblings
between 114 and 336 lines. No TUI source changes in this phase.

### OpenClaw workspace and skill copy consolidation

Moved eleven workspace/document/memory/backup/archive methods into
_forecast_migration_workspace.py (327 lines). Exact function ASTs preserved;
focused migration/hardening/CLI/setup suite: 148 passed in 1.99 seconds.
Log /tmp/superforecasting-openclaw-workspace-tests.log.

Moved four skill destination/import methods into _forecast_migration_skills.py
(147 lines before deduplication), preserving exact method ASTs. Focused suite
passed (/tmp/superforecasting-openclaw-skills-tests.log). Then replaced the two
nearly identical copy loops with one _copy_skill_directory helper, preserving
caller-specific report kinds and descriptions. Module now 120 lines. Ruff and
148 focused tests passed in 1.96 seconds after the deliberate deduplication.
Log /tmp/superforecasting-openclaw-skills-dedup-tests.log.

Independent before/after fixture comparison in
/tmp/check-migration-skill-parity.py exercised 12 combinations: workspace/shared
caller, skip/rename/overwrite conflict mode, dry-run/execute. Each contained an
existing conflicting skill, a fresh skill and an existing -imported collision.
All report records and every resulting file byte matched, including backups.
Comparison uses /tmp/forecast-migration-skills-before.py captured before dedup.
No real profile or operator migration was touched.

Entry now 1,610 lines; further configuration/report orchestration decomposition,
native entry filename, MESSAGING_CWD correction and skill guide remain pending.
TUI source unchanged. Goal active, no commit/stage/push or publication.

### Native standalone migration entrypoint

Further exact method moves: ten service/integration methods into
_forecast_migration_integrations.py (347 lines), six preference methods into
_forecast_migration_preferences.py (367 lines), two extended-channel/env methods
appended to channels (351 total), and four report/notes methods appended to
reports (371 total). Every moved method body/annotation/string AST preserved.
Focused suites respectively: 148 passed in 2.00 seconds, 148 passed, and
148 passed in 1.96 seconds. Logs /tmp/superforecasting-openclaw-
{integrations,preferences,final-moves}-tests.log.

Moved the remaining Migrator orchestration class as an exact AST into
_forecast_migration_runner.py (under 400 lines including imports). Removed ten
unused entry imports with explicit Ruff F401. Runner suite 148 passed in
1.98 seconds (/tmp/superforecasting-openclaw-runner-tests.log).

Renamed the now-small entry to openclaw_to_forecast.py. Former filename is a
19-line compatibility launcher with attribute forwarding. Runtime setup/CLI,
primary migration tests and both skill-guide command examples use the native
filename. Claw discovery supports an older installed legacy filename. Shared
loader uses script_path.stem to avoid registering the legacy launcher under its
own native import name. Fresh python -S regression caught that collision as a
RecursionError before the loader correction; red log
/tmp/superforecasting-openclaw-legacy-red.log. Native/fallback discovery cases and
fresh-process legacy import now pass: 151 tests in 2.00 seconds.
/tmp/superforecasting-openclaw-native-green.log.

Broader migration/update/project/packaging consumers: 424 passed, 1 skipped in
29.60 seconds (/tmp/superforecasting-openclaw-native-consumers.log). Ruff, six
import contracts, docgen and whitespace checks passed. Native and compatibility
--help text matches under python -S from /tmp after normalizing command name
and argparse line wrapping; initial bytewise comparison naturally differed in
wrapping from the longer native name. Logs /tmp/superforecasting-openclaw-native-
{help,ruff,contracts,docgen}.log. Runtime ownership guide updated.

No TUI implementation change. Full15 and installed wheel predate this phase;
release rebuild and next full-suite pass still required. Skill guide command
paths updated, but full standards/contents modernization and MESSAGING_CWD fix
remain pending. No staging, commits, pushes, publication or goal completion.

### Correct removed migration workspace setting

Verified runtime/config.py removes MESSAGING_CWD and uses terminal.cwd. Migration
now writes external source workspaces to config.yaml terminal.cwd, preserving
other settings, backing up before execution, respecting overwrite/idempotence,
and keeping dry runs read-only. Malformed or non-mapping target configuration
is reported as an error rather than overwritten. messaging-settings now
participates in the existing configuration conflict block so later config
writes stop after a conflict/error. Workspaces inside the source tree remain
excluded. Telegram env handling is unchanged.

Added tests/skills/test_openclaw_workspace_config.py: six absent/same/conflicting
workspace + execute/dry-run + overwrite cases and three malformed target cases
that verify later model writes are blocked. Updated the old integration test
that had explicitly required the removed setting. Workspace module remains
364 lines. Final focused checks: 160 passed in 2.00 seconds; Ruff and whitespace
clean. Log /tmp/superforecasting-openclaw-workspace-config-corrected.log.

Evidence correction: initial six red results and first green-attempt failures
were test-fixture errors (omitted required output_dir), not meaningful regression
proof. Fixed fixture with output_dir=None. Then independently reinstated the
original pre-refactor migrate_messaging_settings method from the initial
snapshot, only in a temporary pytest plugin. Initial plugin compilation lacked
future annotations; corrected that harness. All six valid workspace tests fail
against the original implementation at the missing config report assertion.
/tmp/superforecasting-openclaw-workspace-config-negative-corrected.log.
Temporary plugin /tmp/migration_legacy_workspace_negative.py does not load in
normal runs and never altered product source. No workers remain from it.

Skill-guide modernization, fresh installed artifact and full16 remain pending.
TUI source unchanged; goal active, no staging/commit/push/publication.

### Migration guide modernization and explicit channel credential consent

Reading the guide against options/code found Discord and Slack token extraction
ignored migrate_secrets. Updated existing channel tests to exercise False/True:
2 failed (no-consent cases), 2 passed before the fix. Both handlers now gate
bot/app tokens on migrate_secrets while preserving allowlists. Focused checks:
162 passed in 2.04 seconds. Logs /tmp/superforecasting-openclaw-channel-consent-
{red,green}.log. This is a behavior fix, separate from prior exact moves.

Rewrote optional skill guide to 182 lines with repository-standard description,
human-first credit, section order, native tools/paths and actual preset behavior.
Removed stale exhaustive lists, repeated prompt choreography and the obsolete
MESSAGING_CWD destination. Clarified existing authorization, global overwrite
scope, missing workspace decisions, raw archive limitations, dry-run output-dir
writes and JSON status/report semantics. Commands point to native entrypoint.
Regenerated the one website skill page and optional catalog via their generator.
Repository metadata/section checks passed; website generation/link tests:
18 passed in 1.17 seconds (/tmp/superforecasting-openclaw-guide-tests.log).
Ruff, docgen and whitespace clean. Codex skill-creator quick_validate rejected
repo-required author/platforms/version fields because it validates a different
Codex schema; retained the repository's explicit metadata requirements and
validated them directly. No user confirmation was needed for authoring.

Follow-up finding: raw service configuration archives and MCP env/header/auth
copying can contain credentials independently of the extraction flag. Guide now
states this limit accurately; further source hardening should be investigated
in isolation while the next full suite runs. Do not claim the flag sanitizes
all arbitrary source documents or copied directories.

Started full16 at /tmp/superforecasting-full-suite-sixteenth.log. Freeze main
production sources until terminal; use a fresh snapshot for further changes.
Fresh wheel/sdist and installed smoke also remain due. No TUI source change,
no staging/commit/push/publication; goal active.

### Native migration release snapshot and installed smoke

Built wheel + sdist in a fresh 4,837-file source snapshot while full16 runs:
marker /tmp/superforecasting-native-migration-release-path. Reused the verified,
unchanged ui-tui/dist/entry.js with SKIP_NPM=1; no main production files touched.
Wheel SHA256 b415eb2c01606ff48f6d282144542ff5ca9d4c0224cd237510c8fdcdacc2f699.
All 13 migration Python files are present and byte-identical to the snapshot;
TUI bundle also byte-identical. Build and inspection logs:
/tmp/superforecasting-native-migration-release-build.log and
/tmp/superforecasting-native-migration-wheel-inspection.log.

Reinstalled that wheel without dependencies into the existing isolated smoke
venv. python -I from /tmp with a temporary home verified installed native script
discovery, setup-loader class identity, an executed fixture workspace migration
writing terminal.cwd rather than .env, and legacy-launcher class identity.
No source import path was injected into that child. Installed helper resolved
to /tmp/superforecasting-wheel-smoke/optional-skills/migration/openclaw-migration/
scripts/openclaw_to_forecast.py. Log
/tmp/superforecasting-native-migration-installed-smoke.log.

Configured installed realPTY chat also terminal exit 0 using the existing local
HTTP fixture; no paid/real provider call. Log
/tmp/superforecasting-native-migration-installed-chat.log. This validates package
transport/rendering, not forecasting quality. Minimal no-deps smoke environment
retains the known optional browser/websockets warning limitation.

Full16 still active (handle 66556), latest observation around 22%. Continue
freezing main production sources until terminal; any new work needs a fresh
snapshot distinct from the immutable release snapshot. No goal completion,
staging/commit/push/publication or TUI source changes.

### Isolated migration configuration credential hardening (pending integration)

Fresh snapshot marker /tmp/superforecasting-migration-credentials-path, separate
from immutable b415eb2c... release snapshot. Main production source remains
frozen for full16. Added test_openclaw_config_credentials.py there: known tokens
in plugin/gateway/skill/deep-channel archives, both secret-flag states, and MCP
env/header/auth dictionaries with both flag states. Baseline 9 failed, 1 passed
(/tmp/superforecasting-migration-credentials-red.log).

Snapshot fix reuses report redaction through write_config_archive at all sixteen
JSON configuration archive writes across integrations, preferences and channels.
Archives always redact recognized credential keys and token patterns. Arbitrary
copied documents/directories remain outside that guarantee. MCP env/headers/auth
are imported only with migrate_secrets; omitted dictionaries get a skipped
report item explaining the required flag. Other server fields are preserved.
Focused tests 172 passed in 2.60 seconds, with original source JSON preserved.
Added assertions for non-secret archived settings too. Broad migration/update/
packaging/website consumers: 463 passed, 1 skipped in 28.25 seconds. Ruff clean;
architecture/docgen results in corresponding logs. Updated snapshot skill guide
and generated page to describe the narrower, accurate guarantee.

Logs /tmp/superforecasting-migration-credentials-{green,consumers,ruff,contracts,
docgen}.log. Pending promotion after full16 terminal: four script modules
(_forecast_migration_reports.py, _forecast_migration_integrations.py,
_forecast_migration_preferences.py, _forecast_migration_channels.py), the new
test, SKILL.md and its generated website page. Do NOT promote the whole snapshot
or its older worklog. Full16 latest observation around 47%, handle66556 active.
No TUI source changes or actual user migration performed.

### Isolated interactive forecast search extraction (pending integration)

Fresh snapshot marker /tmp/superforecasting-cli-forecast-search-path. Baseline
forecast slash-command tests: 5 passed in 3.46 seconds. Moved five methods
(search normalization, dashboard row selection, ranking, result formatting and
reference/rest splitting) into runtime/forecast_search.py (134 lines). Exact
method ASTs and string literals preserved; original classmethod/staticmethod
bindings explicitly retained. Renderer-dependent handlers stay in ForecastCLI.
Root cli.py 14,028 -> 13,912 lines. Added new module to update syntax guard and
appended runtime ownership documentation. 780 CLI/update-guard tests passed in
9.53 seconds. Ruff, six import contracts and docgen passed. Logs
/tmp/superforecasting-cli-forecast-search-{baseline,tests,ruff,contracts,docgen}.log.
Pending promotion: cli.py, runtime/forecast_search.py, runtime/main.py and only
the appended forecast-search paragraph in docs/architecture/runtime-layout.md.
Do not wholesale copy the older guide/worklog from this snapshot.

Also cleaned legacy local identifiers in the separate migration-credentials
snapshot: target_config/target_server/target_key etc. AST equivalence verified
under identifier renaming. Initial system-python tokenization did not descend
into f-string expressions; the AST assertion rejected the preferences edit
before writing it. Re-ran with project Python 3.13 tokenizer to cover those
expressions. Final migration tests 172 passed in 2.52 seconds
(/tmp/superforecasting-migration-native-locals-final.log).
Add _forecast_migration_providers.py to the prior seven-file migration promotion
list (eight total), because its local identifiers were renamed too.

Main full16 still verified running, handle66556, latest log ~96%. Main source
freeze remains. b415eb2c... installed artifact predates only the pending isolated
credential hardening/local renames and forecast-search extraction. No TUI source
changes, publication, staging/commit/push or goal completion.

### Full16 green and combined integration

Full16 terminal exit 0: 29,897 passed, 147 skipped, 48 warnings in 575.27 seconds.
Log /tmp/superforecasting-full-suite-sixteenth.log; JUnit
.test-results/pytest-20260909T232244Z-87435.xml. Last active work was the real
forecast smoke/pilot export subprocess, confirmed running rather than assumed
hung. This suite covers the native migration restructuring, workspace setting
fix and Discord/Slack consent fix; it predates the two isolated pending slices.

After terminal, promoted eight explicit migration files (five modules, new
credential test, skill guide, generated page) and three forecast-search files
(cli.py, new runtime/forecast_search.py, runtime/main.py syntax guard). Appended
only the search ownership paragraph to main architecture guide. Removed two
stale implementation/test-count claims from AGENTS.md. No snapshot worklog or
unrelated stale files copied. Main now includes both isolated slices.

Combined main CLI/migration/update/metadata/website suite running at
/tmp/superforecasting-migration-search-main-tests.log (handle80577). Ruff,
architecture, docgen and whitespace checks launched for the combined tree.
No full suite currently active. Installed b415eb2c... artifact predates this
integration; rebuild remains due. No TUI implementation change, staging,
commit/push/publication or goal completion.
Combined main integration terminal: 1,235 passed, 1 skipped in 36.12 seconds.
Ruff, six import contracts, docgen and whitespace checks passed. No pending
snapshot promotion remains; prior credential/search snapshots are now stale.

### Consistent standalone migration status and JSON redaction

Main command now computes one exit status from report.summary.error and returns
it from both JSON and human-readable modes. The legacy MIGRATION_JSON_OUTPUT
path now applies the same report redaction as --json. Updated skill guide and
generated page to reflect fixed status behavior. Added actual subprocess tests
for missing source and memory overflow with a synthetic credential, across both
output paths. Initial collection failed because pytest import was omitted; after
correcting that test fixture, meaningful baseline: 2 failed, 2 passed. Fixed
suite: 176 passed in 2.12 seconds; Ruff and whitespace clean.
Logs /tmp/superforecasting-migration-output-{valid-red,green}.log.
No actual credentials or profile data used. Full16 predates this and the recent
combined integration; focused main tests cover the new behavior. Fresh release
artifact still due. No TUI source edits, staging/commit/push or publication.

### Refreshed installed artifact after combined migration/search changes

Fresh immutable snapshot marker /tmp/superforecasting-migration-search-release-path.
Wheel + sdist built; wheel SHA256
 d25303a0792e49ee923195c5983f8ab9abb18fc6e93e9ff32dc1e134737c3c8c.
Verified wheel bytes against all thirteen migration Python files, cli.py,
runtime/forecast_search.py and the unchanged TUI bundle. Reinstalled that wheel
into /tmp/superforecasting-wheel-smoke with --no-deps --reinstall.

Installed checks from /tmp under python -I and isolated homes passed: native
migration discovery/setup loader, fixture workspace migration, legacy launcher,
forecast search class/static bindings, reference splitting and JSON missing-source
exit status 1. Configured installed realPTY chat again rendered the local HTTP
fixture response and exited cleanly with Ctrl-C. No real provider calls.
Logs /tmp/superforecasting-migration-search-{release-build,wheel-inspection,
install,installed-smoke,installed-commands,installed-chat}.log.
Artifact now reflects all current production changes. Main full16 remains the
last full-suite result and predates recent integrated slices; focused tests and
installed smokes cover those additions. No full17 active yet. No pending snapshot
promotions. TUI source unchanged, goal active, no commit/push/publication.
