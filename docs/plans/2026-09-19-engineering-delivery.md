# Engineering delivery record

Goal: implement the complete [specification](2026-09-19-engineering-improvement-specification.md),
not just the initial fixes. Baseline: `df8e3e33cd4d08c6eaad38a275f6e217e92a3375`.
Worktree: `feat/engineering-improvements`.

## Verification policy

The user explicitly requests focused tests instead of the full suite. This supersedes the
specification's full-suite execution requirement for this delivery. Retain the qualification
commands and native matrix; do not claim that an unexecuted full suite passed. Native platform
and installed-artifact requirements still need evidence at the appropriate milestone.

## Package status

| Package | State | Evidence / remaining work |
|---|---|---|
| W01 qualification | In progress | Reproduced provider test failure; preserved legacy active-provider menu; macOS boot identity replaces network discovery; docs freshness added to canonical check. Focused tests below. Windows identity capability/versioning and remote native receipts remain. |
| W02 quality ratchet | In progress | Added test TypeScript project; initial valid-root measurement found 291 diagnostics, including incomplete selection mocks, terminal stream types and protocol fixtures. Fix these before making it blocking. Remaining coverage ratchet, typed fixtures and execution tiers. |
| W03 typed sources | Pending | All specification criteria remain. |
| W04 CLI parity | Pending | Legacy active-provider behavior corrected as part of W01; shared command inventory/parity remains. |
| W05 runtime ownership | Pending | All specification criteria remain. |
| W06 TUI state | Pending | All specification criteria remain. |
| W07 questionnaire durability/lessons | In progress | Update interviews freeze advisory lesson selection, exclusions, digests and score/postmortem support. Historical contexts remain readable, and model prompts omit excluded guidance. Durable editor buffer API implemented with revision conflicts, discard tombstones, atomic receipts and lifecycle cleanup. Pending TUI autosave/restoration/status integration, new-question context and TUI provenance display. |
| W08 integrated recovery | Pending | All specification criteria remain. |
| W09 merged product qualification | Pending | All specification criteria remain, subject to focused-test policy above. |

## Focused receipts

19 September 2026, native macOS, Python 3.13.12, working-tree changes (not release certification):

- Reproduced `test_cmd_model_forwards_nous_login_tls_options`: one failure due to index-zero
  Anthropic selection and an attempted interactive read.
- Process identity, background research and complete CLI provider-resolution module: **38 passed**.
- Process identity, background research, research jobs, async delegation, developer workflow,
  and native docgen environment: **65 passed**.
- `python -m scripts.docgen --check`: passes after regeneration.
- Selected Ruff and strict `ty` check of process identity: pass.

The local background/job tests exercise the real macOS kernel identity probe. They do not
substitute for the pending Linux/Windows/native CI matrix. Old macOS identity records are
conservatively left unreconciled; they are not relabeled as the current host.

First implementation commit: `62a91b2e70`. Canonical Python quality checks pass, including
76 import contracts and generated-reference freshness. No hook bypass was used.

## Second implementation tranche

- Added typed local RPC fixtures with compiler-negative cases; unregistered calls reject.
  Questionnaire components now require only the request capability they consume.
- Updated questionnaire provenance fields, source change-basis fixtures and current composer
  props; removed status-test casts hiding malformed fixtures.
- Focused TUI run: 70 tests across six files passed; subsequent typed questionnaire/RPC/status
  run: 53 tests across four files passed. Production TypeScript check passed.
- Update interview contexts now freeze lesson selection. Shared cutoff admission excludes
  later revisions before supersession. Missing score/postmortem support is rejected, sample
  counts remain distinct from independent-cluster evidence, and guidance is advisory only.
- Focused Python run: 104 tests across interview context/generation, lesson wiring/enforcement,
  active-origin and learning trials passed. Strict interview typing passed.
- Historical evaluation compatibility review: only `learning.py` changed among evaluation
  sources; existing AST changes are confined to scope enumeration and cutoff selection.
  Completed evaluation passes frozen lessons to unchanged adjustment code. The explicit
  registry mapping preserves old identities without rewriting packets; unknown identities
  still fail closed. See `forecasting/trial_compatibility.json` for the review receipt.

The complete test TypeScript project is not yet a passing/blocking gate. Remaining diagnostics
are tracked by `ui-tui/tsconfig.tests.json`; no ignore baseline or blanket cast was added.
No full test suite was run. All W01–W09 exit criteria not evidenced above remain open.

## Durable buffer backend tranche

Added versioned editor-buffer save/read contracts and generated TypeScript. The ledger
stores buffers separately from confirmed interview answers and probabilities. Optimistic
concurrency rejects competing writers and changed interview revisions. Atomic retry receipts
contain no draft text; discarded content cannot be resurrected by replay. Cancellation and
commit purge draft text while profile databases isolate it. Additive schema initialization
preserves existing interview records.

Focused validation covers RPC rejection of secret/actor fields, actual subprocess exit after
acknowledgement, receipt-write rollback, changed/reused requests and lifecycle cleanup. This
is backend readiness, not yet a claim that TUI edits autosave. TUI integration remains open.

Buffer backend receipt: **47 focused tests passed** across persistence, interview lifecycle
and gateway contracts. Canonical Python/TUI static quality checks pass (including generated
contracts, reference freshness, 76 import contracts, lint and production TypeScript).
The full suite was not run. The new RPC request models retain the required `WireModel`
contract and explicitly enforce strict, extra-forbidden editor input.

## Questionnaire editor integration tranche

The TUI now restores acknowledged unconfirmed editor buffers, autosaves with serialized
and coalesced requests, preserves exact uncertain requests for retry, and requires explicit
review of stale buffers. Save/discard-and-close wait for their acknowledgements; unavailable
storage fails truthfully and an explicit leave-unsaved action allows exit. Receipt identity
is checked before displaying saved status. Confirmation retires prior editor text atomically
with the answer, while old retries preserve newer edits. Cleanup failure rolls back the answer.

Validation: 49 focused Python tests (buffers, interview lifecycle, gateway RPC) and 41 TUI
tests (editor controller, interview interactions and component flow) passed. Canonical
`scripts/dev.py check` passed, including production TypeScript. The full suite was not run.
This does not close W07: new-question lesson capture, full provenance presentation and wider
reconnect/conflict qualification remain. Other W01–W09 criteria remain as recorded above.

Editor integration commit: `92607a6938`. The complete test TypeScript project remains
non-blocking and incomplete: stream harness types and legacy callback fixtures still
need migration. New typed RPC fixtures are accepted by the interaction harness without
requiring a caller to widen their closed method catalog to arbitrary strings.
