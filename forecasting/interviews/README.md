# Forecast interviews

Durable question-and-answer drafts for creating or reviewing a forecast. This
package owns interview validation and revision history; it does not call a model,
render the TUI, or change an active forecast probability.

| File        | Responsibility                                                          |
| ----------- | ----------------------------------------------------------------------- |
| `models.py` | Typed questions, attributed answers, assumptions and scenario semantics |
| `store.py`  | Append-only ledger revisions, optimistic concurrency and retry identity |

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
