# Forecast reliability and release verification

Base: merged PR #24, `80eaec132b2bd48edbfc5f7e74de8638574a06c1`.
Branch: `codex/forecast-reliability-20260910`.

## Required outcomes

1. Verify fresh installation and upgrade with isolated profiles, then execute
   create → research → update → resolve → score → postmortem through the installed
   public CLI. Preserve profile data across upgrade and record artifact provenance.
2. Show that scored outcomes produce traceable learning and subsequent forecasts
   consult it. Verify small-sample, leakage, duplicate-outcome and overcorrection
   safeguards, including negative controls.
3. Verify and harden interruption, cancellation, resume, terminal resize and
   dashboard reconnect through real terminal/browser interaction as appropriate.
4. Reduce provider/configuration and CLI/gateway dispatch coupling using focused
   shared components, preserving behavior and registry ownership.
5. Verify evidence timestamps, independence, duplication, staleness and resolution
   criteria against public sources and adversarial fixtures; fix observed gaps.

## Execution discipline

Each outcome needs executable evidence, observed gaps, fixes and verification.
Passing fixtures is not proof of live service availability or forecasting skill.
Use disposable homes and ledgers. Paid model calls await the user's spending
preference. Preserve the existing Ink transcript/composer and dashboard PTY.
Commit and push coherent verified increments, as previously requested.

## Checkpoints

- PR #24 merge confirmed through GitHub; clean worktree before branching.
- Initial investigation found existing calibration-bias and lesson machinery,
  evidence diversity/staleness helpers, and TUI recovery tests. Their end-to-end
  coverage is under review; no requirement is marked complete yet.

### Learning provenance and correction safeguards

- Reproduced missing score references on synthesized bias lessons and sample
  inflation: 50 snapshots of two outcomes counted as 50 observations (2 failures).
- Bias observations now use one latest scored forecast per question. Reports
  carry scored-source references; domain lessons also retain sources supporting
  the global shrinkage prior. Corrections invalidate dependent lessons through
  the existing correction mechanism.
- Context packets show scored-source count, effective sample size and bounded
  source references. Advisory learning leaves the submitted probability unchanged.
- Reproduced overlapping global/domain numeric corrections multiplying to 1.392.
  Both lessons remain consulted and recorded, but only the most specific generated
  numerical bias adjustment applies; the skipped adjustment has an audit reason.
- Negative controls cover neutral/zero-weight/lesson-exposed rows, thin samples,
  corrected global-prior sources, and no advisory probability change.
- Targeted suite: 62 passed. Full forecasting suite: 3,381 passed, 3 skipped in
  320.04 seconds. JUnit: `.test-results/pytest-20260910T111507Z-61553.xml`.

### Release and dashboard observations still being addressed

- Isolated lifecycle smoke with `--skip-backtest` failed because its readiness
  check still demanded the skipped benchmark replay. This is not a completed
  installed-release rehearsal; fix and verify it before relying on that option.
- Real browser at `/desk` showed gateway loss with the packaged TUI. Two failing
  tests establish the dashboard does not propagate CLI Python/source-root/CWD
  settings. Shared launch-environment fix is next.

### Recovery and shared ownership

- CLI and dashboard now share Python interpreter, source root and working-directory
  launch settings. This fixed the observed real-browser gateway startup failure.
- Dashboard transport loss retains one child for 30 seconds with a 1 MiB replay
  bound. Byte cursors prevent duplicate output; expired/incomplete replay requires
  explicit resume. Normal close and server shutdown reap children. ASGI cancellation
  shields teardown. Resize dimensions stay inside the POSIX unsigned-short range.
- Browser rehearsal with a local HTTP model: streamed reply, disconnected socket,
  reconnect from byte 27864, draft preserved, resize and subsequent submission.
  Screenshot: `/tmp/forecast-dashboard-reconnected.png` (local evidence).
- Stalled-stream PTY rehearsal reproduced lost follow-up prompts in SQLite: request
  sequence repair merged durable user rows and invalidated the flush cursor. Repair
  now operates on request copies. Cancellation, resize, subsequent turn, exact-once
  prompt persistence and process restart/resume pass together (13 targeted tests).
- Existing terminal/gateway recovery suite: 293 passed. WebSocket suite: 168 passed.
  PTY replay/expiry/capacity/cleanup suite: 17 passed. Browser connection helper:
  11 Node tests passed; dashboard build passed.
- Provider catalog/template preservation moved out of the interactive picker;
  shared quick-alias expansion preserves arguments and built-in precedence and
  rejects cycles before CLI/gateway dispatch. Shared ownership suite: 77 passed.
- Keyless endpoints no longer receive an unconditional failed-credentials warning.

## Closeout

All five requested workstreams have implementation and executable evidence below.
Future platform/service/performance work is tracked in [TODO.md](../../TODO.md).
Synthetic outcomes and local-model transport rehearsals do not establish
prospective forecasting performance.

### Evidence and release checkpoint

- Research adequacy and readiness now share conservative source identities: one
  publisher is not multiple independent sources because article URLs/names differ.
  `metadata.independence_group` and `original_source_url` capture known shared
  origins. Host diversity remains a proxy, not proof of independence.
- Tracking parameters/fragments no longer inflate the distinct-observation floor;
  original rows remain intact. Future observations do not satisfy recency.
  Publication/availability chronology is validated after UTC normalization.
- USGS imports now use revision timestamps for availability and preserve earthquake
  time separately as `observed_at`; previously revised magnitudes could leak into
  earlier cutoffs. USGS/NWS repeated imports skip identical raw revisions while
  retaining changed revisions. Missing NWS publication uses capture time.
- Public USGS/NWS feeds captured at 2026-09-10 11:46 UTC: 11 events and 353 alerts.
  Three records from each were ingested per installed profile and duplicate imports
  skipped. Raw bytes, URLs, timestamps and SHA-256 are preserved with the rehearsal.
- `scripts/verify_forecast_release.py` creates fresh virtualenvs and homes, installs
  an old wheel then upgrades, checks configuration/question/evidence preservation,
  and executes the full public CLI lifecycle in both upgraded and fresh installs.
  Model calls are not needed; the rehearsal marks snapshots calibration-ineligible.
- Full forecasting suite: 3,386 passed, 3 skipped (320.82s).
  Integrated runtime/gateway/terminal suite: 5,643 passed, 8 skipped (66.94s).
  Full agent suite: 1,368 passed, 3 skipped (14.27s).
  Zero-byte reconnect guard: 159 passed. Browser connection helper: 12 passed.
  Dashboard build, Ruff, generated docs and protocol checks pass.

### Final release evidence

- Implementation commit: `92472c4c1`; follow-up documentation carries the manifest.
- Final wheel SHA-256:
  `29fe919213cedf86cec640a0c0fefb30079ec14bcfb0274fd9bd5d1f97d21fef`.
  Byte equality checked for 966 packaged Python files. TUI/dashboard entrypoints
  were also checked against the bundled build.
- Previous wheel SHA-256:
  `2875d1c4977b2c2f2647fff8985d578f0672dba2b4f26bf36bdc92bcc3265467`.
  Its provider CLI, forecast CLI and evidence source match the merged PR #24 base.
- Final installed-artifact rehearsal: 39 command checks, both fresh and upgraded
  profiles pass. Upgrade preserves prior evidence/question/configuration. Invalid
  criteria and unsupported binary outcomes fail; revised records cannot be cited
  before publication; aged observations are flagged stale. Scores and postmortems
  are verified through independent database reads.
- The negative resolution check reproduced a confirmed-invalid-outcome bug.
  Validation now precedes question closure and scheduler teardown; invalid
  binary/categorical outcomes leave the question active with no resolution row.
- Full command outputs, disposable profiles and captured source bytes:
  `/tmp/forecast-release-delivery-20260910/`. Compact durable manifest:
  [verification JSON](../verification/2026-09-10-forecast-reliability.json).
- Final browser screenshot: `/tmp/forecast-dashboard-final.png`. Reconnect used
  cursor 36448 with `reconnect=1`; the draft remains visible, and the false
  credential warning is absent. Fixture servers are shut down after verification.

Reproduce the release rehearsal (macOS/POSIX, uv installed):

```sh
SKIP_NPM=1 bash scripts/build-release.sh
.venv/bin/python scripts/verify_forecast_release.py \
  --wheel dist/superforecasting_agent-0.20.0-py3-none-any.whl \
  --previous-wheel /path/to/previous/superforecasting_agent-0.20.0-py3-none-any.whl \
  --output /tmp/new-release-rehearsal \
  --source-dir /tmp/forecast-release-delivery-20260910/sources
```

Omit `--source-dir` for the installation/upgrade/local-evidence lifecycle alone.
The source directory must contain `usgs.json`, `nws.json` and their hashed manifest.
This verifies artifact replacement at version 0.20.0; it does not publish a new
version or establish Windows/Linux/Termux or paid-provider readiness.

### Final input and regression confirmation

- Final forecasting suite after resolution validation: 3,388 passed, 3 skipped
  (317.88s), JUnit `.test-results/pytest-20260910T115716Z-70933.xml`.
- Browser-to-SQLite comparison exposed rapid typing loss. Mixed multi-character
  PTY reads and single keystrokes could overtake the paste buffer; all text now
  stays ordered, and Enter flushes buffered text before submission.
- Real PTY tests pass chunked input, rapid input, rapid-submit and stalled-stream
  cancellation/resume (4 passed). The final real browser persisted the complete
  typed prompt exactly, followed by the expected streamed response.
- Full TUI suite: 2,010 passed, 1 skipped across 185 files. Typecheck, build and
  zero-warning targeted ESLint pass.
- Installed public `superforecasting-agent tui` launched outside the checkout
  from the fresh wheel environment, streamed a local-provider response, preserved
  exact prompt/reply in SQLite, and exited cleanly. Result:
  `/tmp/forecast-release-delivery-20260910/installed-tui-result.json`.
