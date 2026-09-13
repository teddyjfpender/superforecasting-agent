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
still returned 403. SpaceX's rendered page was an empty shell, but inspecting its
public data endpoint recovered the primary Flight 13 launch confirmation. It is
now archived as evidence; the historical question still needs an audited typed
binding of its prose censoring policy. The Manifold identity remains unconfirmed in the ledger. Two basket
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


## Credentialed test invocation

Ordinary tests erase provider credentials by design. Live Daytona/Modal tests now
require explicit service selection and restore only that service's environment
keys after hermetic isolation. With credentials already supplied in the process
environment, use:

```bash
.venv/bin/python -m pytest -o addopts="" --live-service=daytona tests/integration/test_daytona_terminal.py -v
.venv/bin/python -m pytest -o addopts="" --live-service=modal tests/integration/test_modal_terminal.py -v
```

The canonical `scripts/run_tests.sh` deliberately strips credentials and is for
hermetic verification, not this opt-in live path. Missing credentials or absent
opt-in are explicit skips, never successful service checks. These tests create
and clean up test sandboxes. No unavailable credentials were fabricated.

Primary launch archive: https://content.spacex.com/api/spacex-website/missions/starship-flight-13
(the mission narrative, not image upload timestamps, establishes the launch).

## Lifecycle atomicity and release-test deadlines

Question insertion and its initial review schedule now commit in one transaction.
An interrupted schedule write rolls back the question instead of leaving an
active question without its intended review. The injected scheduling failure
regression passed, along with the trial integrity tests.

The first v0.22.0 release attempt reached 30,211 passing tests but failed five
runtime deadlines. A duplicate SIGALRM fixture ignored the release workflow's
`--timeout=60`; pytest-timeout is now the sole deadline owner. The heavy offline
benchmark smoke subprocess has its own bounded 300-second allowance, within a
600-second lifecycle subprocess and a 660-second test cap. Ordinary tests retain
their 30-second default. All seven targeted smoke/calibration regressions passed.

The subsequent forecasting suite passed 3,470 tests with three skips and exposed
two watch gate tests accidentally doing DNS lookups on fictitious `.test` URLs.
Those dispatch tests now stub the network signature boundary; their four cases
and the atomicity regression pass. Source-fetch behavior remains independently
tested. These follow-up fixes do not change the immutable v0.22.0 tag.

The expanded Linux/macOS recovery matrix exposed coalesced text/Enter handling
and a shutdown path without a deadline. The terminal tokenizer now preserves
control keys within a single read and keeps bracketed paste literal. Stdin EOF
uses the same bounded shutdown fallback as termination signals. The soak test
waits for the desk's completed-turn status: a visible final token can precede
`message.complete`, so Ctrl+C at that point correctly interrupts instead of
exiting. The PTY verification harness now decodes UTF-8 incrementally, avoiding
corrupted screen assertions when one character spans multiple output reads.

The sustained test additionally exposed an old React handler's delayed thinking
status overwriting `ready` after `message.complete`. Delayed status updates now
check that the turn is still busy. A regression simulates handler replacement;
removing the guard makes it fail. This repairs the visible lifecycle state,
not the underlying forecast record. The 2,020-test TypeScript suite passed before
this final timer fix, followed by all 59 gateway-handler tests with the fix.

With the status correction, all eight real-terminal recovery/shutdown tests
passed in 83 seconds, including 60 Unicode turns across five process lifetimes,
stalled-stream cancellation, durable resume, gateway respawn and hard client
termination. The harness/EOF unit checks passed 15 tests; terminal parser checks
passed 57. Linux/macOS CI must rerun these fixes before claiming platform parity.

## Release and platform closeout

The second v0.22.0 gate attempt failed with 30,214 tests passing and 163 skips:
a hierarchical-calibration read raised SQLite `not authorized`, and another
worker crashed in SSL certificate loading inside a background banner update
check. No release assets were published. The first attempt's duplicate deadline
mechanism is removed in this follow-up, but the second SQLite error has not been
independently attributed to it. Do not describe these failures as resolved
release evidence.

The crash dump contained multiple concurrent banner update-check threads.
`prefetch_update_check` now shares one in-flight thread and always signals
completion on failure. A blocked-provider regression confirms that 100 extra
prefetch calls do not create additional workers. Seventy focused update-check,
build-identity, doctor, TUI startup and hierarchical-calibration tests passed.
This addresses thread accumulation; it does not claim to prove the SSL crash's
complete cause.

The updated macOS CI job passed fresh install, upgrade and sustained recovery;
Windows passed install/upgrade. Linux passed the soak/input checks but its
hard-kill assertion still reported an orphan. The assertion now distinguishes
an exited zombie from a running worker and includes live process status on
failure. Its regression proves sleeping workers still fail the live-orphan
check; three local respawn/orphan tests passed. Linux verification remains
pending for that test correction.

Publishing the corrected code requires a release-identity decision: preserve the
existing v0.22.0 tag and use v0.22.1, or explicitly replace the unpublished tag
while preserving the failed candidate in an audit ref. No tag was moved and no
failed gate was bypassed.
