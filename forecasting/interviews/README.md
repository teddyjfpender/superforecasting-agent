# Forecast interviews

Durable question-and-answer drafts for creating or reviewing a forecast. This
package owns interview validation, revision history and bounded adaptive
question generation. It does not render the TUI or change an active forecast
probability.

| File           | Responsibility                                                                      |
| -------------- | ----------------------------------------------------------------------------------- |
| `models.py`    | Re-exports shared contracts from `protocol/interviews.py`                           |
| `store.py`     | Append-only ledger revisions, optimistic concurrency and retry identity             |
| `context.py` | Immutable question, baseline and evidence captures with integrity checks |
| `questions.py` | Required interview spine and outcome-specific elicitation                           |
| `news.py`      | Idempotent article attachment and evidence-linked update drafts                     |
| `generation.py` | Frozen input packets, idempotent job enqueue and validated proposal application |
| `model_worker.py` | Isolated model call with an owned cancellation/deadline boundary |
| `service.py`   | Begin/resume, attributed answers, validation preview and explicit question creation |

Every save supplies the revision the caller read and a stable request ID. Retrying
the same request returns its original result; a stale or changed request fails.
Answered question meanings and the target/baseline cannot change in place. Agent
writers may retain user answers but cannot invent, edit or delete them. Actor
identity must come from the calling application, not model-generated JSON.

Conditional scenarios assert conditions. Ablations exclude factors from an
analysis; exclusion does **not** mean the factor is false. Neither is a scored
forecast. Publishing a forecast requires the separate explicit ledger commit path.

Run `scripts/run_tests.sh tests/forecasting/test_interviews.py` from the repository
root. See [the implementation design](../../docs/design/forecast-interviews-and-scenarios.md)
for the design rationale and acceptance criteria.

## Current interaction

In the Desk, `n` opens a new-question interview and `i` revisits the selected
forecast. Confirm text answers with Ctrl+Enter, choices with Enter, move with
Tab/Shift+Tab, and use Ctrl+U for Unknown or Ctrl+S to Skip. Confirmed answers
are durable; unfinished text is retained while moving between questions but is
not saved when closing. Reopening resumes the latest uncommitted interview.
The review page scrolls with Page Up/Down. Creating a question requires explicit
confirmation and is idempotent for the reviewed revision.

The deterministic questionnaire works without model credentials. Adaptive model
follow-ups, scenario comparisons and explicit baseline promotion are available.
An update interview saves a draft; changing the active probability requires
separate preview and confirmation. Scheduled reviews use the same application
owner through the forecast ledger tool.

## Markets and News handoffs

Press `F` on a Markets row to start a forecast interview. Multi-outcome prediction
markets require expanding the event and selecting an outcome first. The draft
retains the exact source identifiers, available units and timestamps; source
prices remain observations, not answers attributed to the user. Imported source
context is not a verified settlement binding.

Press `F` in News to find an active forecast and review the article before
attaching it. Choose either evidence only or evidence plus an update interview.
Retries deduplicate equivalent article captures. Revised content stays grouped
with the original URL, while syndication independence remains unassessed.
Unknown publication times stay unknown, and these user-selected claims are not
admissible for historical backtests by default. No attachment changes a forecast
probability or automatically starts an agent run.

## Adaptive generation backend

`forecast.interview.generate` accepts an interview revision, stable `request_id`
and optional provider/model, question count, token budget and wall deadline.
Defaults are eight follow-ups, 4,000 output tokens and 90 seconds; hard bounds
are enforced by the shared contract. This is an explicit paid model operation.
In the interview, Ctrl+G opens generation settings and restores the latest job
for that interview. Choose budgets with arrows, optionally enter provider/model
identifiers, then select Generate. Ctrl+X requests cancellation; Escape returns
to answers without cancelling. Completed questions open only on Ctrl+R. A status
lookup failure disables new calls until durable state can be read again.

The `forecast_interview` job type uses the shared durable job store and spend
policy. Poll `jobs.status` and cancel with `jobs.cancel`; detached execution uses
the active profile. Repeating a start request returns the same job, and a kernel
claim prevents concurrent execution. A crash after storing validated output
reuses that output without another call. A crash before output is stored may
require another provider call; provider-level exactly-once billing is not promised.

Model output can append optional questions and proposed assumptions, never user
answers. Provenance includes the frozen input revision/digest, prompt digest,
requested provider, reported response model and output-token usage when supplied.
Generation provenance alone is not a matched comparison; scenario evaluation
also compares prepared-request fingerprints. Stale results remain in job
annotations and cannot overwrite newer user edits.
Cancellation terminates and reaps the owned model process; a cancelled response
is not applied. No live-provider forecasting-quality claim follows from these
synthetic failure and recovery checks.

## Choice answers and scenarios

Choice questions offer an explicit Other entry when custom input is allowed.
Use Space to toggle multiple selections and Ctrl+Enter to save them. Custom text
is stored separately from choice identifiers; Unknown/Skip carry neither.
Tab and Shift+Tab move between questions without discarding local text/selection
edits. Confirm an answer to make it durable before closing the interview.

Ctrl+O opens the scenario library. A **conditional scenario** fixes selected
assumptions true (`t`) or false (`f`); `u` removes that condition and leaves it
uncertain. A **factor ablation** uses Space to include/exclude factors, without
asserting excluded factors false. Use `n` to name a scenario, Enter to inspect a
full assumption and its attribution, and Ctrl+Enter to save. Existing scenarios
can be reopened and edited; Ctrl+D asks for confirmation before deletion.
Revisions retain history. Agent writers cannot overwrite user-owned scenarios.
Definitions alone do not change the active forecast probability. Run comparisons
with Ctrl+E, then explicitly preview and confirm an unconditional baseline if
you choose to promote it.

## Frozen update context

Opening an update captures the complete question contract, current snapshot and
evidence records in the same ledger transaction as the first draft. The draft
references that capture by SHA-256. Generation reads this packet, not later
ledger values; corrections and newly attached evidence require a new interview.
Evidence retains timestamps, independence metadata and verification status.
Oversized packets fail the prompt-size check rather than silently dropping
evidence. Legacy drafts without a capture must be reopened as a new update
before model generation. A capture is reproducibility evidence, not a claim
that the sources have been verified.

An update carries assumptions and scenario definitions from the latest
non-cancelled interview for that question, including its committed creation
interview. The parent ID, revision and digest are immutable. Original user/agent
attribution is retained, and an agent cannot alter inherited user content.
Earlier answers are available to the interviewer as explicitly historical
context; they are not copied into newly answered questions or represented as
current user confirmation. A prior draft also does not replace the active
forecast baseline.

## Scenario evaluation backend

The `forecast_scenarios` durable job takes an interview ID/revision and
`ScenarioEvaluationOptions`: one to eight saved scenarios, one to three
repetitions, and the same bounded model-call settings as generation. Each
repetition contains one unconditional baseline and each selected variant.
The plan is persisted before spending; completed calls are stored individually
and reused after interruption. No result writes a forecast snapshot.

Estimates use strict numeric schemas, exact category labels and units, and
existing evidence IDs. Continuous results are direct q10/q50/q90 estimates;
these do not authorize Gaussian tail reconstruction. Comparisons report paired
changes and observed model dispersion (unmeasured for a single repetition).
Request settings and reported response-model identity must match across calls.
Fingerprints do not expose credentials or raw endpoint URLs, and cannot prove
what happens inside a provider's infrastructure.

Ablations exclude factors from the reasoning task; the same source packet is
retained in every variant. They are sensitivity analyses, not blinded information
experiments, causal effects or evidence of calibration. Conditional outputs stay
conditional. Scheduled review operations are described below.

### Comparing in the TUI

Ctrl+E opens **Evaluate scenarios**. Toggle saved scenarios with Space, adjust
repetitions/output caps with Left/Right, and select Run only after reviewing the
call/token total. Provider/model overrides use Enter. Each call has a 90-second
execution deadline. Ctrl+X cancels; Escape leaves the durable job running.
Only one evaluation per interview can run at a time; retrying a lost start
response retains its request identity.

Ctrl+R explicitly opens completed comparisons. The reader starts at the top and
scrolls with arrows or Page Up/Down. It shows frozen scenario definitions,
assumptions, per-run reasoning, unresolved questions and cited evidence.
Probabilities use percentages; differences use percentage points. Stale
interviews/contracts/baselines are labelled historical. No comparison becomes
a forecast without a separate promotion action.

### Explicit promotion

In a completed comparison, Ctrl+P opens promotion for unconditional baseline
runs only. Left/Right selects a repetition; Enter runs the ledger preview;
Ctrl+Enter accepts its exact candidate. The preview includes configured
probability clamps and displays ledger blockers. It never disables citation,
style, output-shape or other ledger gates to make a candidate pass.

Promotion refuses changed interviews, active baselines and resolution contracts.
The snapshot and promotion receipt commit in one transaction, and retries return
the same snapshot. Frozen call provenance and attributed assumptions are copied
into snapshot metadata. Conditional scenarios and ablations cannot be selected.
Continuous quantiles remain quantiles; no Gaussian or tail probability is
invented to satisfy a censored-outcome contract. A new-question interview must
first create its reviewed question. Reopening the preview restores the saved
forecast ID after a lost response.

## Scheduled and agent-owned reviews

Agents use `forecast_ledger` action `interview` with a typed `interview_request`.
Operations are `begin`, `read`, `answer`, `propose` (adaptive questions and
assumptions), and `scenario`. Begin after evidence collection so the review
captures that evidence. Writes require the current revision and a stable
request ID; retries preserve identity. All answers/scenarios are agent-attributed.
Proposed follow-ups share the interactive validator and do not start another
model call or manufacture a provider receipt.

Unattended `update_forecast` calls must pass a completed `interview_id`. The
application checks the question, baseline, contract, cited evidence and eleven
review topics covering evidence, reference classes, assumptions, dependence,
uncertainty, counterevidence and triggers. Unknown is valid and explicitly
recorded; skipping the review is not. The proposal stores its review revision,
digest, unresolved questions and attributed assumptions. New evidence or a
changed baseline requires a fresh review. The existing proposal-only runtime
boundary remains in force, so scheduled agents cannot promote live snapshots.
