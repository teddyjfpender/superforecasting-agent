### Interactive provider routing ownership

Moved _normalize_model_for_provider and _resolve_turn_agent_config from cli.py
to runtime/interactive_routing.py (150 lines). Exact function ASTs, annotations,
strings and method interface preserved; no callback/renderer or auth-refresh
changes. Root CLI 13,912 -> 13,769 lines. Added syntax guard and runtime ownership
documentation. Baseline provider/fast-mode tests 56 passed in 1.78 seconds;
post-move whole CLI/update-guard suite 780 passed in 7.59 seconds. Ruff, six
architecture contracts, docgen and whitespace clean. Logs
/tmp/superforecasting-cli-routing-{baseline,tests,ruff,contracts,docgen}.log.
Current installed d25303a0... artifact predates only this method move. No full
suite active, no pending snapshot integration, no TUI source change, no staging,
commit/push/publication or goal completion.

### CLI output ownership and forecast command extraction

Moved the contiguous thirteen output-history/printing declarations into
runtime/console_output.py (198 lines). Exact ASTs preserved, including history
rebinding and the contextmanager. Root re-exports function names, not mutable
state. Removed now-unused root deque/prompt-toolkit print imports. Background
printing tests patch the actual new owner; resume display tests inspect its
history buffer. ChatConsole test still exercises the real root class through
the shared output helper. Baseline redraw/background/history tests: 59 passed
in 1.59 seconds. Full CLI + realPTY + update guard: 806 passed in 14.02 seconds.
Ruff, six import contracts, docgen and whitespace clean. Logs
/tmp/superforecasting-console-output-{baseline,tests,ruff,contracts,docgen}.log.

With output ownership separated, moved all eight remaining forecast command/
reference handlers into runtime/forecast_commands.py (215 lines), exact method
ASTs and classmethod descriptors preserved. Uses console_output._cprint directly;
root dispatch still binds the existing method names. Full CLI/update guard:
780 passed in 7.39 seconds. Same quality gates passed. Logs
/tmp/superforecasting-forecast-commands-{tests,ruff,contracts,docgen}.log.
Both modules added to update syntax guard and ownership guide. Root cli.py now
13,403 lines (13,769 before this phase). No Ink/TUI source edits; realPTY suite
covers the console move. Installed d25303a0... artifact predates interactive
routing, console output and command method moves. No pending snapshot promotion.
Started full17: /tmp/superforecasting-full-suite-seventeenth.log, handle12057.
Freeze main production sources until terminal; subsequent edits need a fresh
snapshot. No staging/commit/push/publication; goal remains active.

### Isolated Rich console / credential ownership and banner deduplication

Fresh snapshot marker /tmp/superforecasting-cli-credentials-path. Moved the exact
ChatConsole class AST into runtime/console_output.py (now 245 lines), root class
name re-exported. Whole CLI/update guard: 780 passed in 10.47 seconds. Then moved
_ensure_runtime_credentials exact method AST into runtime/interactive_routing.py
alongside normalization and turn routing, importing shared ChatConsole/_cprint
and retaining logger name cli. No auth/fallback/model/client-reset behavior
changed. Whole CLI + realPTY + update guard: 806 passed in 14.99 seconds.
Logs /tmp/superforecasting-{chat-console,cli-credentials}-tests.log.

In that same snapshot, removed two unreferenced duplicate art constants from
cli.py. AST literal comparison confirms their text exactly matches the active
banner.py definitions; root had no reads of either constant. Active banner logo
constant renamed FORECAST_AGENT_LOGO; legacy environment string remains supported.
Banner/metadata/context-warning checks: 181 passed, 1 skipped in 3.12 seconds
(/tmp/superforecasting-banner-dedup-tests.log). Ruff, six import contracts and
docgen passed (/tmp/superforecasting-cli-credentials-{ruff,contracts,docgen}.log).
Updated ownership guide in snapshot. Both helper modules remain below 400 lines.

Pending promotion after full17 terminal: cli.py, runtime/console_output.py,
runtime/interactive_routing.py, runtime/banner.py, and the two revised paragraphs
in docs/architecture/runtime-layout.md. Do not copy the older snapshot worklog.
Main full17 still active, handle12057, latest log ~33%. Main source remains
frozen. TUI source unchanged; goal active, no staging/commit/push/publication.

### Full17 green, console/credential promotion and visible product banner

Full17 passed: 29,911 passed, 147 skipped, 48 warnings in 606.91 seconds.
Log /tmp/superforecasting-full-suite-seventeenth.log; XML
.test-results/pytest-20260909T234139Z-99221.xml. Promoted pending console,
credential routing, banner constant deduplication and ownership documentation.
A promotion script initially used shortened runtime paths and stopped after
copying cli.py; the prematurely launched focused run was interrupted and is
not validation evidence. Corrected explicit package paths, then reran from
fully integrated sources: 6,145 passed, 9 skipped, 45 warnings in 69.04 seconds
(/tmp/superforecasting-credentials-banner-integrated-retest.log). Ruff, all six
import contracts and docgen passed.

Actual image inspection found both old README and social PNGs still displayed
HERMES AGENT (identical SHA256
75e85ef6fecf5a6227985f2082e5b35331fceff4d8db03720c82a7d9ee8b7eea).
Replaced with editable assets/banner.svg and a derived native-named website PNG;
updated both READMEs and Docusaurus social reference, removed obsolete PNGs.
assets/README.md documents regeneration and font behavior. Impeccable guidance
used for this narrow dark/gold name correction. Desktop 1200 and mobile 390
renders independently reviewed: ship, no clipping or material legibility issue.
Documentation review required no app-wide design-system changes. Metadata/
website checks: 179 passed, 1 skipped in 2.22 seconds. TUI source unchanged.

Fresh wheel+sdist snapshot marker
/tmp/superforecasting-credentials-banner-release-path; wheel SHA256
1d55aafa045d9d737c99bf11c7192346362c27b479205283d534121d2cebfb39.
Verified six packaged CLI/runtime/bundle files byte-for-byte against snapshot;
installed with --no-deps --reinstall in isolated smoke environment. Configured
installed TUI probe pending handle5264, log
/tmp/superforecasting-credentials-banner-installed-chat.log.

Further inspection found empty saved user text crashes resume recap at
splitlines()[0]. Four regression cases (None, empty string/list, audio-only
content) all fail with IndexError in pending credentials snapshot; one-line
fallback keeps the user row and preserves stored content. Focused green run
pending handle86668; log
/tmp/superforecasting-empty-recap-green.log. Only pending source promotion now:
cli.py one-line fallback and tests/cli/test_resume_display.py four cases.
Goal remains active; no staging, commit, push or publication.

### Empty recap correction and focused resume-display ownership

Installed 1d55aafa... configured realPTY test completed successfully: streamed
local fixture response, Ctrl-C exit 0. No paid provider call. Log
/tmp/superforecasting-credentials-banner-installed-chat.log. The artifact
predates the following recap correction and module move.

Four empty-text regression cases reproduced IndexError at splitlines()[0].
Added `or [""]` for the user recap row, retaining the row and original stored
content. Snapshot resume suite: 41 passed in 1.58 seconds; promoted correction
and tests; main focused check 41 passed in 1.87 seconds.
Logs /tmp/superforecasting-empty-recap-{red,green,integrated}.log.
Then moved _display_resumed_history and _render_resume_history_panel_lines as
exact method ASTs (including multiline strings) into
superforecasting_agent/runtime/resume_display.py (186 lines). Imports native
assistant_text and console_output directly; root method bindings preserve API.
Added module to update syntax guard and ownership guide. CLI + realPTY: 802
passed in 13.37 seconds (/tmp/superforecasting-resume-display-module-tests.log).
Ruff, all six import contracts, docgen, and git diff --check passed. Root cli.py
now 13,031 lines; console_output245 and interactive_routing305. No pending source
promotion or active test/build processes. The previous snapshot marker remains
historical and lacks this latest resume module; do not copy its cli.py again.
No new full suite after this isolated change; full17 and integrated6,145 predate
it, while 802 focused tests cover it. No TUI implementation edits. Goal active.

### Browser command ownership

Previous turn classified progress: banner replacement, verified installed TUI,
resume crash correction and native recap module changed authoritative state.
Continued from current tree with no active test/build workers.
Moved _try_launch_chrome_debug (staticmethod preserved) and
_handle_browser_command into superforecasting_agent/runtime/browser_commands.py,
227 lines. Exact method AST comparison passed, including multiline literals.
The module imports native browser_connect helpers, os/time/urlparse directly;
root no longer imports unused CDP helpers. Updated one test patch to the new
lookup owner, preserving the connection assertions. Baseline browser tests16
passed in1.30s. CLI+realPTY802 passed in13.88s after move. Updated syntax guard,
ownership guide and stale command spellings in root docstrings/comments.
Root cli.py now12,816 lines. Logs
/tmp/superforecasting-browser-command-baseline.log and
/tmp/superforecasting-browser-commands-{tests,ruff,contracts,docgen,diffcheck}.log.
Ruff, six import contracts and diffcheck passed. Docgen initially detected the
expected BROWSER_CDP_URL source-owner change in config-and-env; regenerated
reference and reran check successfully (generator has no --help mode; that
invocation regenerated its standard outputs). No pending sources or workers.
Installed artifact1d55aafa... predates resume correction/module and this browser
move; latest full17 also predates them. Focused CLI+realPTY coverage is current.
Goal active; no staging/commit/push. TUI implementation unchanged.

### Goal command ownership and command-module release

Previous continuation was progress (browser module and current focused gates).
Moved four exact ForecastCLI method ASTs (_get_goal_manager,
_handle_goal_command, _handle_subgoal_command, _maybe_continue_goal_after_turn)
into runtime/goal_commands.py299lines. State/judging stays runtime/goals.py.
Moved exact slash-detection helper to central commands.py and re-exported it;
console_output now owns shared _DIM/_RST constants. No continuation/interrupt/
queue behavior changes. Baseline goal checks68passed1.60s; CLI+realPTY+goal model
and TUI gateway checks863passed17.10s. Ruff, six contracts, docgen, diffcheck clean.
Logs /tmp/superforecasting-goal-commands-{baseline,tests,contracts,docgen}.log.
Root cli.py12,514lines. Added syntax guard entry and ownership documentation.

Built fresh wheel+sdist in marker /tmp/superforecasting-command-modules-release-path.
Wheel SHA256 e4392028d12127c1dc8c41fcc39b37a418e1ecf39b83d57205f05c76945ce8f4;
seven source/bundle files verified byte-identical to snapshot. Installed isolated
--no-deps --reinstall; configured realPTY streamed fixture response and Ctrl-C
exit0. Logs /tmp/superforecasting-command-modules-{release-build,installed-chat}.log.
This artifact includes the resume empty-text fix, resume/browser/goal modules.

Full18 started, handle92600, log /tmp/superforecasting-full-suite-eighteenth.log.
Main production sources frozen until terminal; last observed27%. No full-suite
result claimed yet. New independent source-record work in snapshot marker
/tmp/superforecasting-source-records-path. Baseline tests/forecasting running
handle57805, log /tmp/superforecasting-source-records-baseline.log (last15%).
Read source_adapters.py10,193lines and identified54dataclasses (count must use
extractor output, this estimate is not a gate) as bounded domain groups. Prepared
/tmp/extract-source-records.py, NOT YET RUN. It moves frozen records into six
forecasting/sources/*_records.py leaves with exact decorator/class AST checks,
<=400lines each and<=1200total moved lines, keeps old source_adapters imports.
Prepared /tmp/source-records-contract.py; baseline captures fields/type hints,
frozen/repr/asdict/payload and legacy pickle bytes for all actual classes.
Do not run extractor until baseline handle57805 terminal. Main remains unchanged
by source-record work; no source promotion pending yet. Goal active, no git writes.

### Source record split isolated and mechanically verified

Continued by re-polling the same baseline/full-suite handles; both were live.
Forecasting baseline completed: 3,224 passed, 3 skipped in344.18s, including the
real forecast smoke workflow and100-case protocol bundle. Log
/tmp/superforecasting-source-records-baseline.log. No source edits during it.
Ran prepared extractor in source-record snapshot after terminal. All54class
ASTs/decorators match exactly;955lines moved (<1200slice limit). Six leaves:
economic_records244, research_records179, technology_records191,
public_records164, environment_records140, market_records177. Added a one-line
sources/__init__.py. source_adapters.py now9,291lines and retains explicit
re-exports. No fetching/parsing logic moved in this slice. External-name audit
shows records depend only on dataclass and OutcomeSpace outside builtins.
Field/type/frozen/repr/asdict/payload and both legacy/new pickle round trips
passed for54classes. Logs /tmp/superforecasting-source-records-{extraction,contract,ruff,contracts,docgen}.log.
Ruff, six contracts and docgen pass. Snapshot ownership map has one new row.

Post-move tests/forecasting active handle30214, log
/tmp/superforecasting-source-records-tests.log (last35%). Main full18 still live
handle92600, last98%; main source remains frozen. Source record promotion still
pending BOTH test runs. Explicit paths: forecasting/source_adapters.py,
forecasting/sources/ (seven files) and one ownership-map row; never copy snapshot
worklog. Separate packaging snapshot marker
/tmp/superforecasting-source-records-release-path; build active (handle recorded
by tool output), log /tmp/superforecasting-source-records-release-build.log.
No source promotion yet, no git writes, goal active.

### Source records integrated; full18 exposed stale source-location checks

Full18 terminal: 2 failed,29,913passed,147skipped,48warnings in693.71s.
Failures: callable credential source assertion searched cli.py after method moved;
metadata source assertion searched cli.py after goal/recap moves. Updated callable
check to inspect.getsource(ForecastCLI._ensure_runtime_credentials), and metadata
positive AND negative assertions to actual goal_commands/resume_display sources.
The metadata case has several sequential moved-string assertions; completed all
owner updates. Final focused run177passed1skipped2.47s
(/tmp/superforecasting-relocated-source-checks-green.log). No runtime workaround.
Full18 also prints a closed-stream atexit logging error from evidence tally;
confirmed same error in full17, so it predates these changes. Still worth a
separate lifecycle investigation; not silently claimed fixed.

Source-record post-move full forecasting tests:3,224passed3skipped310.96s, including
real smoke/protocol bundle. Main vs snapshot comparison confirms all354fetch/
parse/helper function ASTs unchanged. Promoted source_adapters.py, seven new
sources files, and precisely one ownership-map row. Integrated54record contracts,
ruff, six architecture contracts, docgen, diffcheck pass. No source snapshot
promotion remains. Old snapshot lacks latest main source-location test fixes;
never copy its tests/worklog wholesale.

Source-record release wheel+sdist built in separate marker
/tmp/superforecasting-source-records-release-path. Wheel SHA256
b7b639c81c85fd8f0b9c790ac9ed5fb7c3e7f433032c2278b246bf4f8f7fd59f.
Ten packaged files verified byte-for-byte against snapshot. Installed isolated
--no-deps --reinstall. Installed54record contracts/legacy-pickle loading pass;
configured realPTY streams local fixture response and exits0 onCtrl-C.
Logs /tmp/superforecasting-source-records-{release-build,installed-contract,installed-chat}.log.
Refreshed sdist after copying corrected source-location tests into release
snapshot; verified included tests/test_project_metadata.py bytes match main.
Log /tmp/superforecasting-source-records-sdist-refresh.log. Wheel production
sources unchanged by test fixes. Contract script now gets54names from frozen
baseline JSON, since main no longer defines those classes in source_adapters.

Started full19 after integration/test corrections, handle22881, log
/tmp/superforecasting-full-suite-nineteenth.log. Main production sources frozen
until terminal; use fresh snapshots for any next work. No other live test/build
workers remain. Next candidate: source normalization helpers and package-registry
parsers (pure helpers, no I/O moves yet). Do not infer optional-number behavior
changes are authorized by this note; reproduce a concrete regression first.
Goal active; no staging/commit/push/publication.

### Isolated source value, package-registry, and feed parsing

Fresh snapshot marker /tmp/superforecasting-source-parsers-path. Baseline from
current integrated source-record tree; PyPI/npm CLI+ledger8passed2.77s. Captured
99return/exception cases for shared optional-value helpers. Moved7helpers into
sources/values.py55lines and11PyPI/npm helpers into package_registry.py137lines,
145body lines total; exact function ASTs preserved. All99baseline cases match.
CLI+ledger+extensions428passed80.79s. Logs
/tmp/superforecasting-{package-parsers-baseline,source-parsers-extraction,source-parsers-values,source-parsers-tests,source-parsers-ruff,source-parsers-contracts,source-parsers-docgen}.log.

After those tests finished, moved11RSS/Atom/arXiv/XML helpers into feeds.py133
lines (100body lines), exact ASTs preserved. Removed now-unused email-date
import from adapter facade. News/RSS/Atom/arXiv/PubMed20passed1.68s. Ownership-map
row updated to include parser leaves. Ruff/six contracts/docgen pass.
Logs /tmp/superforecasting-source-feeds-{extraction,tests,ruff,contracts,docgen}.log.

A separate malformed-input regression showed that optional integer counts
containing strings NaN,Infinity,-Infinity,1e999 abort the public GitHub repository
adapter with ValueError/OverflowError; four controls already passed. New
8-case tests/forecasting/test_source_values.py demonstrates the public adapter
retains the record, uses None for an invalid optional count, and preserves its
raw evidence value. Valid red4failed4passed1.41s. Narrow fix catches ValueError/
OverflowError only around int(number) in values._optional_int; values.py58lines.
99-case comparison verifies ONLY four intended integer fallback cases changed;
all other results/exceptions preserved. Source-value/GitHub/PyPI/npm/feed tests
54passed2.29s. Logs /tmp/superforecasting-source-count-{red,green,contract}.log.
This does not claim all optional floats are finite or general payload sanitation.

Pending promotion AFTER full19(handle22881) terminal: forecasting/source_adapters.py
(now9074lines in snapshot), sources/{values,package_registry,feeds}.py,
tests/forecasting/test_source_values.py, and updated ownership-map row. Main
still frozen; last full19log83%, no failure observed yet. No active snapshot
tests remain. Current installed b7b639c8... predates these parser/helper changes.
Previous goal turn was progress (source records integrated, regression checks
repaired, installed behavior verified). Goal active, no staging/commit/push.

### Full19 green and parser integration

Full19 terminal0:29,915passed147skipped48warnings617.33s. Log
/tmp/superforecasting-full-suite-nineteenth.log; XML
.test-results/pytest-20260910T001455Z-23014.xml. The closed-stream atexit logging
error still appears after tests (same as full17/full18), separate from test status.
After terminal, promoted pending source parsers, count regression and ownership
row. Integrated source-value+metadata+callable-key185passed1skipped3.22s.
Log /tmp/superforecasting-source-parsers-integrated-tests.log. No pending source
promotion; source_adapters9074lines. Ruff and architecture/docgen checks passed
in snapshot; main integrated architecture/docgen logs recorded separately.

Investigated evidence._log_leak_domain_tally atexit callback: the traceback is
logging.StreamHandler.emit writing a closed capture stream. Do not suppress the
logger or claim the owning handler is identified yet. Prepared read-only pytest
plugin /tmp/forecast-log-probe/handler_lifecycle_probe.py, recording only handler
class/stream class/closed status/test identity/verbose tag (no log contents).
It does not create loggers or replace handlers. Focused logging+leak evidence
suite57passed1.66s with plugin; no closed handler in that subset. JSONLs under
/tmp/superforecasting-handler-lifecycle-<pid>.jsonl. Need wider run to locate
leaking owner. No logging production changes made.

Fresh release snapshot marker /tmp/superforecasting-source-parsers-release-path;
build handle87407, log /tmp/superforecasting-source-parsers-release-build.log.
Main source frozen again for full20, handle from tool output; log
/tmp/superforecasting-full-suite-twentieth.log. This run includes parser/count
changes and read-only logging probe (-p handler_lifecycle_probe, PYTHONPATH only
adds its temporary directory). Re-poll same handles; no restart on timeout.
Goal remains active; no staging/commit/push/publication.

### Parser release verified; GitHub adapter family isolated

Current parser release wheel SHA256
7b98a879b80f755f358b6cec17cc45f081fe3a925ee3c81968441a76f9f7de2e;
marker /tmp/superforecasting-source-parsers-release-path. Verified13packaged
source/bundle files byte-identical; installed isolated --no-deps --reinstall.
Installed54record contracts and99optional-value cases (only4int fallbacks differ
from original baseline) pass. Configured installed realPTY streamed fixture and
exited0. Logs /tmp/superforecasting-source-parsers-{release-build,installed-records,installed-values,installed-chat}.log.
Full20 still active handle40613; main source frozen. Temporary logging probe
has not yet identified the closed-handler owner; no logging code changed.

Fresh GitHub snapshot marker /tmp/superforecasting-github-source-path. Baseline
GitHub CLI/ledger18passed3.20s. Moved three shared GitHub metadata helpers with
exact ASTs into sources/github_metadata.py54lines. Repository snapshot adapter
moved into github_repository.py96lines; four release/issue/commit/workflow
adapters into github_activity.py331lines. Public source_adapters signatures,
return annotations and docstrings preserved by thin wrappers. Each wrapper
passes the facade's _read_json_endpoint explicitly to its leaf, retaining the
existing HTTP-mocking boundary without a leaf-to-facade import or mutable
reader global. Adapter AST comparison permits ONLY this added keyword-only
reader parameter; all bodies unchanged. Existing helper exports retained.
No behavior change or new source/network capability.

Repository26focused checks passed1.75s; all-family26passed1.82s; broader CLI,
ledger,extensions,tool and value-regression516passed79.98s. Ruff,six architecture
contracts,docgen pass. Logs /tmp/superforecasting-github-{source-baseline,source-extraction,source-tests,activity-extraction,activity-tests,source-broad-tests,source-contracts,source-docgen}.log.
Snapshot source_adapters now8727lines (main still9074). Ownership-map row and a
short adapter-boundary paragraph updated in snapshot.

Pending promotion AFTER full20 terminal: forecasting/source_adapters.py,
sources/github_{metadata,repository,activity}.py, ownership-map row/paragraph.
No active snapshot tests/builds. Current installed7b98a879... predates GitHub
adapter extraction. Do not copy snapshot worklog. Goal active, no git writes.

### Package adapters and obsolete collection-time diagnostic

Full20 terminal0:29,923passed147skipped48warnings589.00s. Log
/tmp/superforecasting-full-suite-twentieth.log; XML
.test-results/pytest-20260910T002708Z-30850.xml. It included the read-only handler
probe. The same atexit error persisted. Probe30863 showed a plain root
logging.StreamHandler bound to _pytest.capture.EncodedFile, verbose tag false;
other workers had only file/pytest handlers. Earlier PID filter>31000 was too
high; actual full20workers were30862/30863/30864/... .

In pending GitHub snapshot, also moved load_pypi_releases and
load_npm_package_versions into sources/package_releases.py197lines. Adapter body
ASTs unchanged except required keyword-only reader injection; public signatures,
return annotations/docstrings unchanged. PyPI/npm8passed1.56s. Updated ownership
map; ruff,sixcontracts,docgen passed. GitHub516broad pass predates these two moves;
package-specific8checks cover them directly.

Identified tests/run_agent/test_interactive_interrupt.py as a MANUAL debug
script (zero collected test functions/classes) with logging.basicConfig at
module scope. No repository references found. A fresh-process import under
redirected stderr reproduced a root-handler/level mutation (temporary regression
1failed1.38s). Initially relocated script and moved logging setup into main;
import regression passed1.36s. Then actually ran the diagnostic in isolated home
with mock/local settings: it fails before child startup with AttributeError
(exit1; /tmp/superforecasting-manual-interrupt.log). The maintained
TestCLISubagentInterrupt.test_full_delegate_interrupt_flow already exercises
this complete scenario, with separate propagation/concurrent tests.
Removed the obsolete script instead of shipping a broken diagnostic. Discarded
the newly created temporary import test, relocated script, and manual-doc section;
NONE reached main. Existing automated tests untouched. Interrupt+logging+leak
checks67passed1.89s with probe. Full-suite confirmation still needed for absence
of the shutdown error. No production logging suppression/level change.

After full20 terminal, promoted GitHub/package leaves, source_adapters facade,
ownership docs, and deleted the obsolete zero-test script. Integrated adapter/
source-value/interrupt44passed2.63s. Ruff,sixcontracts,docgen,diffcheck pass.
No pending source promotion. Current installed7b98a879... predates this family
and diagnostic removal. Fresh release marker
/tmp/superforecasting-adapter-family-release-path; build handle7756, log
/tmp/superforecasting-adapter-family-release-build.log.
Full21 active handle32738, log /tmp/superforecasting-full-suite-twenty-first.log,
with same read-only logging probe. MAIN FROZEN again until terminal. Goal active;
no staging/commit/push/publication. Previous turn was progress (adapter extraction,
regression proof and obsolete-script removal), not a stalled wait.

### Adapter release verification and scholarly-source split

Adapter-family release build7756 completed0. Wheel SHA256
 d37999cbbc1d27ea1703f2ef353a623b7848b3129939963d922135ce08d6c34a.
Verified17 packaged files byte-for-byte against release snapshot, including all
14 source modules, cli.py, source_adapters.py, and the unchanged TUI bundle.
(The wheel stores the bundle at superforecasting_agent/runtime/tui_dist/entry.js;
initial verification lookup incorrectly used the source path, then corrected.)
Installed wheel into isolated /tmp/superforecasting-wheel-smoke. Record contract
54 and value matrix99 passed. Real configured TUI displayed local fixture reply
and Ctrl-C exited0. Logs /tmp/superforecasting-adapter-family-installed-{records,values,chat}.log.
Wheel marker /tmp/superforecasting-adapter-family-wheel-path. No publication.

Full21 still active32738, main production frozen; last seen96percent, launcher
38923 / workers38938-38941. Log /tmp/superforecasting-full-suite-twenty-first.log.
Do not claim shutdown logging fix until terminal result/probe inspection.

Fresh snapshot /tmp/superforecasting-research-sources-path points to
/var/folders/5x/7hym3yzn05z0k_z3g1m17brc0000gn/T/superforecasting-research-sources-u9v4x4ys.
Moved OpenAlex and Crossref loaders WITH their family parsers into
sources/openalex.py150lines and crossref.py188lines. Same explicit JSON-reader
injection as prior families; exact body/helper AST preservation, public
signature/return/docstring preservation. Shared _fred_date/_fred_date_to_iso moved
unchanged into sources/dates.py; facade exports retained. No date-policy change.
Extraction script /tmp/extract-research-sources.py. Ownership docs updated ONLY
in snapshot. Baseline6pass3.53s; targeted CLI/ledger10pass1.98s and extension/tool
4pass1.36s. Ruff, six architecture contracts, docgen pass. Logs
/tmp/superforecasting-research-sources-{baseline,tests,extension-tests,contracts,docgen}.log.
Full forecasting group active61203, log
/tmp/superforecasting-research-sources-forecast-tests.log. This wider check covers
shared date helpers used beyond the two research sources. Not yet promoted.
Pending AFTER both suites terminal and green: source_adapters.py,
sources/{dates,openalex,crossref}.py, ownership-map row and appended paragraph.
Never copy snapshot worklog wholesale. Goal active; no git writes.

### Research promotion, WebSocket fixture repair, and example consolidation

Full21 terminal1:1failed29,922passed147skipped48warnings595.01s. The failure was
TestPtyWebSocket.test_pub_broadcasts_to_events_subscribers, waiting30s to receive
its published frame. The atexit logging error ALSO PERSISTED: deleting the stale
manual diagnostic was valid cleanup but NOT sufficient to fix this error.
Full21 stream handler in worker38939 was still a plain root StreamHandler bound
to pytest's EncodedFile; no verbose tag. Do not claim that issue resolved.

WebSocket class recheck13passed2.14s. Investigated the fixture rather than
increasing timeouts: TestClient(ws.app) without context starts a separate portal
loop per websocket. Temporary /tests/runtime_cli/test_websocket_loop_probe.py
in adapter-family RELEASE snapshot proved subscriber/publisher loops differ
(deterministic1failed2.22s). Context-managed TestClient proves same-loop and all
13existing tests pass (14total3.11s). Promoted ONLY fixture change in
main tests/runtime_cli/test_web_server.py: with TestClient as client, assign and
yield. Production endpoint unchanged. Entire main web_server tests155pass5warn
2.69s. Temporary probe did not enter main. Evidence logs
/tmp/superforecasting-websocket-{failure-recheck,loop-red,loop-green,integrated-tests}.log.

Research snapshot full forecasting group terminal0:3232passed3skipped304.73s.
Promoted source_adapters.py, sources/{dates,openalex,crossref}.py, ownership map.
No pending research-source promotion. Main ruff,sixcontracts,docgen,diffcheck pass.

Root datagen-config-examples consolidated under examples/trajectories:
example_browser_tasks.jsonl, trajectory_compression.yaml byte-preserving moves;
run_browser_tasks.sh moved with native home/path comments and set -euo pipefail.
Temporary fake-python worker exiting7 reproduced old shell exit0 plus Done banner;
new shell exits7 and omits success banner. Logs
/tmp/superforecasting-browser-example-{red,green}.log; probe script
/tmp/probe-browser-example.py. Bash syntax passes; no paid/browser work executed.
Removed unreferenced web_research.yaml: advertised batch --config and WebResearchEnv
which the actual batch CLI does not implement. Added examples/trajectories/README.md
with supported research distribution arguments and explicit compression --config.
Verified dataset rows, CompressionConfig.from_yaml, and documented signature/
distribution names against actual code. README and data_generation guide link new
examples. No model/runtime dependency changes; no modification of user cli-config.yaml.

Enhanced TEMP handler probe to annotate newly constructed plain StreamHandlers
with stack traces, record newly seen handlers after each test (not just closed).
Collection-only first attempt failed because runtime import treated pytest -p
as profile; reran with PYTEST_PLUGINS env instead:30069/30071collected2deselected
19.96s, no collection error. No production workaround added. Collection did not
show leaked stream; likely test execution origin, now being traced.
Full22 active59335, log /tmp/superforecasting-full-suite-twenty-second.log,
launcher47589, XML pytest-20260910T010142Z-47589.xml. MAIN PRODUCTION FROZEN.
Fresh release snapshot/build active99731, marker
/tmp/superforecasting-research-release-path, log
/tmp/superforecasting-research-release-build.log. Existing installed d37999... wheel
predates scholarly split/example consolidation. Goal active; no staging/commit/push.

Fresh research release build99731 terminal0. Wheel
1a3333d374ea697664b7e63319d8bc41f7911881e4f7953529caba88baf1285a;
20packaged files byte-verified including all sources and unchanged TUI bundle.
Installed into isolated smoke venv;54record/99value contracts passed. Configured
TUI local fixture response rendered and Ctrl-C exit0. Logs
/tmp/superforecasting-research-installed-{records,values,chat}.log; wheel marker
/tmp/superforecasting-research-wheel-path. No publication.

Continued example failure investigation in completed RESEARCH RELEASE snapshot
/var/folders/5x/7hym3yzn05z0k_z3g1m17brc0000gn/T/superforecasting-research-release-cu0vtsd_.
Batch CLI validation paths returned None and fatal handler returned1; Fire prints
a return value rather than using it as process exit status. Eight real subprocess
regressions all reproduced status0 for invalid/missing arguments, bad prefill,
and missing dataset. Narrow fix in trajectories/batch_cli.py raises SystemExit(2)
for six validation returns and SystemExit(1) for fatal exception. Successful
list/run paths unchanged. Added tests/trajectories/test_batch_exit_status.py with
8subprocess cases, isolated paths, no model/network calls. Red8failed2.98s;
all trajectories80passed3.39s; ruff and actual --list_distributions exit0.
These initial snapshot tests used fallback Python3.11.15 because release snapshot
had no .venv. Added snapshot-only .venv symlink to main Python3.13.12 and rerunning
same domain now90445; log /tmp/superforecasting-batch-exit-python313.log.
Earlier logs /tmp/superforecasting-batch-exit-{red,green}.log; list log
/tmp/superforecasting-batch-list-success.log. Not promoted while full22 runs.
Pending promotion: ONLY superforecasting_agent/trajectories/batch_cli.py and
new tests/trajectories/test_batch_exit_status.py from this release snapshot.
Built wheel predates this pending fix even though source snapshot now contains it.

Full22 still active59335 (main freeze); expanded handler trace has not yet shown
plain root stream creation at last observed34percent. Prior turn made concrete
progress through verified promotions, test fixture repair, root organization,
installed release validation, and pending red/green CLI error fix. Goal active.

### Root logging leak identified and gateway lifecycle fix prepared

Batch exit-code snapshot recheck on main Python3.13.12:80passed3.55s,
/tmp/superforecasting-batch-exit-python313.log. Ready for promotion after full22.

Full22 handler trace identified the actual remaining plain StreamHandler origin:
worker47602 after tests/gateway/test_runner_startup_failures.py::
test_start_gateway_verbosity_imports_redacting_formatter. Constructor stack goes
to gateway/run.py:start_gateway, line18961. Gateway adds a root stderr handler
and leaves it installed on clean early return, failed start, or exception.
This is a production lifecycle leak (also duplicates retry output), not merely a
pytest capture issue. Earlier manual diagnostic deletion remains valid obsolete
script cleanup, but was not the complete root-cause fix.

Prepared fix in current research RELEASE snapshot (same as pending batch fix).
Expanded existing verbosity regression across None/0/1/2 and clean/failed/exception
startup outcomes. Captures handler list/level after return, restores fixture state
even on red so the regression itself cannot contaminate later tests. Red9failed
3passed1.79s; after fix12passed1.65s. gateway/run.py now initializes optional
handler/root-level bookkeeping and wraps the existing remainder of start_gateway
in try/finally. Removes/closes ONLY its own stderr handler on exit; restores a
lowered root level only if it still equals the level this invocation chose.
All remaining gateway lifecycle body ASTs unchanged inside try; no startup,
signal, PID, adapter, or shutdown policy changed. Compared whole-module AST:
only start_gateway differs. No logger suppression or broad handler removal.

Entire snapshot tests/gateway:5750passed53skipped2warnings65.83s; ruff clean.
Logs /tmp/superforecasting-gateway-stderr-{red,green,domain}.log.
Pending promotion AFTER full22 terminal: gateway/run.py and
 tests/gateway/test_runner_startup_failures.py, plus prior pending batch_cli.py
and test_batch_exit_status.py. Main still frozen; full22 active59335 last92percent,
one E marker not yet explained (wait for terminal traceback). Full22 necessarily
predates this gateway fix. Use an uninstrumented full23 after promotion; the
logging constructor trace has served its diagnostic purpose.

Full22 terminal1:1failed29,921passed147skipped48warnings1error604.75s.
Failure: TestNavigationSessionKey.test_public_url_uses_bare_task_id performs live
socket.getaddrinfo for github.com and exceeded30s. Setup error in following
TestWebExtractSecretExfil.test_blocks_api_key_in_url was ResourceWarning for an
unreaped agent-browser Popen52484, not a failure in secret-exfil validation.
Do not conflate them or call full22 green. Enhanced logging probe itself did
not fail; trace conclusively found gateway handler origin. Full22 still emitted
known atexit logging error (it predates prepared gateway fix).

After terminal, promoted gateway/run.py + expanded startup tests, batch_cli.py +
8exit-code subprocess regressions. Added deterministic public-address DNS result
ONLY to the public-host routing test (routing/private-IP logic still exercised;
no production DNS/SSRF changes). Focused combined routing, exfil, startup and
trajectories130passed4.54s. Ruff, sixcontracts, docgen, diffcheck pass.
Logs /tmp/superforecasting-lifecycle-integrated-{tests,ruff,contracts,docgen,diffcheck}.log.

Discovered inherited .gitignore examples/ rule hid new trajectory examples.
Changed to /examples/* with explicit exceptions for known forecasting and
trajectories source directories. git status now shows ?? examples/trajectories/;
no previously ignored forecasting files appeared. No staging/commit performed.

No pending source promotion now. Fresh uninstrumented full23 active99475,
/tmp/superforecasting-full-suite-twenty-third.log. MAIN PRODUCTION FROZEN again.
Need verify no shutdown logging error. Browser subprocess cancellation/lifetime
still deserves investigation: both Popen wait sites in tools/browser_tool.py
handle subprocess.TimeoutExpired with kill+wait but unexpected interruption can
bypass that cleanup. ResourceWarning from full22 remains unresolved; focused
130checks passed but do not prove all browser subprocess lifetimes. Existing
installed research wheel1a3333... predates gateway/batch lifecycle fixes. Goal
active; prior turn made actual diagnosed/fixed/tested/promoted progress.

### Browser child-process interruption regression

Fresh browser snapshot marker /tmp/superforecasting-browser-lifecycle-path:
/var/folders/5x/7hym3yzn05z0k_z3g1m17brc0000gn/T/superforecasting-browser-lifecycle-tmxga30q.
Main remains frozen under full23 active99475 (last38percent).

Both tools/browser_tool.py command paths only killed/reaped children on
subprocess.TimeoutExpired. Added a six-case regression using REAL local Python
children (never agent-browser/browser/network/model): primary and temporary Chrome
fallback paths x KeyboardInterrupt, unexpected TimeoutError, normal command timeout.
Popen launch seam substitutes a sleeping Python child; first wait raises chosen
exception. Test inspects returncode before its own safety cleanup; finalizer always
kills/reaps intentionally leaked red-control children. Existing normal-timeout
cases passed; unexpected timeout/interrupt cases4failed2passed1.89s.

Minimal fix introduces shared _wait_browser_process: wait, kill+wait on any
BaseException, then re-raise. Both existing sites use helper; remove duplicate
kill+wait from timeout handlers, preserving existing timeout error responses.
No navigation, provider, routing, SSRF, or fallback policy changes. Whole-module
AST diff limited to two command functions and new wait helper. Red/green sixcases
now6passed1.28s. All browser modules331passed22skipped16.01s; ruff clean.
Logs /tmp/superforecasting-browser-process-{red,green,domain}.log.
This proves the lifecycle bug, but does not yet prove full22's delayed warning
had this exact interruption trigger; verify the combined full suite after promotion.

Pending promotion AFTER full23 terminal: tools/browser_tool.py and new
 tests/tools/test_browser_process_interrupt.py from browser snapshot. No other
pending snapshot changes. Existing installed research1a3333... wheel still
predates gateway/batch fixes and this pending browser fix. Goal active.

### Open-Meteo source ownership

Continued in browser-lifecycle snapshot after its browser checks completed.
Open-Meteo daily forecast, air-quality forecast, and historical-weather loaders
plus seven family helpers moved into sources/openmeteo.py327lines. Adapter body
ASTs identical except explicit keyword-only JSON-reader injection; helper ASTs
unchanged. Facade retains every signature, return annotation, docstring and
private helper export. No weather/date/value policy changes or new API calls.
Extraction /tmp/extract-openmeteo-sources.py; source_adapters8319→8090lines.
Ownership-map row/paragraph updated ONLY in snapshot.

Existing CLI/ledger/extensions/tool weather checks baseline11passed2.70s,
post11passed1.62s. Ruff, six architecture contracts, docgen pass. Full forecasting
domain active23193, log /tmp/superforecasting-openmeteo-domain.log. Other logs
/tmp/superforecasting-openmeteo-{baseline,tests,contracts,docgen}.log.
Main still frozen under full23 active99475; last seen80percent, no terminal result.

Pending promotion after relevant terminal gates: existing browser_tool.py +
test_browser_process_interrupt.py, AND source_adapters.py + sources/openmeteo.py
+ ownership-map row/appended paragraph from browser-lifecycle snapshot. Snapshot
worklog is stale; do not copy it. No release build includes these pending changes.
Goal active; no git staging/commit/push.

### Native ACP implementation and removal of test-only dashboard plugin

Full23 terminal0:29,942passed147skipped48warnings623.61s, XML
.test-results/pytest-20260910T011332Z-55372.xml. No Logging error, closed-file,
unreaped-process warning, failures, or errors in log. Gateway handler lifecycle
fix is confirmed by uninstrumented full-suite shutdown. Browser interruption
fix was not yet included, so this run alone does not cover that pending change.

Open-Meteo snapshot full forecasting domain3232passed3skipped323.18s. Promoted
browser wait helper + six real-child regressions and Open-Meteo family + ownership
docs after both terminal gates.

Fresh ACP snapshot /tmp/superforecasting-acp-native-path ->
/var/folders/5x/7hym3yzn05z0k_z3g1m17brc0000gn/T/superforecasting-acp-native-fb4wxs0u.
Baseline275passed4.32s. Canonical class ForecastACPAgent and AGENT_VERSION now own
implementation; HermesACPAgent/HERMES_VERSION remain compatibility aliases. Entry
constructs canonical class, uses native version/main locals and load_forecast_dotenv
(the same implementation old wrapper called), preserving home keyword compatibility.
Fixed package protocol expansion to Agent Client Protocol. Native class used in
server tests, legacy MCP tests still exercise alias; added identity/value regression.
Historical transcript fixture containing HermesACPAgent remains unchanged.
Class method ASTs identical after version-identifier normalization and docstring
exclusion. ACP+env283passed3.49s. Updated ACP guide, README/ownership rows, and
metadata version-template assertion (negative old-product check now independent
of constant name). Ruff, sixcontracts,docgen pass. Promoted explicit paths, only
metadata assertion edits rather than replacing stale entire metadata test.

ACP snapshot metadata initial2fail159pass1skip because rsync --exclude dist had
omitted tracked plugin dashboard JS files. Copied required files from MAIN and
recheck161passed1skip1.97s. This exposed a release-snapshot validation gap:
earlier temporary wheels (including 1a3333...) omitted plugin dashboard dist
assets even though their TUI and checked source bytes were valid. Source repo
and production build recipe retain them; temporary snapshot copying was wrong.
Do not describe prior temporary wheel as fully complete. Corrected fresh-copy
recipe to exclude ONLY /dist/ and /build/ at root plus ui-tui/dist/ (then copy
verified TUI bundle). Nested tracked plugin dist assets now retained explicitly.
No need to change production packaging rules, which already include them.

Found plugins/example-dashboard contains only an auth-test hello endpoint and a
manifest pointing at nonexistent JS. It was nevertheless auto-discovered as a
product dashboard plugin. Existing auth test now uses real read-only
/api/plugins/kanban/config, checks unauthenticated401, authenticated200 and actual
render_markdown default. Added assertion example is absent from default discovered
plugins: red1failed7passed1.61s. Deleted its two tracked test-only source files;
no example plugin ships. Kept auth middleware and real plugin routing unchanged.
Source subtree may retain ignored __pycache__; no source files remain.

Integrated web server + ACP + metadata + browser process regressions598passed
1skipped5warnings5.63s. Ruff,contracts,docgen,diffcheck pass.
Logs /tmp/superforecasting-{acp-native-*,dashboard-fixture-red,weather-acp-*}.log.
No pending source promotion. Fresh uninstrumented full24 active71220, log
/tmp/superforecasting-full-suite-twenty-fourth.log. MAIN PRODUCTION FROZEN.
Corrected release snapshot/build19638 active; marker
/tmp/superforecasting-native-acp-release-path ->
/var/folders/5x/7hym3yzn05z0k_z3g1m17brc0000gn/T/superforecasting-native-acp-release-v5q487i4.
Build log /tmp/superforecasting-native-acp-release-build.log. Verify plugin JS/CSS
bytes alongside source/TUI and absence of example plugin before install smoke.
Goal active; no staging/commit/push/publication.

Corrected native-ACP release build19638 terminal0. Wheel SHA256
f4a65085b93ad692989f844c73dfb5d0382d8f304d0d2d11132680c8516f28ce.
Verified EVERY .py under the eleven declared package roots plus root cli/run_agent:
905Python files, four plugin JS/CSS assets, and unchanged TUI bundle match snapshot
bytes; none missing. Example-dashboard package absent. Source archive also checked
for all four plugin assets and absence of example-dashboard. This supersedes the
incomplete earlier temporary release snapshots for packaging evidence.
Marker /tmp/superforecasting-native-acp-wheel-path.

Installed wheel in isolated smoke venv;54record and99value contract checks pass.
TUI local fixture rendered response and Ctrl-C exit0. Initial installed ACP alias
check correctly reported missing optional acp dependency (base smoke env had none).
Installed declared project extra dependency agent-client-protocol==0.9.0 only in
smoke venv, then isolated-home/cwd/tmp/-I checks passed: native/legacy class and
version aliases identical, python -m acp_adapter --check prints native success.
No model/provider network calls, publishing, or global environment changes.
Logs /tmp/superforecasting-native-acp-{installed-records,installed-values,installed-chat,installed-alias,installed-check,extra-install}.log.
Main full24 still active71220, last34percent; no source mutation since launch.
No pending source promotion. Goal active.

### ACP content boundary and bounded image reads

Fresh snapshot /tmp/superforecasting-acp-content-path ->
/var/folders/5x/7hym3yzn05z0k_z3g1m17brc0000gn/T/superforecasting-acp-content-wnizbd_9.
Uses corrected snapshot exclusions retaining tracked plugin bundles.
Both ACP test directories matter: tests/acp/ and tests/acp_adapter/ (the latter
contains multimodal/resource conversion coverage). Baseline295passed5.19s.
Moved13 functions+3constants exactly by AST into acp_adapter/content.py374lines;
server keeps explicit re-exports and existing class/protocol logic. Existing
resource logger channel acp_adapter.server retained without importing server.
Removed now-unused server imports; collapsed only whitespace left by the moved
block. Server1954→1617lines. Post-move295passed4.40s. Extraction script
/tmp/extract-acp-content.py. Fresh direct content import loads neither server,
session manager nor run_agent entrypoint (verified snapshot __file__).

Separate real limit bug found during review: image resource pre-check uses stat,
then reads without a bound. A growing image bypasses cap. Regression uses an actual
525312-byte file with stale stat size1 and records actual read position: red1failed
1.17s. Fix reads cap+1 and returns existing-style oversized-image text if the
sentinel byte is present; ordinary pre-stat oversized handling unchanged. Test
asserts BOTH bounded bytes read and rejection of oversized multimodal content.
All ACP296passed3.22s. New content module384lines, still below size bar. Logs
/tmp/superforecasting-acp-{content-baseline,content-tests,image-limit-red,image-limit-green,content-ruff,content-contracts,content-docgen}.log.
Ruff,sixcontracts,docgen pass. Updated ACP guide/ownership row only in snapshot.

Pending promotion AFTER full24 terminal: acp_adapter/server.py,
acp_adapter/content.py, tests/acp_adapter/test_resource_limits.py, ACP guide section,
ownership-map ACP row. Main full24 active71220 last99percent, not yet terminal.
Existing corrected f4a650... installed wheel predates this pending content split
and image-bound fix. Goal active; no staging/commit/push/publication.

Full24 terminal0: 29949passed147skipped48warnings577.84s. Log /tmp/superforecasting-full-suite-twenty-fourth.log; XML pytest-20260910T012925Z-64471.xml. Promoted the five reviewed ACP content paths after suite completion.

### ACP installed artifact and history boundary

Integrated content checks:296passed3.32s; Ruff,six import contracts,docgen pass.
Corrected fresh release snapshot /tmp/superforecasting-acp-content-release-path.
Wheel marker /tmp/superforecasting-acp-content-wheel-path; SHA256
c0f7cf50cea7df5655cf920f62866cc6c1ec2192b12d5795b4d71cb85e5ec4ca.
Verified906 Python files across11package roots+twoentrypoints, all4pluginassets,
unchanged TUI, and absence of example-dashboard. sdist retains pluginassets too.
Installed isolated smoke venv: native ACP alias/content conversion/check passed;
real TUI local fixture response and Ctrl-C exit0. Build and chat logs
/tmp/superforecasting-acp-content-release-build.log and
/tmp/superforecasting-acp-content-installed-chat.log. This wheel predates history
extraction below, but includes bounded resource reads.

Moved eight session-history replay methods from server into history.py213lines,
with exact AST including static/classmethod decorators and docstring literals.
Server1433lines; class-body bindings preserve self/cls override dispatch.
First extraction assertion caught dedent changing multiline docstring whitespace;
no source was written before that assertion. Corrected script preserves all
multiline string tokens before writing. /tmp/extract-acp-history.py.
No functional change. Both ACP directories296passed3.11s after extraction;
Ruff,sixcontracts,docgen,diffcheck pass. Logs
/tmp/superforecasting-acp-history-{tests,contracts,docgen}.log.
ACP guide and ownership map now describe history replay. All changes main;
no pending snapshot promotion, no staging/commit/push/publication.
Full25 begins after these changes; freeze main production until terminal.

### EIA adapter boundary and credential-bearing evidence URLs (pending)

Fresh snapshot /tmp/superforecasting-eia-source-path ->
/var/folders/5x/7hym3yzn05z0k_z3g1m17brc0000gn/T/superforecasting-eia-source-i2se5bsq.
Baseline EIA7passed1skipped5.70s. Exact move of adapter body (explicit JSONreader
injection only) plus4helper ASTs into sources/eia.py210lines. Public signature,
return annotation, docstring, helper exports retained. Postmove7passed1skip2.06s.
Script /tmp/extract-eia-source.py. No FRED extraction attempted: its fallback
callbacks would require a separately designed slice to preserve facade patches.

Inspection found EIA request endpoint (including api_key) copied into source_url
on evidence records. Three dummy-key regressions fail before fix: explicit key,
keyed URL, URL with encoded/duplicate keys and an empty nonsecret query field.
Red3failed1.22s. Regression serialization corrected to dataclasses.asdict (records
have no to_payload method); failing URL assertion preceded that serialization.
Fix strips api_key query fields at shared EIA record construction, retains
request URL authentication and all other query pairs. Green10passed1skip.
Tests assert both authenticated outbound request and credential-free returned
record serialization; no external API calls or actual secrets. Does not claim
redaction of arbitrary user-entered source strings or server-echoed payloads.

Updated snapshot ownership map. Ruff/contracts/docgen and full forecasting domain
running handle57266; log /tmp/superforecasting-eia-domain.log. Main production
remains frozen for full25 handle16590. Pending promotion only after both terminal:
forecasting/source_adapters.py, forecasting/sources/eia.py,
tests/forecasting/test_eia_credentials.py, ownership-map EIA additions.
Do not copy snapshot worklog. Installed c0f7cf... wheel predates ACP history and
all EIA work. Goal active.

### ACP dead renderer and internal names (pending)

Snapshot /tmp/superforecasting-acp-cleanup-path ->
/var/folders/5x/7hym3yzn05z0k_z3g1m17brc0000gn/T/superforecasting-acp-cleanup-htp1v5p3.
Repository-wide Python/Markdown search found _build_patch_mode_content only at
its definition. Active patch starts use edit_diff from the approval path or a
preparation note; existing tests verify both cases. Deleted unused64-line V4A
renderer (no change to active unified-diff parser). Renamed private permission
mapping identifiers to runtime, and local session DB home variable to agent_home.
Changed tool comments/docstrings to agent naming; clarified dynamic home docs.
No wire/auth identifier changes: documented hermes-setup compatibility retained.
ACP296passed5.39s, Ruff and sixcontracts pass. Logs
/tmp/superforecasting-acp-cleanup-{tests,ruff,contracts}.log.

AGENTS tree in snapshot now groups tooling under its actual package and replaces
nonexistent example plugin listings with actual bundled plugin names. No policy
changes. Pending promotion after main full25 terminal: acp_adapter/tools.py,
acp_adapter/permissions.py, acp_adapter/session.py, AGENTS.md. This snapshot has
no EIA edits; promote only named paths and preserve worklog/ownership-map changes.
Main full25 still active16590 last72percent; EIA domain57266 last93percent.

EIA full domain terminal0:3235passed3skipped346.14s.
/tmp/superforecasting-eia-domain.log; snapshot XML pytest-20260910T014953Z-74268.xml.

### Combined candidate release verified

Fresh corrected snapshot /tmp/superforecasting-energy-acp-release-path overlays
only named EIA and ACP cleanup paths onto current main. Build passed.
Wheel marker /tmp/superforecasting-energy-acp-wheel-path; SHA256
065baeaa2fca7fae0f9df09b058d121c6a95e5da95ed249a8f678a802e2bd865.
908 Python files across11package roots+root entrypoints byte-match snapshot;
4plugin JS/CSS assets and unchanged TUI verified; no example-dashboard.
Sdist also verified for4pluginassets and absence of example-dashboard.
Installed in isolated smoke venv. Native/legacyACP aliases and class-bound history
replay pass; authenticated EIA request retains dummy key while serialized evidence
omits it. Real installed TUI local fixture response +Ctrl-C exit0. Metadata suite
164passed1skip3.58s against release snapshot, including actual built assets.
Logs /tmp/superforecasting-energy-acp-{release-build,installed,installed-chat,metadata}.log.
This candidate includes pending paths; main still frozen for full25 (last97%).

Full25 terminal0:29950passed147skipped48warnings667.90s. XML pytest-20260910T014642Z-72524.xml; /tmp/superforecasting-full-suite-twenty-fifth.log. Promoted the eight named EIA/ACP/guide paths after terminal. No pending promotions. Candidate wheel065bae... matches these promoted files.

Integrated EIA/ACP/metadata checks463passed1skipped5.71s:
/tmp/superforecasting-energy-acp-integrated.log. source_adapters7938lines,
EIA215lines, ACPtools1291lines. Ruff,sixcontracts,docgen,diffcheck all pass.

### ACP first-save provider metadata

Review of remaining session persistence found first insert only writes cwd,
while subsequent saves write full session_meta. Existing restoration test did
an extra save and concealed provider loss on the first persisted record.
Parametrized that test with/without extra save, checks provider/base_url/api_mode,
and closes its real SessionDB via contextlib.closing. Red1failed1passed1.02s:
first-save restoration incorrectly selected openrouter after global config changed
from anthropic. One-line fix passes existing session_meta to create_session,
matching subsequent writes. Green fullACP297passed3.10s. No live provider calls.
Logs /tmp/superforecasting-acp-first-save-{red,green}.log.
All changes main, no pending promotion. Candidate065bae... wheel predates this
one-line persistence fix; all other candidate changes have been promoted.
Full26 launching for integrated EIA and ACP changes; freeze main production until
terminal. Goal remains active; no staging/commit/push/publication.

### Native provider overlay catalog (pending)

Snapshot /tmp/superforecasting-provider-catalog-path ->
/var/folders/5x/7hym3yzn05z0k_z3g1m17brc0000gn/T/superforecasting-provider-catalog-eqroeu65.
Full runtime_cli baseline5168passed8skipped45warnings67.93s.
Moved overlay class+35-entry catalog by exact AST before renaming into
runtime/provider_overlays.py193lines. Canonical ProviderOverlay/PROVIDER_OVERLAYS;
providers facade retains HermesOverlay/HERMES_OVERLAYS aliases. Updated internal
model_switch consumer and11test consumers/patch targets to canonical names.
Existing metadata source="hermes" preserved for compatibility. One alias identity
test added; no provider values/endpoints/auth modes changed. All35 dataclass
payloads match pre-move baseline; old pickle resolves via class alias and new
pickle round-trip passes. /tmp/provider-overlay-contract.py, baseline JSON and
legacy pickle under /tmp/superforecasting-provider-overlays-*.

Extraction script /tmp/extract-provider-catalog.py. First attempt failed after
catalog write because rg without an explicit search path read inherited stdin.
Restored snapshot providers.py from frozen main, fixed rg to search '.', reran.
No main source edits. Ruff,sixcontracts,value/pickle checks pass. Domain tests
running97945 (/tmp/superforecasting-provider-catalog-tests.log), last59percent.
Pending paths listed /tmp/superforecasting-provider-catalog-changed-paths (14),
plus ownership documentation still to update. Main full26 active68005 last33%.
Do not copy snapshot worklog. No EIA/ACP pending; those changes already main.

Provider catalog domain terminal0:5169passed8skipped45warnings65.41s. Snapshot XML pytest-20260910T020309Z-83543.xml. Ownership map row added; docgen check passes. Pending path list now15 entries at /tmp/superforecasting-provider-catalog-changed-paths. Promote only after main full26 terminal; all snapshot checks terminal green.

### Complete provider data/resolution split (supersedes pending leaf name)

The existing alias,label,transport tables and ProviderDef fit with overlay data:
completed four additional exact AST moves inside the same pending snapshot.
Final leaf is runtime/provider_catalog.py360lines (provider_overlays.py was an
unpromoted intermediate and no longer exists). providers.py372lines retains
resolution logic and explicit data exports. Removed empty section headings and
unused imports. All catalog values unchanged; old/new ProviderDef pickles and all
three tables match independent main baselines, in addition to35overlay checks.
Script /tmp/finish-provider-catalog.py; value verifier updated.
Pending15-path manifest updated to provider_catalog.py; ownership row updated.
Runtime CLI post-final-split running92265; complete gates running62020.
Logs /tmp/superforecasting-provider-catalog-complete-{tests,values,ruff,contracts,docgen}.log.
Main full26 remains active68005; do not promote before terminal.

Final provider split domain5169passed8skipped45warnings67.89s.
Snapshot XML pytest-20260910T020621Z-86710.xml. All complete gates pass.
After tests only removed empty transport heading and corrected module docstring
catalog location; resolution facade now369lines, catalog360lines.
Built release inside tested snapshot after copying unchanged mainTUIbundle.
909 Python files+4pluginassets+unchangedTUI byte-verified; noexample-dashboard or
intermediate provider_overlays.py in wheel. Marker
/tmp/superforecasting-provider-catalog-wheel-path. SHA256
236a03685bd37ba70880c0c5be68d2fa6f959125a9fb6f0161ae5de699ba67ec.
Installed smoke venv; installed provider catalog/pickle checks and ACP first-save
DB metadata checks launched; TUI probe active72401. Logs
/tmp/superforecasting-provider-catalog-{release,installed,installed-chat}.log.
Main full26 active68005; pending15provider paths remain isolated.

Installed provider/pickle/first-save metadata checks pass; real installed TUI local fixture response +Ctrl-C exit0 passed (72401 terminal0). Full26 last96%; no main promotion yet.

Full26 terminal0:29954passed147skipped48warnings624.99s, XML
pytest-20260910T020010Z-81383.xml; log /tmp/superforecasting-full-suite-twenty-sixth.log.
No logging-error/closed-file/ResourceWarning lines found. Promoted15 provider
catalog paths after terminal; installed236a... candidate covers those changes.
