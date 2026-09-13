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
preserves JUnit/log artifacts. A fresh Windows run is still required.

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
