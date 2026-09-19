# W07 questionnaire acceptance

Implementation acceptance reviewed against W07 of the engineering specification.
This is focused engineering evidence, not final merged-product qualification or
proof that lessons improve calibration. Native/release qualification remains W09.

| Requirement | Owner and evidence |
| --- | --- |
| Acknowledged drafts survive restart as unconfirmed content | `forecasting/interviews/buffers.py`; `test_acknowledged_buffer_survives_process_exit` and the real Ink/gateway/SQLite/dashboard test `test_real_questionnaire_draft_survives_reconnect_and_terminal_restart` (unchanged, concurrent-answer and process-death cases). The latter ran in the bounded native Linux quality job at `74ec3aaa68`. |
| Truthful save state; failure does not promise durability | `ui-tui/src/__tests__/interviewBuffers.test.ts` and `interviewControls.test.tsx` cover acknowledgements, failed saves, stale replies, remounts and explicit leave/discard paths. |
| Idempotent save/confirm; no answer or forecast mutation on save | `tests/forecasting/test_interview_buffers.py` covers receipts, concurrent revisions, rollback, confirmation cleanup, late retry, migration and profile isolation. Buffers are separate from answers and promotion. |
| Discard and retention | Latest text persists until discard, confirmation, commit or cancellation; retry receipts retain acknowledgements/hashes rather than discarded text. Profile removal removes its database. Secret prompts have separate RPC owners and are not buffer consumers. |
| Frozen applicability and provenance | `tests/forecasting/test_interview_context.py` covers exact digests, included/excluded lessons, supersession, future cutoff, missing score/postmortem support, unknown independent-cluster counts and historical contexts without backfill. |
| Generation/evaluation share frozen guidance | `test_generation_and_all_scenario_calls_consult_same_frozen_lessons` changes the live library after freezing and checks both baseline and conditional calls against the generation packet. The active forecast is unchanged. |
| Budget admission preserves the packet | `test_prompt_budget_rejects_without_truncating_durable_context` verifies over-budget rejection while the entire stored evidence/context remains identical. Evaluation also rejects oversized serialized calls before execution. |
| Accessible concise guidance and provenance | TUI controls cover Ctrl+Y guidance, expandable provenance, sparse/unknown support, mismatch/retry, and returning without answer confirmation at 60×18, 80×24 and 120×40. Unknown/skip and outline/review remain available. This is not a screen-reader compliance claim. |

## Verification receipt

At source `602e0bef8a` plus the two new acceptance tests:

- 57 focused buffer/context/generation/agent tests passed.
- The context/scenario group passed 47 existing/other cases; the new matched-lesson
  case passed after correcting its fixture status and snapshot comparison.
- The new oversized-context preservation test passed.
- 48 TUI buffer/control tests passed.
- No full suite was run.

The tests establish consultation and lifecycle invariants, not empirical forecast
improvement. New-question interviews have no confirmed domain/outcome at initial
capture; their frozen selection intentionally admits only general guidance.
Reclassification must never rewrite historical contexts. Additional classified
capture workflows are future product work, not a reason to mutate this packet.
