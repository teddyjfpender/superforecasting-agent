# Forecast interviews

Durable question-and-answer drafts for creating or reviewing a forecast. This
package owns interview validation, revision history and bounded adaptive
question generation. It does not render the TUI or change an active forecast
probability.

| File           | Responsibility                                                                      |
| -------------- | ----------------------------------------------------------------------------------- |
| `models.py`    | Re-exports shared contracts from `protocol/interviews.py`                           |
| `store.py`     | Append-only ledger revisions, optimistic concurrency and retry identity             |
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
for the planned transport, questionnaire UI and scheduled-review integration.

## Current interaction

In the Desk, `n` opens a new-question interview and `i` revisits the selected
forecast. Confirm text answers with Ctrl+Enter, choices with Enter, move with
Tab/Shift+Tab, and use Ctrl+U for Unknown or Ctrl+S to Skip. Confirmed answers
are durable; unfinished text is retained while moving between questions but is
not saved when closing. Reopening resumes the latest uncommitted interview.
The review page scrolls with Page Up/Down. Creating a question requires explicit
confirmation and is idempotent for the reviewed revision.

The deterministic questionnaire works without model credentials. Adaptive model
follow-ups and scenario selection are available; scenario execution, update
promotion and scheduled review integration are still being implemented. An update interview currently saves the review
draft and does not change the active probability.

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
It does not yet prove a matched provider route for scenario comparisons. Stale
results remain in job annotations and cannot overwrite newer user edits.
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
These definitions are not yet evaluated predictions and cannot change the active
forecast probability.
