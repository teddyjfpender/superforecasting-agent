# Runtime ownership and recovery investigation

Scope: engineering behavior in isolated profiles; no live forecasts or paid
providers. The historical SSL crash and the late bad-descriptor error are separate
incidents. A demonstrated mechanism must not be described as their proven cause.

## Demonstrated descriptor bug and shutdown changes

`_ThreadedProcessHandle` previously closed the write end of its stdout pipe twice:
first in the worker's `finally`, then in `close()`/`__del__`. File descriptor numbers
are reusable. The second close could therefore close another component's new
socket or pipe. The worker now exclusively owns the write descriptor; the handle
owns the read file object. Closing before execution finishes produces a broken
pipe in the worker, without closing a numeric descriptor that may belong elsewhere.
Regression tests force descriptor reuse and cover cleanup before/after completion.
This proves and fixes the mechanism, but does not attribute the old suite failure.

Gateway lock acquisition/release is serialized. Failed lock-record writes close
the acquired handle. Cleanup carries an opaque lease identity, so a stale shutdown
or atexit callback cannot release a newer lease. Shared asynchronous shutdown is
shielded: cancelling an individual waiter cannot cancel cleanup for every caller.
Tests cover stale leases, failed acquisition writes and cancelled shutdown waiters.

## Real desk integration exposed a recovery defect

The previous supervision tests used the same string for two different identities:
the temporary JSON-RPC session ID and the durable SQLite session ID. Real sessions
use different values. Ink previously tried to resume the temporary ID after a
child-process crash, received “session not found”, then opened a new desk.

`SessionInfo.durable_session_id` now carries the SQLite key from creation, agent
hydration and compression. Ink retains that key for reconnect and the active-session
file; normal RPC dispatch still uses the temporary ID. Recovery restores the
original journal receipt and partial response. The optional protocol field permits
older gateways to remain readable without inventing a durable identity.

`tests/runtime_cli/test_local_desk_lifecycle.py` runs the actual compiled Ink TUI,
stdio gateway, dashboard WebSocket/PTY bridge and SessionDB together. Only the
provider boundary is replaced: a test agent streams a controllable loopback HTTP
response. External connections are refused in that child; the optional update
probe is disabled in this fixture and tested separately. Cases cover authentication
expiry, rate limits, premature stream EOF, cancellation, abrupt gateway SIGKILL,
resize and dashboard reconnect. Assertions inspect the durable journal and actual
terminal output. The fixture closes every SQLite reader explicitly (a connection
context manager commits/rolls back; it does not close the connection).

Repeat locally:

```sh
npm ci --prefix ui-tui
npm run build --prefix ui-tui
scripts/run_tests.sh tests/runtime_cli/test_local_desk_lifecycle.py
```

The native investigation workflow supplies those prerequisites on Linux and saves
JUnit output. Default Python runs include these tests when the compiled TUI exists;
without it they explicitly report the missing prerequisite as a skip.

## Native SSL evidence boundary

Original failure: production-release run `34583759149`, test job `103223021819`,
2026-09-11 10:18:10 UTC. The full job log identifies Ubuntu 24.04 runner image
`20260907.300.1`, uv `0.10.9`, and uv-managed CPython
`3.11.15-linux-x86_64-gnu`. The Python stack locates certificate loading in the
background update check. It does not contain native frames, a core, the OpenSSL
binary hash or the CA bundle hash. The fixture-running main thread was not
interpreter shutdown. Shutdown is therefore a separate discriminating control,
not the assumed historical cause.

`scripts/investigate_native_tls.py` requires Linux x86-64 and the workflow runs it
on a native Ubuntu runner. It records Python/OpenSSL/libc identity, linked libraries,
executable/extension/CA hashes and the current runner image. A fresh interpreter
runs each case under GDB: serial TLS initialization, concurrent initialization,
environment growth/removal, the same mutation with an explicit CA file, and daemon
thread shutdown. The environment test targets native default-path environment
lookup lifetime; it is a hypothesis, not a root-cause claim. GDB records all-thread
native stacks and a core when a signal occurs. A clearly labelled synthetic abort
validates the capture pipeline. It is not an SSL reproduction. Timeouts kill and
reap the entire debugger/process group. Debugged children receive a minimal
environment so runner credentials do not enter their cores.

A matching Python version and current native runner do not prove byte equivalence
to the lost historical runtime or certificate bundle. A clean run does not close
the root-cause item. Results are recorded separately after the workflow runs.

### Certificate-loading paths outside the update probe

- `runtime/auth.py::_default_verify/_resolve_verify`: macOS certifi or explicit
  custom CA contexts; other platforms defer to httpx. These are in-process.
- `gateway/platforms/weixin.py`: explicit certifi context, also in-process.
- `gateway/platforms/email.py` and `tools/send_message_tool.py`: STARTTLS default
  contexts; IMAP SSL also initializes TLS internally.
- `forecasting/source_adapters.py` and Google/Anthropic acquisition helpers:
  urllib HTTPS uses library-created contexts; requests/httpx provider clients
  likewise own TLS internally.

The update subprocess containment covers none of those other clients. A blanket
Python lock would not synchronize third-party native context construction or
arbitrary environment writers; it would not establish a fix. Their trust-store
behavior is preserved pending a discriminating native result.

## Economic parsing and command ownership

EIA, Treasury, Census, World Bank and IMF ingestion no longer present observation
periods as publication timestamps. Unknown publication/revision times remain
unknown. The general adapters do not gain verified settlement authority: BLS/FRED
remain the explicitly reviewed economic contracts.

EIA parsing has its own pure module, rejects mismatched series and nonfinite or
boolean measurements, validates calendar periods, and no longer borrows metadata
from the first unrelated legacy series. World Bank and IMF now have pure payload
parsers; World Bank requires response country/indicator identity (including the
explicit ISO3 field when requested), and IMF rejects anonymous year/value maps.
Census rejects duplicate headers and row-width changes. Treasury requires requested
date/value fields and refuses to guess between multiple numeric measurement
columns. Fixtures pin these cases and unsupported settlement adapters fail closed.

The shared constants owner parses persisted service tiers and fast commands for
CLI, messaging gateway and TUI. Empty commands report status; explicit toggle and
on/off aliases share semantics. TUI single-setting edits now use the same locked,
comment-preserving latest-file merge as CLI/gateway. Full snapshot saves retain
revision checks. Tests preserve unrelated external edits and reject malformed YAML
without replacing it.
