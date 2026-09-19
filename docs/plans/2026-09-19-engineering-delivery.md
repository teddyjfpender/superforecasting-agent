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
| W02 quality ratchet | In progress | Added test TypeScript project; measuring and fixing existing diagnostics before making it blocking. Remaining coverage ratchet, typed fixtures and execution tiers. |
| W03 typed sources | Pending | All specification criteria remain. |
| W04 CLI parity | Pending | Legacy active-provider behavior corrected as part of W01; shared command inventory/parity remains. |
| W05 runtime ownership | Pending | All specification criteria remain. |
| W06 TUI state | Pending | All specification criteria remain. |
| W07 questionnaire durability/lessons | Pending | All specification criteria remain. |
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
