# Deep dive: the testing doctrine

The honest doctrine behind the test suite and the gates. The
[development guide](../development.md#tests) covers *how to run* the suites
(`scripts/run_tests.sh` for Python, `npm test` for the TUI); this page is the
*why* — the disciplines that keep the suite from lying, the flaky classes it lives
with, and the refactor-safety rules that keep a green suite green through a carve.
The canonical contributor rules are in [`CONTRIBUTING.md`](../../CONTRIBUTING.md)
("Exit-code test gates", "Commit provenance"); this page is the reasoning.

---

## Exit-code gates never grep (the swallowed-red-test story)

> **A test gate passes or fails by exit code, never by grepping output.**

`vitest | grep` and friends are **banned**. The failure mode they hide: a pipeline
like `vitest run | grep -q PASS` takes the exit code of the *last* stage
(`grep`), so a red test that still prints the searched-for word passes the gate —
the red is swallowed. CI and the git hooks propagate the **real** exit code,
always. This is Arc F(c), shipped with A1: the protocol staleness gate is
`scripts/check-protocol.sh` (`python -m protocol.codegen --check`), wired into
`.github/workflows/tests.yml` *before* the pytest run and mirrored by the pytest
golden-file test `tests/test_protocol_codegen.py` — **both exit-code gated**. Even
the "grep-proof" tests (assert no raw event-name string survives outside the
generated module) are real test assertions with a real exit code, not a
grep-over-output masquerading as a gate.

---

## Component-level width pins (`useStdout` reports nothing)

The Ink test harness does not report terminal columns: mounted inline,
`useStdout()` returns nothing usable, so any component that measures its width
falls back to an **80-column** default and never mounts a width-dependent layout
(the Desk's two-pane summary panel, for instance). The discipline is therefore to
**pin the contract at the component level with a deterministic width** rather than
mount the whole app and hope. The `deskView.test.tsx` "sidebar wrap law" test is
the exemplar: it renders `DeskSummary` directly with `width={44}` into a
`writeStream(60, 40)` and asserts the title wraps (`through` / `2027?` present,
`AI-infrastr…` absent) and the teaser reads to its end. This "pmSection pattern"
was hand-rolled ~3× before a proper fix (Arc F(a), still open) — the deferred fix
is to teach the harness's `useStdout` to report injected-stream columns so width
logic becomes testable through real mounts.

---

## The known flaky classes

Flakes are **named, not hidden** (a `feat`/`refactor` commit body records what
flaked). The suite lives with a small, understood set:

- **Subprocess-timeout under xdist load.** `test_smoke_script` runs a real
  subprocess with a 60s timeout; under heavy parallel (`xdist`) load the child can
  miss the window and time out. It is a **timing** flake, not a logic failure — it
  passes in isolation and on a re-run. Every ledger-carve slice records it
  explicitly ("2,271 pass + 1 pre-existing flaky `test_smoke_script` 60s-subprocess
  timeout … the flake passed on the after-run").
- **Order-sensitivity across the full suite.** A handful of tests are sensitive to
  **full-suite xdist ordering** (worker assignment / shared-fixture ordering) in
  ways they are not when a single area runs alone. The carve slices call this out
  when a before/after pass count differs by an order-dependent test that touches no
  changed code.
- **Keyboard/echo timing on the TUI side.** The line-editor fast-path tests
  (`textInputFastEcho.test.ts`, cursor source-of-truth tests) exercise
  timing-sensitive input echo; they are deterministic when driven with explicit
  ticks, and the discipline is to drive them with a fixed clock rather than lean on
  wall-time.

Because these are known and timing-shaped, `scripts/run_tests.sh` pins the xdist
worker count, timezone/locale/hash seed, and blanks credential env vars so a local
run matches CI and a "flake" is reproducible rather than mysterious.

---

## Fixture-rot vs live probes

Recorded fixtures capture a provider's response *shape at capture time* — and shapes
**rot**. The market-data plane (Arc C) proved this three times: the FX-range shapes,
the BEA error/line/comma quirks (`Year=LAST5` invalid; the comma-formatted numbers),
and specific live cases — **Peru, RFK, and BEA were all found only live**, not in any
fixture. The related honesty story: the **BEA `0.0000`** estimator bug "lived in
client TS precisely because the taxonomy tests could not see it" — a client-side
computation the server-side estimator-honesty suite would have caught.

Two responses:

1. **Estimator-honesty suites cover all quote math server-side.** Moving the
   providers server-side (Arc C) was partly so *one* honesty suite could see every
   quote computation — a fabricated `0.0000` can't hide in client TypeScript the
   taxonomy tests never run against.
2. **A weekly live-API contract cron** (Arc F(d) / Arc-7c): a scheduled job hits
   each provider's cheapest endpoint weekly and alerts on shape drift, so fixture-rot
   surfaces as an alert instead of a silent wrong number in production.

The general rule: fixtures test *our parsing*; a live probe tests *their contract*.
Both are needed; neither substitutes for the other.

---

## Test-first bug fixes (reproduce before fix)

A bug fix starts by **reproducing the failure in a test**, then fixing it — so the
test proves the fix and guards the regression. The ledger carve gives a crisp
example: an AST-extent bug where using "the next `def`" as a method boundary
swallowed a class attribute (`_TRIGGER_VALUE_KEYS`) that sat between a method's
`return` and the next `def`. The tests caught it as a concrete `AttributeError` at
the call site — the fix was to use AST `end_lineno` for extents, and the failing
test is what made the boundary bug legible rather than a vague "something's
missing".

---

## The pre-push targeted pytest map

`pre-commit` is the fast gate (<10s: `ruff` on changed `.py`, the protocol
staleness check, the wire-drift check, `tsc --noEmit` when `ui-tui` is staged).
`pre-push` is the heavier one (~2–3 min): it re-checks protocol staleness, runs
`vitest --changed` when `ui-tui` was touched, and runs **targeted pytest for the
changed Python domains** via `py_test_targets` (`.githooks/lib/checks.sh`), which
maps changed files to their covering test dirs:

| Changed path | Test target |
| --- | --- |
| `forecasting/**`, `tools/forecast_actions/**` | `tests/forecasting` |
| `protocol/**` | `tests/test_protocol_codegen.py` |
| `gateway/**`, `tui_gateway/**` | `tests/gateway` |
| `agent/**` | `tests/agent` |
| `superforecasting_agent/runtime/**` | `tests/runtime_cli` |
| `providers/**` | `tests/providers` |
| `cron/**` | `tests/cron` |
| `acp_adapter/**`, `acp_registry/**` | `tests/acp` |
| `tests/**` | the test file itself |

Targets are de-duped and existence-checked; a changed file with no mapping skips
the targeted run loudly. The push runs `scripts/run_tests.sh $TARGETS -q` so it
matches CI settings. (The hooks **block** but never `git add`/`commit` — staging is
a human decision.)

---

## Monkeypatch-surface preservation in refactors (the ledger façade)

The single most dangerous move in a carve is **breaking a monkeypatch reach**.
Tests patch module-global names — `forecasting.ledger.urlopen`,
`forecasting.ledger.ForecastLedger` — and expect the patch to reach the call
sites. When the ledger monolith became the `forecasting/ledger/` package, the
bodies moved to `core` (a distinct namespace), so a plain re-export would have
silently broken every such test.

The fix (D1, and **every future leaf inherits it**): `__init__` installs a tiny
façade — `_LedgerPackage.__setattr__`/`__delattr__` forward writes to `core` when
`core` has the attribute — reproducing the old single-module monkeypatch semantics
**exactly**, with zero test or caller edits. The mandated discipline for every
subsequent slice: **re-run the package-level-patch grep** for every name the new
leaf re-imports (`forecasting.ledger.<name>`), and confirm it comes back empty
before pulling a body out. (The env-var gate `FORECAST_GATE_DIRECT_WRITES` is read
*live* inside `allow_ledger_writes`, so its tests patch the environment, not an
attribute — a separate surface, equally preserved.)

---

## Before/after (stash) verification for pre-existing failures

Every carve slice is verified **mechanically, both sides of the change**: the full
`tests/forecasting` suite must be green **before AND after** — capturing the
baseline first so a pre-existing flake (the `test_smoke_script` timeout) is
attributed to the baseline, not blamed on the slice. The full gate per moves-only
slice is: (1) suite green before and after; (2) `git diff` shows only moves +
one-line delegates (difflib categorization proving **0 unexpected added/removed
lines**); (3) `--collect-only` reports 0 import errors; (4) import-time budget
unchanged. A pre-existing failure that shows up on the "before" run is named in the
commit body and shown to still pass/flake identically on "after" — the change is
proven to have *added no red*, which a single after-only run could never establish.

---

## Sources

- `CONTRIBUTING.md` ("Exit-code test gates", "Commit provenance", "No staging")
- `.githooks/pre-commit`, `pre-push`, `commit-msg`, `.githooks/lib/checks.sh`
  (`py_test_targets`, `check_protocol_stale`, `check_drift`, `check_vitest_changed`)
- `scripts/run_tests.sh`; `tests/test_protocol_codegen.py`
- `ui-tui/src/__tests__/deskView.test.tsx` ("sidebar wrap law"),
  `textInputFastEcho.test.ts`
- `docs/plans/2026-07-03-architecture-delivery-plan.md` — Arc F (test infra), the
  ledger-carve findings ledger (monkeypatch façade, AST-extent bug, before/after
  gates), Arc C (live-probe / fixture-rot, the BEA `0.0000` story)
