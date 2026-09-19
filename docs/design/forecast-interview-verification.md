# Forecast interview verification

Review checkpoint: 19 September 2026. This is engineering evidence, not evidence
that the feature improves predictive accuracy. The implementation is PR #65.

## Requested workflows

| Requirement | Implementation | Repeatable evidence |
| --- | --- | --- |
| Research-grounded elicitation | [Design and primary sources](forecast-interviews-and-scenarios.md); deterministic spine plus adaptive follow-ups | `test_interviews.py`, `test_interview_generation.py` |
| New-question and update interviews | Shared service, revision store and `ForecastInterview`; Desk `n` / `i` | Atomic question creation, update context capture, branch validation and rendered `interviewControls.test.tsx` |
| Assumptions and beliefs | Attributed probabilities, uncertainty types, rationale and evidence links; explicit editing | User ownership, historical revisions, stale writes and lost-response retries in backend and rendered TUI tests |
| Conditional scenarios and on/off ablations | Separate condition and exclusion contracts; shared evaluation owner | `test_scenario_evaluation.py`: matched calls, exact units/categories, cancellation, partial recovery, stale inputs and explicit-tail safeguards |
| Safe forecast updates | Preview and explicit unconditional-baseline promotion; ledger quality gates | `test_interview_rpc.py` round trip reconstructs the service for each request, evaluates with a controlled model, then promotes exactly once |
| Scheduled structured reviews | Forecast-ledger interview operations, required unattended review coverage, proposal-only guard | `test_interview_agent.py`, `test_commit_preview.py` and `test_reforecast_policy.py` |
| Markets shortcut | `F` captures exact series or selected prediction outcome without adopting its price as a user belief | `test_interview_sources.py`, `forecastSeeds.test.ts`, prediction-market keyboard/selection coverage |
| Stable News reading | Acquisition stages changes separately from visible publication; `u` applies updates | `newsOnboarding.test.tsx` checks selected content and bounded layouts at 80×24 and 120×40 |
| News-to-forecast evidence | `F` opens active-question search, attachment preview and optional update interview | Rendered attachment confirmation plus RPC/source tests for retry, rollback, revision grouping and unknown/future timestamps |

Test paths above are under `tests/forecasting/`, `tests/tui_gateway/`, or
`ui-tui/src/__tests__/`. Production owners and controls are documented in the
[interview README](../../forecasting/interviews/README.md).

## Verification status

- Full TUI suite: **2,266 passed, one skipped** (220 test files).
- Canonical lint, typing, architecture and generated-contract gates passed at
  the latest committed checkpoints.
- The controlled RPC review-to-promotion round trip passes with the declared
  optional request defaults and durable state restored on every request.
- Final canonical Python suite: **32,681 passed, 150 skipped**, no failures
  (571.64 seconds). The first run's six failures were fixed before this rerun.
  JUnit artifact: `.test-results/pytest-20260919T100145Z-79814.xml`.
- Final TUI suite includes real renderer dimensions at 60×18, 80×24 and 120×40,
  plus live resize from 120×40 to 60×18 and back to 140×40 with editor retention.
- The signed-webhook integration now executes structured review through the real
  agent tool loop before creating its pending proposal. Replay remains idempotent
  and the active forecast is unchanged.
- Historical evaluator compatibility was reviewed against source revision
  `90176bc000`: only the import/call initializing separate interview tables differs
  in evaluation-owned sources. Explicit compatibility entries preserve frozen
  trials; unknown hashes continue to fail closed.

## Explicit limits

- Generation and comparisons use controlled providers in engineering tests.
  Live-provider quality and eventual proper-score improvement are unproven.
- Factor ablation omits factors from reasoning while retaining the same evidence
  packet. It is not a causal intervention or blinded evidence-removal experiment.
- The system asks about dependence and conflicting beliefs. It does not prove
  arbitrary natural-language assumptions logically compatible, nor infer a causal
  graph or exact epistemic/aleatoric variance decomposition.
- Confirmed answers are durable. Unconfirmed text survives question navigation
  within the open interview but is not saved across closing the panel.
- Existing reference classes are captured and cited. Prose base-rate answers do
  not fabricate empirical anchors. A blocked preview directs the user to add a
  supported anchor and begin a fresh review before reevaluating.
- Source claims retain timestamps and identities but do not acquire verified
  settlement provenance merely by being attached. Syndication independence may
  remain unassessed.
- Interviews now have a wide section/question/context layout and a question outline
  with section jumps. Resize tests preserve unconfirmed text when switching between
  wide and compact layouts. Typed causal dependencies and distribution-valued
  assumptions remain unimplemented design extensions; current factors are explicit
  statements with probabilities, true/false conditions and exclusion toggles.

## Superforecasting and engagement review

The follow-up review corrected outcome-inappropriate base-rate prompts, misleading
section completion counts, unresolved-state regression, citation checks bypassed
by direct draft callers, overlapping generation requests and questionnaire wording
changes on reconfirmation. Regression coverage lives in `test_interviews.py`,
`test_interview_generation.py` and `interviewControls.test.tsx`.

Shared elicitation feedback now reaches the review screen and both AI paths.
It distinguishes missing reasoning from settlement errors and never treats an
answered questionnaire as proof of sound reasoning. The model instructions
prioritize useful cruxes, permit zero follow-ups, require outside-view/update
justification and distinguish repeated reporting from independent evidence.
Those instructions improve the requested behavior; controlled-provider tests
cannot establish compliance by every model or improved forecasting accuracy.

Remaining limits: base-rate prose is not an automatically verified reference
class; arbitrary causal dependencies remain elicited descriptions rather than a
validated probabilistic graph. Unconfirmed editor text is not durable after
closing the modal. These are explicit limits, not implied capabilities.

Review validation: the canonical runner passed **120 tests** covering interviews,
source attachments, frozen context, scenario evaluation, RPC, signed webhooks and
proposal commits. The rendered questionnaire suite passed **22 tests**, including
Unknown/Skipped progress, review guidance, resizing, recovery and old comparison
reports without reference-class fields. This is targeted validation of the review
changes; the earlier full-suite counts above belong to the preceding commit.
