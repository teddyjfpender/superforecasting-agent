# CLI Guide

Task-oriented walkthroughs for the `forecast` CLI. This is the *how do I…* guide;
for the exhaustive command tree (every subcommand and flag, introspected from the
code) see [reference/cli-reference.md](reference/cli-reference.md).

`forecast`, `superforecasting-agent`, and `superforecast` are the same entry point
(`superforecasting_agent/cli.py` → the argparse tree in the `forecasting/cli/`
package).
Bare `forecast` prints the desk dashboard summary; `forecast tui` opens the TUI;
`forecast <command>` runs a workflow.

```bash
forecast tui             # open the forecast desk TUI (also: superforecasting-agent --tui)
forecast                 # bare invocation prints the desk dashboard summary
forecast status          # desk state, calibration, live baseline comparisons
forecast doctor          # one-shot operational / pilot / readiness gate
forecast about           # fork identity and forecast-first scope
```

---

## The laziest path: one sentence → a committed forecast

The intended path is a single sentence. `onboard` structures the question (infers
the deadline, accepts recommended defaults, refuses only genuinely unscoreable
asks), attaches recommended watched sources, then runs research → base rate →
committed forecast through the **same gated pipeline** a hand-driven session uses:

```bash
forecast onboard "Will the Fed cut rates by September?" --auto
```

What you get without asking: no rival duplicate questions (`--force-new`
overrides), an auto-started multi-model quorum on high-impact calls, a nightly
self-check cron installed on first commit, auto-scoring + lesson synthesis on
resolution, and keep/skim/skip triage of watched-source reading. In chat, the
same journey is one tool call — ask the agent to forecast something and it uses
`full_forecast`.

---

## The hand-driven path

### Create and research a question

```bash
forecast new "Will X happen?" --resolution-criteria "Resolved yes if ..." --source-plan
forecast sources --question <id> --apply-watch      # discover + attach watched sources
forecast evidence add <id> <url-or-note>            # attach timestamped evidence
forecast research <id> <source...>                  # capture evidence WITHOUT moving probability
forecast base-rate <id> ...                          # anchor on a reference class first
```

### Import external context as evidence

The `import` family runs source adapters (RSS, econ/fiscal data, filings, papers,
weather, and dozens more — 59 adapters at last count; the full list is
`forecast import --help`):

```bash
forecast import news <rss-or-atom-url> --question <id> --materiality high
forecast import fred UNRATE --question <id>            # an economic series
forecast import sec 0000320193 --question <id>         # company filings
forecast import arxiv "cat:cs.AI AND forecasting" --question <id>
```

### Reason and commit

```bash
forecast model <id> --type bayesian_update ...         # record a model run
forecast bayes ...                                     # the auditable Bayesian scratchpad
forecast panel record <id> ...                         # record a perspective panel
forecast quorum <id> ...                               # multi-model Delphi panel
forecast update <id> --probability 0.63 --rationale "..."   # append a snapshot (gated)
```

`update` also takes `--numeric-value` for numeric questions. The commit is gated —
if a hook rule blocks (e.g. missing components or stale evidence), it tells you
what to add. See [forecasting-methodology.md](forecasting-methodology.md).

### Find things without copying IDs

```bash
forecast search "gasoline CPI"     # match by title, topic, domain, rationale, or evidence
forecast list                      # the active forecast book
forecast show <id>                 # full detail for one question
forecast review --stale            # beliefs due for a look
```

---

## Resolve, score, and learn

```bash
forecast resolve <id> --outcome yes          # record the outcome (auto-scores)
forecast score <id> --baselines              # score vs base-rate / crowd / market
forecast postmortem <id>                      # structured post-resolution diagnosis
forecast calibration --by-origin --all        # your reliability curve + trend
forecast errors                               # domain error-profile summary
forecast lessons                              # calibration lessons
forecast lessons apply <lesson>               # compile a lesson into an enforced hook rule
forecast lessons audit                        # per-lesson: applied / dormant
```

Become the forecaster: `forecast drill --n 5` replays resolved binaries and scores
you instantly; `forecast calibration --operator` compares you to the system.

---

## Autonomy and maintenance

```bash
forecast freshen <id> --cadence daily         # put a forecast on a refresh cadence (+ cron)
forecast autopilot enable <id> --source <adapter>:<src> --cadence 1d --mode propose
forecast autopilot run <id>                    # run source checks + generate proposals
forecast schedule add --domain macro --topic inflation --cadence 1d --auto-score
forecast schedule run --due                     # run due self-checks
forecast cycle run                              # the closed-loop forecast cycle
forecast watch check                            # check watched sources for changes
forecast alerts                                 # list + reconcile forecast alerts
```

---

## Hooks (the commit gate)

```bash
forecast hooks list                             # active rules + resolved severity (and why)
forecast hooks profiles                         # curated profiles + their severities
forecast hooks explain <signal>                 # what a DSL signal means
forecast hooks set-severity <rule> off|warn|error
forecast hooks add <spec.json>                  # validate + save a custom rule
```

The built-in rules (43 at last count) are documented in
[reference/hooks-rules.md](reference/hooks-rules.md), which is regenerated from
the rule registry.

---

## Markets and prediction markets

```bash
forecast market-nightly sample ...              # sample the live market-hidden harness
forecast market-nightly run ...                 # run the nightly forecaster
forecast market-nightly report                  # paired agent-vs-market edge roll-up
forecast market-quality ...                     # market-quality diagnostics
```

The agent pulls prediction-market priors structurally through the `forecast_ledger`
tool's `pm_query` action (search / event / book / history), returning the same
de-vigged distributions the [Markets view](operating.md) renders. Provider and
venue registry: [reference/providers.md](reference/providers.md).

---

## Backtest, benchmark, and export

```bash
forecast backtest builtin:heldout-120-binary                        # replay a dataset
forecast backtest --all-benchmarks --probability-source forecast-engine
forecast bench                                                       # ForecastBench scoreboard
forecast readiness --json                                           # claim-readiness gaps
forecast performance --live                                          # live scores
forecast export all --format json --output export.json              # auditable packet
forecast import packet export.json --conflict skip                   # restore a packet
```

Source-bound JSON packets now carry their archived source bytes and measurement
bindings. On another instance these are **imported claims**, not locally verified
evidence. Inspect their status and explicitly re-fetch the canonical source:

```bash
superforecasting-agent forecast facts show <question-id>
superforecasting-agent forecast facts verify-import <question-id>
```

Identical bytes acquire a local verification timestamp; changed sources remain
imported with an explanation. Verification does not authenticate the original
forecast timing or make imported scores eligible for calibration. Original records
remain in the packet's transfer history.

For economic settlement, `facts bind-source` supports reviewed BLS monthly series
with `--revision-policy as_captured`, and FRED with `first_release` or an explicit
`vintage` date. FRED also requires archived series metadata proving physical units
and frequency. Observation dates are not publication timestamps. See the
[source-contract and transfer guide](plans/2026-09-11-source-portability-runtime.md)
for semantics and limits.


---

## Data-provider API keys

```bash
forecast api-key list                           # providers + whether a key is set (redacted)
forecast api-key set fred <key>                 # persist to the user .env and activate
```

Note: `api-key` manages **data-source** keys (FRED, EIA, Firecrawl, …). LLM
provider sign-ins are handled separately by the setup/auth flow, not here.
