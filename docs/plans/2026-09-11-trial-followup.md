# Trial reliability and remaining release evidence

## Implemented

`forecast trial candidates` is a read-only readiness audit. It reports missing
pre-cutoff evidence, absent applicable lessons, absent outcome-backed lessons and
unsupported loss families before an operator spends model budget. It does not
infer event independence from titles, companies or domains.

New trials use the `paired-learning-v3` response contract: a binary probability,
an exact categorical probability mapping summing to one, or `{mean, sd}` with a
positive standard deviation in the declared units. Every response includes a
nonempty rationale. Extra fields, numeric strings and renamed parameters fail
without rerolling. Named vote-share vectors are rejected at enrollment because
their existing MAE metric is not a comparable proper trial loss.

Trial specs accept `requests_per_minute` (default 6) and
`input_tokens_per_minute` (default 60000). Before claiming an arm, a transaction
reserves a provider-wide request slot and a conservative UTF-8-byte input estimate
plus framing allowance. A paused run returns `execution_pause` with a retry time;
resume with the same `forecast trial run` command. The pending arm is untouched.
Oversized individual requests report a non-retryable budget pause. These limits
cover this ledger's trial calls, not unrelated applications or readiness probes.
Provider failures still consume the attempted arm and stop the batch.

Execution retains its strict source identity. Completed evaluations use a separate
identity covering score computation, validation, frozen adjustment application and
the evaluator. A transport or prompt change cannot resume old pending arms, but
does not invalidate completed comparisons. The v2 request renderer is retained.
Evaluation reconstructs output from the raw provider receipt and frozen treatment;
a changed stored output cannot become a score comparison.

The compatibility registry explicitly maps reviewed historical source hashes from
49c9e0f18 and cbd7c15da/299b014a0 to the extracted evaluator. Their scoring, ledger,
models, learning, censoring and strict JSON modules were byte-identical to the new
evaluation dependencies. Unknown historical hashes fail closed. Historical trial
rows, requests, failures and packets are never rewritten. A future scoring change
requires another explicit compatibility review, not a version-label exception.

Profile listings and diagnostic dumps now use the same model/provider normalization
as execution; legacy root-level provider configuration no longer disappears from
those displays. The diagnostic-only `model.name` fallback remains supported.

openFDA fetching now delegates to a pure retained-payload parser. Latest-submission
selection uses parsed dates, so malformed date strings cannot outrank valid dates;
unknown dates remain unknown and cannot pass a `since` filter.

## Live evidence and limits

The September 11 readiness audit found 252 future-closing questions, 50 ready for
manual cluster review, 197 without applicable lessons, and 94 missing recorded
pre-cutoff evidence (categories overlap). Ready cases are concentrated in the
AI-infrastructure family. They cannot honestly be relabelled as 20 independent
clusters. The earlier eight complete pairs remain prospective, not resolved
accuracy results. No new calls were spent on untreated or unresearched cases.

All six deferred settlements were revisited. Michigan's official results endpoint
still returned 403. SpaceX's primary launch page yielded no usable record; the
historical question also needs an audited typed binding of its prose censoring
policy. The Manifold identity remains unconfirmed in the ledger. Two basket
questions concern an interval ending in June 2027. Reviews and reminders remain
append-only; no retrospective outcomes or probabilities were invented.

A live Gemini known-answer numeric response check passed with exactly `mean` and
`sd`; it is transport evidence, not forecasting accuracy evidence.

A 60-turn Unicode exercise across five process lifetimes, resizing and resuming,
passed locally with the cancellation, gateway respawn and PTY bridge checks.
The installed-lifecycle matrix now runs this recovery exercise on Linux/macOS.
Native Windows dashboard PTYs are unsupported; Android/Termux and unavailable
Daytona/Modal/web-search/Home Assistant credentials remain external requirements.

The formal v0.22.0 release targets merged PR #34 at b98f8a85d. This follow-up is a
separate change and is not represented as part of that release artifact.
