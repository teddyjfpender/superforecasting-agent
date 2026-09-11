# Learning, settlement and runtime hardening

Release work is deferred at the operator's request. This work does not monitor CI
or assert a published release.

## Confirmed defects and changes

- SQLite reuses authorization on cached prepared statements. A raw INSERT first
  prepared inside `allow_ledger_writes` succeeded again outside that context on
  the same connection. Ledger connections now disable statement caching, with
  regressions covering context exit and a switch to proposal-only policy.
- An exception inside a SQLite authorizer becomes `DatabaseError: not authorized`,
  including on SELECT. The callback now logs its original exception and traceback
  without SQL values. This reproduces a possible mechanism for the historical
  deadline failure; it does not prove what interrupted that CI worker.
- Source bindings reject malformed contracts, missing/out-of-range timestamps,
  numeric strings, booleans, missing measurements and nonfinite values at the
  parser boundary. These remain observation contracts, not proof of a completed
  daily maximum or independent corroboration.
- New trial admission and readiness share evidence and score-support checks.
  Invalidated, superseded, blocked, explicitly stale and backtest-excluded evidence
  cannot enter new frozen packets. Calibration-ineligible or zero-weight scores
  cannot establish outcome-backed lesson support. Applicability rejection reasons
  are visible in candidate reports.
- A pending update refresh no longer displays the previous completed result.
- Historical censoring conversion previews every forecast's original payload and
  selected event probability, binds application to a SHA-256 review digest, and
  retains the original question/forecast manifest in its review history. Explicit
  `p_gt_*`/`p_gte_*` keys must match the declared inequality and threshold. Missing
  keys cannot silently fall back to a Gaussian. Existing scores use the correction
  workflow, not this conversion. Censored scores remain calibration-ineligible.

Completed historical trials retain their original config and packet identities.
The compatibility registry explicitly reviews the connection-only change and the
opt-in censoring representation: old contracts without `probability_key` retain
unchanged scoring. Unknown source/evaluation identities still fail closed.

## Investigation still open

The SSL crash stack was inside default certificate loading in an update-check
thread on Linux CPython 3.11.15. Single-flight update checks address the observed
thread accumulation, but no native crash reproduction establishes the full cause.
Do not label it fixed based on that mitigation alone.

Android/Termux access is pending. The local Docker client exists but its daemon
is unavailable. Neither is cross-platform execution evidence. Credential-dependent
services need their actual service access; hermetic tests cannot verify them.
