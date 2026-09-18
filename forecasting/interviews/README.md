# Forecast interviews

Durable question-and-answer drafts for creating or reviewing a forecast. This
package owns interview validation and revision history; it does not call a model,
render the TUI, or change an active forecast probability.

| File           | Responsibility                                                                      |
| -------------- | ----------------------------------------------------------------------------------- |
| `models.py`    | Re-exports shared contracts from `protocol/interviews.py`                           |
| `store.py`     | Append-only ledger revisions, optimistic concurrency and retry identity             |
| `questions.py` | Required interview spine and outcome-specific elicitation                           |
| `news.py`      | Idempotent article attachment and evidence-linked update drafts                     |
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
follow-ups, scenario execution, update promotion and scheduled review integration
are still being implemented. An update interview currently saves the review
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
