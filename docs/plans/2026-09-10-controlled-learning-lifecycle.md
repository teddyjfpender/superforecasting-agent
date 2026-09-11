# Controlled learning and durable review

Three shared ledger capabilities now connect the public CLI, agent forecast
context, and Ink desk. They use additive tables in the existing SQLite database;
there is no separate experiment service or alternative dashboard transcript.

## Prospective comparison

Create a JSON specification before outcomes are known:

```json
{
  "assignments": {"fq_first": "independent_event_a", "fq_second": "independent_event_b"},
  "provider": "your_configured_provider",
  "model": "your_explicit_model",
  "max_tokens": 2048,
  "min_clusters": 20,
  "minimum_effect": 0.0
}
```

Run `superforecasting-agent forecast trial create --spec-file cohort.json`,
then `forecast trial run <id> --limit 4`. Inspect `forecast trial report <id>`
and retain `forecast trial export <id> --output trial.json` (private file).
`forecast trial list` is also reachable from `/ledger learning` in the TUI.

Enrollment requires active questions, future close times, recorded evidence and
no existing resolution. Both arms receive the same frozen question contract and
evidence packet, model and output-token cap, with no tools, external memory or
agent context injection. Only the learning arm receives frozen applicable lessons
and error profiles. Explicit binary calibration adjustments are applied after the
model output, with the raw estimate retained. Physical quantities are never
clamped or shifted as binary probabilities.

The trial persists both arms before execution, randomized order per declared
cluster, exact requests, provider/model receipts, outputs, errors and leases.
Failed or interrupted arms cannot be silently rerolled. `forecast trial recover
<id>` marks expired leases interrupted; restarting does not repeat completed
calls. Trials never write live forecast snapshots or live calibration scores.

Reports use confirmed, criteria-satisfied outcomes and the shared scoring kernel.
Changed contracts, late forecasts, mismatched provider/model receipts, invalidated
lesson sources and corrupted packets cannot become accuracy gains. Different
score rules and physical units remain separate. The estimator equally weights
operator-declared event clusters, with a deterministic cluster bootstrap interval.
Missing pairs remain in the assigned denominator. A positive finding requires the
predeclared minimum cluster count, complete cohort, one comparable scoring group,
and a lower interval bound above the minimum effect. Twenty clusters is a default
screen, not a statistical power guarantee.

This measures the bounded closed-book lesson-context plus adjustment policy. It
cannot establish the benefit of autonomous research, causal benefit of each lesson,
or general forecasting superiority. Cluster independence remains an operator
judgment. Actual evidence of benefit requires prospective outcomes; test fixtures
are software validation only. A source hash pins scoring, numeric treatment and response validation;
changed implementation code requires the original release to reproduce a trial rather
than silently mixing score versions. Export preserves the frozen inputs and
receipts; keep a SQLite online backup and release wheel for full restoration.

## Evidence-backed conditions

`forecast facts bind <question> --key weather.period_complete --source-url
https://source.example/observation.json --value-pointer /properties/complete
--observed-at-pointer /properties/timestamp --value-type boolean
--max-age-seconds 3600` binds a fact to an explicitly trusted source schema.
The URL and pointers above illustrate a schema; they are not a weather API preset.
Capture the real source through the existing evidence URL command first.

A lesson can require `"applicability": {"evidence_equals":
{"weather.period_complete": true}}` inside its recommended_adjustment object. This is different from
`metadata_equals`, which remains available for declared question characteristics.
Agent-supplied metadata cannot satisfy `evidence_equals`. Source receipts are
created by the evidence fetch path, archives are hashed, and observation/capture/
availability times are checked against the forecast cutoff. Missing, stale,
malformed, tampered or unverified archives yield an explicit unknown condition.
The latest eligible capture wins; invalid newer evidence cannot be bypassed by
selecting a more convenient older observation.

`forecast facts show <question>` explains missing conditions and provenance.
Question details show bound facts and source-refresh actions; the agent protocol
receives the same facts. Snapshot metadata freezes the decision evidence.
Older archives without fetch receipts remain unverified until genuinely recaptured.
Bindings prove what a selected source said; they do not prove that its measurement
or the operator's interpretation is correct. In particular, an afternoon clock
reading does not establish that a day's weather maximum has passed.

## Deferred settlement

`forecast lifecycle review <question> --state awaiting_source --reason "Need
certified counts" --source "official results page" --next-action "Check certified
statewide totals" --owner operator --revisit-at 2026-09-17T12:00:00Z` appends a
review decision. Supported states are ready, awaiting_source, future_outcome,
identity_unresolved, censoring_required, and no_historical_forecast.

Deferred states require a future revisit time, owner, source, reason and next
action. The shared lifecycle worker emits one durable alert per due review,
transactionally with its notification marker, including across restart and
acknowledgment. A new review supersedes the old reminder without erasing history.
The existing scheduler and TUI maintenance invoke the worker; no additional daemon
is required. If neither is running, `forecast lifecycle run` delivers due reminders
on the next invocation. No background action changes a probability or invents an
outcome.

A resolved question with no historical snapshots can be explicitly marked
no_historical_forecast. It remains a documented limitation in the desk and full
report, instead of an endlessly retried scoring task. It receives no synthetic
forecast or score. Right-censored outcomes still need a separate representation
and proper scoring implementation; censoring_required records that blocker.

## Live-provider hardening (0.21.1)

The real Gemini pilot exposed a serialization gap: quarantine existed as a score
ledger column but was missing from `ScoreRecord` and score JSON exports. Typed
scores now preserve it; a regression uses actual scored lesson provenance and
verifies exclusion after quarantine. Trial responses accept a single complete
JSON code fence as a transport wrapper, retaining the untouched response. They
still reject malformed JSON, duplicate keys and additional prose; no model retry
or outcome-dependent repair occurs. Trial reports include treatment coverage so
an error-profile-only cohort cannot be mistaken for a lesson-bearing cohort.

The first live cohort used the inherited `market_nightly` domain and had no
applicable politics lessons. Its failed/interrupted calls are retained. A separate
cohort uses existing `politics` questions and freezes their applicable lessons.
Both cohorts belong to one correlated 2026 Senate election cluster; they are
operational pilots, with outcomes still pending, not evidence of improved accuracy.

JSON packet imports retain capture receipts as `imported_source_capture`, rather
than treating caller-supplied metadata as a locally verified fetch. Recapture the
source to authorize a current source-backed condition. SQLite online backups
preserve the original instance's complete operational state.

## Verification and live outcome

The deployed runtime is **0.21.2**, built from commit `9846723e5`; subsequent
verification-document commits do not change that wheel. See the
[verification record](../verification/2026-09-10-controlled-learning-lifecycle.json).
The forecast suite passed 3,449 tests (three skips); the TUI suite passed 2,015
(one skip). Later import/report regressions passed separately. Fresh installation,
upgrades, real source capture, scored lesson provenance, paired local-provider HTTP
calls and installed 150/80/150-column TUI report navigation were exercised.

The live profile retains all 7,403 original snapshots unchanged. Six reviewed
settlements now have durable blockers and future revisit dates; two outcomes with
no historical forecast are documented terminal limitations. Repeated recovery
finds no unfinished finalization work.

The real-provider lesson-bearing pilot enrolled two existing politics questions,
froze four lessons for each, and retained all four failed attempts: high-demand
503 errors, incomplete output and a timeout. It has zero usable pairs. This is a
recorded operational failure, not an accuracy result; waiting for outcomes alone
will not make the missing pairs usable. A new prospective cohort with an available
provider and sufficient response budget is required. The earlier aborted cohort
is retained as well. No failed arm was silently rerolled and no live probability
was changed. The report-only update to 0.21.2 preserves the enrolled trial's
execution/scoring identity.
