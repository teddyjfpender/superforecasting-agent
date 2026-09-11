# Source contracts, portable provenance and runtime recovery

This pass changes system behavior and tests in isolated stores. It does not settle
live forecasts, run prospective cohorts, publish releases or establish forecasting skill.

## Economic settlement contracts

`forecasting/economic_bindings.py` owns economic response semantics. Fetching remains
at the ledger acquisition boundary; credentials are added only to the request URL.
Canonical URLs, evidence metadata and export receipts never acquire the FRED API key.
`applicability_facts.py` owns archive verification, cutoff admission and scalar facts;
`settlement_binding.py` checks these facts against the declared resolution contract.

- BLS supports explicitly reviewed monthly series/unit mappings (unemployment,
  total nonfarm payrolls, seasonally adjusted CPI). Exact series, month and complete
  period are mandatory. Conflicting duplicates and missing/nonfinite values fail.
  Its current API proves only the value at capture, not the initial release.
- FRED requires a separate archived series-metadata response proving entity,
  physical units and frequency. `units=lin` specifies transformation, not physical
  units. An exact observation and complete period are required.
- Initial-release FRED requests use `output_type=4`. Pinned-vintage requests use
  `output_type=1` with an explicit real-time date. These policies are distinct and
  settlement checks the frozen policy. Day-precision initial-release availability
  is conservatively represented by the next midnight UTC, not an invented precise
  publication instant. BLS and pinned-vintage publication times remain unknown.
- General FRED ingestion no longer fabricates publication time from observation
  dates or silently takes another CSV series column. Numeric zero is preserved.
- Redirected or oversized captures cannot acquire canonical-source authority.

Provider semantics: [BLS API](https://www.bls.gov/developers/api_signature_v2.htm),
[FRED observations](https://fred.stlouisfed.org/docs/api/fred/series_observations.html),
[FRED real-time periods](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html).
These are intentionally narrow adapters. Unsupported series/measurement semantics
must receive a reviewed contract; a plausible number alone cannot authorize settlement.

## Version 1 source transfer

JSON question exports contain `source_transfer` with version, validated bindings,
base64 archives (2 MB per archive), SHA-256 receipts and immutable transfer history.
Import commits the evidence bytes and associated records in one SQLite transaction.
Malformed versions, scopes, contracts, conflicting identities or hashes roll back.
Foreign archive paths are replaced by evidence IDs for bound resolutions and are
not used as local read capabilities. Original resolution references and learning
records remain in hash-bound history, including original forecast provenance.

An imported hash proves integrity, not source authenticity or historical availability.
Facts therefore report `imported`, and imported source-bound resolutions cannot
produce new scores until local verification. Imported forecasts and scores are
ineligible for calibration; active foreign lessons become tentative and derived
error profiles are not promoted. This quarantine survives later byte verification.

`superforecasting-agent forecast facts verify-import <id>` explicitly fetches the
canonical source again. Identical bytes receive `locally_reverified` with the actual
verification time. Changed sources remain imported with a reason. Verification is
never backdated and does not establish the foreign forecast's historical timing.
The new local capture remains separate evidence. A changing endpoint may never
allow historical byte verification; its imported claim remains inspectable.

## Configuration ownership

`storage/files.py` owns atomic YAML read/modify/replace under the shared thread and
process lock. Compound model/profile changes preserve unrelated settings and YAML
comments. YAML 1.1 boolean-like strings such as `off` are explicitly quoted so
YAML 1.2 serialization cannot change their type for the application loaders. Login/logout, onboarding, doctor, messaging display settings and Yuanbao
home-channel discovery use shared persistence instead of direct whole-file writes.
Raw runtime loads now retain revisions, so stale auth/doctor saves fail too.
The snapshot type has one storage owner across runtime reloads and compatibility
imports; separate loaders cannot silently lose its revision checks.
Classic CLI first writes target the active profile, not a repository defaults file.
The TUI uses shared indexed dotted-key navigation.

Dashboard form and raw YAML APIs require a revision token: missing preconditions
return 428 and conflicting saves return 409. The editor retains edits for review.
TUI full snapshots also reject cross-profile or stale saves. Edits made while a
dashboard save is in flight are retained when its revision token returns. Whole replacements
remain deliberate reset/setup operations, not an implicit way to save one setting.
CLI and messaging reasoning effort validation share the same parser; failed saves
no longer announce a successful persisted setting. Session-only messaging settings
retain their documented scope.

## Durable TUI recovery

`tui_gateway/turn_journal.py` stores prompt, partial output, status, error and worker
identity in the existing session database. Start/delta/terminal state commits before
notification. Cancellation remains pending until the worker exits; terminal records
cannot be reopened by late frames. Session deletion also erases the saved prompts. In-flight receipts follow
compression continuation sessions.
Resume detects a live process by PID plus process creation time and does not steal
its turn. An unfinished receipt from a dead process becomes interrupted exactly once.
The resumed TUI displays saved partial output and recovery status. Storage failure
is explicitly displayed as unavailable, not as a successfully saved response.

Turn IDs reject late/duplicate transport messages across retries. Tests inject auth
expiry, rate limits and interrupted streams through both the persistence seam and
the real gateway worker. Other fixtures cover cancellation, repeated resume, stale
events, failed persistence and session deletion. Existing dashboard reconnect tests
continue to exercise the embedded TUI transport; this is not a second transcript UI.

## Runtime investigation: conclusions and limits

The original failure log identifies CPython 3.11.15 from uv on Linux x86-64. The
native fault was in `ssl.load_default_certs`, called by the optional background
release check. Many other update-check threads were waiting on Git subprocesses.
That is the observed stack, not proof of an OpenSSL defect or a specific race.

The bounded `scripts/investigate_runtime.py` harness exercises concurrent default
context construction, daemon shutdown and concurrent environment mutation in
separate processes, without network access or credentials. Committed JSON receipts
are in [runtime verification](../verification/2026-09-11-runtime/).

| Runtime | TLS/shutdown/environment processes | Result |
| --- | ---: | --- |
| Linux ARM64, CPython 3.11.15, OpenSSL 3.5.6 | 16 (TLS/shutdown) | all exited 0 |
| Linux x86-64, CPython 3.11.15, OpenSSL 3.0.20 | 24 | all exited 0 |
| uv Linux x86-64, CPython 3.11.15, OpenSSL 3.5.5 | 9 + 6 | all exited 0 |

The x86-64 tests ran under local emulation. The uv runtime matches the historical
version/distribution/architecture, not a proven byte-identical runner; the host CA
bundle was supplied explicitly. These finite exercises did not reproduce the
native SSL fault. The historical native root cause remains unresolved. Existing
bounded update-check subprocess isolation removes certificate loading from the
foreground process; this pass adds interpreter/OpenSSL identity before TLS setup
and bounded crash stderr to the parent diagnostics. Existing timeout/signal tests
verify child cleanup. No TLS verification was disabled and no library downgrade
was applied on speculation.

The SQLite mechanism **was reproduced with a real SIGALRM**, including on the uv
Linux runtime: an exception inside the authorizer is converted by sqlite3 into
`DatabaseError: not authorized`. `LedgerConnection` preserves and rethrows the
actual callback exception through connection/cursor statements and transaction
commit/rollback/exit. The same Linux harness now reports the original `Deadline`
and a reusable connection. Write authorization remains fail closed and statement
caching remains disabled. Regression tests verify rollback and reuse after actual
signal interruptions, including commit failure. This explains how the historical
message can arise; the original log does not prove which deadline caused that run.

## Validation

The final canonical Python run on implementation `61567a296` passed **30,387**
tests, with **148 skipped**, no failures and no errors (552 seconds). The runner
excludes `tests/integration` and `tests/e2e`; this is not a claim of live credential
or additional platform verification. The JUnit digest and commands are recorded
in [validation.json](../verification/2026-09-11-runtime/validation.json).

The complete TUI suite passed **2,024 tests**, with one skipped. TUI type-check,
production build and changed-file ESLint passed; the dashboard production build
passed. Configured Ruff checks, undefined-name checks, all six architecture
contracts and generated-document freshness checks passed.

Focused suites additionally exercised 152 YAML/model/profile cases, 115 setup and
loader-identity cases, and 228 combined TUI/shutdown cases. Earlier full-suite runs
exposed the YAML string/boolean mismatch, module-reload snapshot identity issue,
and stale test-owned database/module references. The disk-failure test now injects
at the real database boundary. A shutdown wiring fixture's earlier bad-descriptor
failure prompted isolation of global lock release it did not own; no production
native root-cause claim is inferred from that test-only failure. The final full run
is clean, including these regression cases.

Frozen learning trial identities remain unchanged; the compatibility registry explicitly reviews the
nonmathematical connection and imported-settlement changes. Paired scoring formulas
and frozen lesson adjustments were not changed.
