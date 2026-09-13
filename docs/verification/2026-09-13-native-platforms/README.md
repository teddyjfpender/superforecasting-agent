# Native platform qualification

## Recovered receipts

These receipts concern commit `59d8044f047ba0056ee69d21c8fa376b5b987701`, not
subsequent ConPTY changes. Workflow run: `34754775714` in
`teddyjfpender/superforecasting-agent`.

- `previous-linux-x86_64.json`: artifact `10317215140`, native Ubuntu x86-64,
  Node 22. Fresh backend lifecycle, local terminal and authenticated headless
  reconnect/termination checks passed. Upgrades were not requested.
- `previous-windows.json`: artifact `10315904790`, native Windows AMD64,
  Node 22, job `103717202181`. Backend lifecycle passed; the terminal was skipped;
  headless verification failed because `Path.home()` could not determine a home.

The failure came from eagerly resolving standard roots despite an explicitly
configured absolute profile. The runtime now accepts that service configuration;
the isolated Windows test environment also provides USERPROFILE and temporary
paths. Regression tests cover all three supported home variables.

## New native qualification

Run `34759724958`, source commit `0c451ec54111b1d027d43caaec7809cca42c5ed4`:
Linux x86-64 passed on Node 20 and 22 (artifacts `10318865538` and
`10318726206`, corresponding JSON receipts here). Windows jobs `103730307033`
and `103730307059` passed the real Ink cancellation/resume test and 41 other
focused tests; the low-level cooked-input fixture raised EOFError on Ctrl-C.
The fixture now uses raw input, matching the TUI. Subsequent qualification also
runs installed-product checks independently when a focused test fails and
preserves JUnit/log artifacts.

Run `34760876242`, source commit `61dfafa025555d6ff576ffc8ae1c2bb1f4232913`,
passed all 43 focused Windows tests on both Node versions. Installed local Ink
also passed; installed headless qualification failed without child diagnostics.
Linux and macOS passed both versions. Inspection of the pinned ConPTY dependency
found that [winpty-rs 0.4 replaces the caller's standard handles](https://github.com/andfoy/winpty-rs/blob/v0.4.0/src/pty/conpty/pty_impl.rs)
and can allocate/free its console. Qualification now contains native ConPTY
allocation in a worker process and captures headless output explicitly. This
explains the missing inherited output; a new native run must establish whether
it also resolves headless qualification. This is unrelated to SSL attribution.

## Repeatable checks

`Product quality` builds independent wheels and runs `scripts/verify_profiles.py`
on native Windows, Linux x86-64 and macOS for Node 20 and 22. Windows now uses
`winpty.Backend.ConPTY` through `scripts/terminal_session.py`; absence of ConPTY
is a failure rather than a successful skip. Upgrade exercises use the same driver.

The native matrix also runs the canonical test runner over
`tests/test_terminal_session.py`, `tests/test_constants.py`, and
`tests/test_native_terminal_recovery.py`. The recovery test connects real Ink to
an authenticated headless host backed by SQLite and a controlled local provider.
It cancels an in-flight stream and reconnects fresh terminal processes to the
same durable session. This exposed and fixed rejection of idle disconnected
sessions as already active: resumption now reattaches the existing allocation,
while connected, busy and cleanup-pending sessions remain protected. The low-level harness checks resizing, Ctrl-C delivery,
input, confirmed exit and repeated cleanup after a replacement starts.

Focused macOS checks: 70 passed across native recovery, protocol admission and
WebSocket send ownership; 218 passed and one skipped across naming, command
aliases and generated documentation. These are not native Windows receipts.

The new POSIX side of the shared driver passed fresh installed-product
qualification on macOS ARM64 at commit `1f93b4b23` (see
`macos-conpty-driver-posix.json`). All five installation/interaction checks passed;
upgrades were not requested in this run. The receipt does not qualify ConPTY.

## Android/Termux

No Android device, adb connection or Android SDK is available on the development
host. This remains unverified; Linux qualification is not Android qualification.
On a real Termux device with the repository's Python development dependencies,
Node and uv installed, run the same three focused tests through
`scripts/run_tests.sh`, then build and qualify the product wheels using
`scripts/build_profiles.py` and `scripts/verify_profiles.py`. Select the device's
native Python executable with `--python`; do not substitute a managed glibc
interpreter. Preserve the report alongside Android API level, architecture,
Termux version, Node version and Python/OpenSSL versions. Installation failures
are qualification failures, not reasons to omit a check.

## Historical native SSL attribution

No new original binary, certificate bundle, native core or credible reproducer
has been recovered. The previous evidence remains in
`../2026-09-13-products/previous-native-tls.json`. The matching-version runner
experiments did not reproduce the crash and do not establish its cause.
Use `scripts/investigate_native_tls.py` only when new evidence supplies a
specific discriminating hypothesis; preserve binary and CA hashes and native
frames. Do not claim containment is root-cause attribution.

The other retained TLS artifact, `10273517042`, was inspected from run
`34624892829` (commit `fbe8c0643f018298661b903c1485fffece3a5d75`). Its report
is `earlier-native-tls.json`: seven non-crashing workload cases and a synthetic
capture self-test, still without an original CA hash. Shutdown completed zero
TLS contexts, so it is not evidence of sustained concurrent shutdown coverage.

## Colored host-log regression

Run `34761935182` at `9ab8fbc1ea538571c69c63a3d66f40467368e76f`
confirmed that subprocess isolation restores Windows diagnostic output. Native
Windows again passed the focused terminal tests and installed local TUI. The
remaining failure was port discovery: Uvicorn's colored formatter restored its
original `color_message` template after the privacy filter cleared `args`,
printing `%s://%s:%d`. The filter now removes that alternate template after
redaction. Regression tests use Uvicorn's actual formatter with colors on/off,
port placeholders and credentials in both argument-based and literal alternate
messages. Qualification cleanup no longer masks startup errors with an assertion
that handshakes were exercised. The HTTP import probe explicitly shuts down its
owned runtime before interpreter exit.

Run `34762679228` at `5f7c47447a7e7a0400ae91cb0f0781fff98ef82d`
passed installed Windows local and remote terminal interaction, five authenticated
reconnects and completed ASGI shutdown. Its final exit-status assertion rejected
the host exit. Uvicorn restores the original handler and re-raises SIGBREAK;
[Microsoft documents CRT default signal termination as exit 3](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/signal?view=msvc-170),
which differs from an unhandled console event. The verifier now measures this
using a separate child of the same installed interpreter and still requires the
application shutdown-complete marker. Tests reject missing completion and
unrelated exit failures. The earlier HTTP import-probe thread warning no longer
appeared after explicit runtime shutdown in this run.
