# Superforecasting Agent Fork Context

## Strategic Thesis

The fork should not add forecasting as a feature on top of Hermes Agent. It should invert the product around a new primitive: the forecast.

Hermes is a general assistant with tools. The fork should become a research desk that maintains probabilistic beliefs over time. The core object is no longer a chat turn, session, or generic task. The core object is a scoreable forecast with an append-only history, evidence, assumptions, models, resolution, score, and postmortem.

The north star:

> A command-line forecasting desk that compounds judgment over time.

## Product Difference From Hermes

A general agent can answer a question and move on. A forecasting desk must maintain standing beliefs, notice when those beliefs are stale, update when new evidence arrives, and improve over months through resolved outcomes.

That difference changes the architecture:

- Chat history becomes secondary to forecast history.
- Memory becomes calibration memory and evidence memory, not generic conversation recall.
- Tool use becomes stage-gated around research, modeling, updating, resolving, and scoring.
- The CLI home screen shows active beliefs and required reviews, not a blank assistant prompt.
- Long-term performance is measured by calibration and scoring, not by whether a single answer sounded plausible.

## Domain-General Scope

The product should be good at any scoreable question, not optimized around one forecasting platform or tournament format. Metaculus, prediction markets, public datasets, research papers, financial data, news, and private user notes are all possible inputs, but none should become the center of gravity.

Platform-specific ingestion is useful when it extracts question metadata, crowd forecasts, priors, posteriors, resolution criteria, market-implied probabilities, news context, economic time series, public open-data rows, health indicators, emergency declarations, equity/ETF/index price charts, crypto market snapshots, company filings, XBRL fundamentals, research papers, biomedical literature, software package releases, repository activity, workflow-run status, and benchmark probabilities. It should behave like an adapter that enriches the ledger, not like the product's main workflow. For example, Metaculus can attach visible crowd forecasts as baseline comparisons and import resolved binary questions as benchmark cases, Manifold, Polymarket, and Kalshi connectors can attach public market probabilities as baseline comparisons, GDELT/RSS/FRED/IMF DataMapper/Socrata/Stooq/Yahoo Finance/CoinGecko/SEC EDGAR/SEC company facts/arXiv/PubMed/WHO GHO/FEMA/PyPI/npm/GitHub/data adapters can attach timestamped evidence, and Manifold/Kalshi connectors can import resolved binary markets as benchmark cases, but the forecast ledger and update workflow remain platform-neutral.

The standard should be:

- Can the question be made scoreable?
- Can evidence be timestamped and audited?
- Can a probability or distribution be stored and later scored?
- Can the system learn from the resolved outcome?

## Surgical Fork Map

Keep the Hermes pieces that support a local research terminal:

- CLI/TUI as the primary product surface.
- Tool registry and core execution path.
- Terminal, browser, MCP, file, web, delegation, and code-execution tooling.
- Provider adapters, credential pools, model routing, and auxiliary model support.
- Session DB patterns, logging, profiles, setup, config, and plugin discovery.
- The test harness and local-first development posture.

Cut or demote surfaces that do not improve forecasting quality:

- Most gateway/platform integrations.
- General assistant branding and UX.
- Generic skills marketplace as a first-class product.
- Broad "do anything" tool exposure by default.
- Dashboard chat duplication unless it supports forecast review.
- Memory that cannot be tied to evidence, scoring, calibration, or postmortems.

## Closed Feedback Loop

The hardest part is not the UI or tools. It is the learning loop:

```text
forecast -> observe -> resolve -> score -> diagnose -> recalibrate -> forecast better
```

Every implementation choice should serve that loop. A feature that makes research easier but does not affect evidence quality, probability estimation, update discipline, resolution, scoring, or calibration should be treated as optional.

## Backtesting And Self-Checks

Backtesting is a core product capability because it is how the agent proves that it is learning rather than merely producing plausible rationales. Historical evaluation must be time-aware: when replaying a forecast, the agent may only use evidence that was available before the simulated forecast timestamp. Post-resolution articles, later market prices, and retrospective summaries must be excluded unless they are part of the resolution step.

The fork should ship with small smoke-test corpora and larger replay corpora. Synthetic corpora are useful for regression tests, but at least one packaged public resolved-question corpus should preserve source URLs and external baseline probabilities so local benchmark runs do not depend on live APIs.

Backtest replays should also separate "dataset replay" from generated probabilities. A deterministic baseline-ensemble replay mode is useful as a local probability-engine smoke test: it can combine market, crowd, base-rate, and naive components without using an LLM, then report paired performance against every baseline. This still should not be described as proof of superforecasting skill; it is benchmark plumbing for future agent-generated forecasts.

The fork should also expose a named local forecast-engine replay mode. Unlike dataset replay, it should not read the dataset's answer-side probability field. It should generate probabilities from available pre-cutoff priors, baselines, evidence stance metadata, and fixed calibration/extremization rules so the desk has an auditable engine to compare against market, crowd, base-rate, and naive baselines. Strong replay results from this mode are evidence about the benchmark machinery and heuristics, not a guarantee that live agent forecasts beat human superforecasters.

The replay layer should also support an explicit agent-protocol mode. This mode should build a historical forecast prompt from the same pre-cutoff case data, exclude answer-side fields such as dataset probability and resolved outcome, and either call the live forecast agent or replay captured JSON outputs from prior agent runs. It should also be able to export sanitized prompt packets before any model call for one dataset or the built-in benchmark suite, and write the responses used by a run as JSONL so future benchmark runs can replay the same agent outputs. Captured agent-protocol prompts and outputs make benchmark runs deterministic and auditable while preserving the distinction between historical replay evidence and live forecast performance.

The CLI should make that plumbing visible without forcing the operator into a full case dump. A compact performance view should show recent backtest runs, agent mean Brier, the best available baseline, and the agent's Brier edge against that baseline, while keeping live forecasts, backtests, and imported baselines separate. The same performance summary should be exportable as structured JSON so cron jobs, evaluation harnesses, and external reports can consume benchmark results without scraping terminal text. It should also summarize evidence readiness for stronger claims by showing live scored-forecast counts, agent-protocol replay counts, leakage-free runs, generated-source positive baseline-edge runs, distinct dataset coverage, external resolved-question corpus coverage, external source-family diversity, and the remaining gaps before any live superiority claim is justified.

The system should also run scheduled self-checks by domain, topic, forecast horizon, confidence band, large forecast-delta threshold, and stale-evidence risk. These jobs should not silently overwrite forecasts. They should detect new evidence, flag stale assumptions, identify resolved questions, flag large probability moves for review, trigger postmortems, and update calibration memory or domain error profiles after scoring.

Automatic learning writes should be opt-in. A no-agent scheduled review may create scores and postmortem learning records when explicitly configured, but it should still emit alerts for operator review and should never silently change the standing probability on an active forecast.

Watched sources should be treated as alert inputs, not automatic forecast updates. A changed watched file, RSS/Atom feed, GDELT search, FRED series, IMF DataMapper indicator, Census, Socrata, or CKAN open-data query, Stooq/Yahoo Finance market price feed, CoinGecko coin snapshot, SEC filing or company-fact observation, arXiv query, PubMed query, WHO GHO indicator, FEMA disaster declaration query, GitHub repository metadata, commit, or Actions feed, PyPI package release feed, npm package feed, public-attention feed such as Hacker News, Reddit, Bluesky search, or Mastodon hashtag timelines, source adapter feed, or future external monitor should create a review alert tied to a question, domain, topic, or portfolio. The agent can then research the changed source and append an explicit forecast update if the probability should move.

External data ingestion should be generic before it is provider-specific. A CSV/JSON data adapter lets users attach economic indicators, internal datasets, polling rows, company metrics, health indicators, emergency declarations, demographic/regional rows, or custom feeds as timestamped evidence with source metadata. Provider-specific adapters such as FRED, Census, SEC EDGAR filings, SEC company facts/XBRL, arXiv, PubMed, WHO GHO, FEMA, GitHub, PyPI, or npm can build on that shape for common public datasets, but the desk should remain useful when the relevant data is just a file or URL.

Learning memory must be provenance-aware. Live forecasts, historical backtests, and imported baselines should be tracked separately, and only eligible scored forecasts should update calibration memory. Resolutions should be confirmed against their stated criteria before they can affect scores, postmortems, or domain error profiles.

Calibration lessons should have an explicit review state. Newly generated lessons can start tentative, but forecast updates should only cite active, non-invalidated lessons so one bad postmortem does not silently bias future probabilities.

Useful scheduled jobs include:

- Review active forecasts approaching close time.
- Re-run evidence scans for watched domains or topics.
- Detect resolved questions and score them.
- Generate postmortems for newly resolved misses.
- Update calibration lessons by domain, horizon, and question type.
- Alert the user when a forecast needs review or when error patterns change.
- For global self-checks, alert when the benchmark evidence ledger is still
  missing live scored forecasts, agent-protocol held-out cases, leakage-free
  benchmark runs, generated-source positive baseline edges, enough distinct
  datasets, external resolved-question corpus coverage, or enough external
  source-family diversity to justify stronger performance claims.

## Forecasting Protocol

The core agent loop should be reshaped into a forecasting protocol:

1. Parse the question and resolution criteria.
2. Identify the outcome space and ambiguity.
3. Build reference classes.
4. Generate a source plan for official data, leading indicators, market priors,
   RSS/news, and broad textual search.
5. Gather time-stamped evidence.
6. Estimate base rates.
7. Generate inside-view arguments.
8. Run quantitative models where useful.
9. Produce a probability distribution.
10. Store the forecast and rationale.
11. Revisit when new evidence arrives.
12. Score itself after resolution.
13. Update calibration priors and known biases.
14. Schedule future reviews when the forecast is stale, high-impact, or close to resolution.

LLMs should generate hypotheses, decomposition, source summaries, and structured judgment. They should not be the only probability engine by default. The saved probability should come from an explicit ensemble when enough inputs exist:

- Reference-class/base-rate model.
- Bayesian update model.
- Market-implied probability where available.
- Time-series or statistical model when relevant.
- Structured LLM judgment.
- Historical calibration adjustment.

## Persistence Contract

The forecast ledger is the most important new subsystem. Without it, the system cannot learn.

The ledger must preserve:

- The probability or distribution.
- The rationale.
- Evidence references.
- Source snapshots.
- Model versions and parameters.
- Prompt or protocol versions.
- Assumptions.
- Resolution details.
- Scores.
- Postmortems.

Forecast snapshots should be append-only. Editing a past forecast should require an explicit correction record, not mutation.

## CLI Feel

The CLI should feel like a quantitative research terminal.

The default view should show active questions, current probabilities, probability deltas, confidence, close dates, stale forecasts, unresolved assumptions, and new-evidence alerts.
For everyday monitoring, the operator should also have a compact forecast-book
shortcut that lists active questions as numbered rows. The row should carry the
headline probability, delta, freshness/as-of date, close date, confidence,
evidence count, and alert/review state. A row number or direct dashboard/TUI
selection should open the full forecast details so IDs are not part of the
normal browsing workflow. In the TUI, that full-detail view should be a
structured ledger panel rather than a raw text dump: current probability,
rationale, recent evidence, forecast history, assumptions/reference classes,
model runs, resolution state, and concrete follow-up actions should be visible
at once. The TUI should also support forecast lookup by ordinary words, topic,
domain, latest rationale, or latest evidence, and should let the operator add
evidence or append a probability update after resolving a row/search phrase to
the matching ledger question. A ledger browser shortcut should let the operator
jump between book, review, alerts, evidence, learning, schedules, calibration,
backtests, all, and search views.

Example:

```text
ACTIVE FORECASTS

ID     Question                         P(now)  Delta  Close       Status
142    Will X win the election?          0.63   +0.08  2026-11-03  needs update
188    Will company Y default?           0.21   -0.04  2026-09-30  model fresh
203    Will bill Z pass committee?       0.47   +0.12  2026-06-15  new evidence
```

The useful product behavior is not "answer this forecasting question." It is "maintain my book of forecasts and tell me where my beliefs need work."

## Source Breadth And RSS/Text Triage

The desk should not rely on a user manually naming every source. From question
inception it should propose a source plan that covers official resolution
sources, measurable quantitative inputs, market priors when available, and
textual early-warning sources such as RSS/Atom feeds and GDELT searches.

RSS/news is qualitative context, not an automatic probability engine. Feed
items should be filtered, deduplicated, classified as candidate evidence, and
promoted into review alerts only when relevant or material. A watch alert
should point to a filtered `forecast import news ...` command and preserve the
rule that active probabilities only change through explicit forecast updates.
After a forecast has watched text streams, the user or agent should also be
able to search those configured RSS/Atom streams for question-relevant candidate
evidence and optionally capture the matches into the evidence ledger without
moving the current probability.

## First Major Surgery

The first implementation pass should:

1. Rename the product and strip gateway-first surfaces from the default path.
2. Replace assistant-centric prompts with forecasting protocols.
3. Add `forecasting/` domain modules for questions, evidence, models, scoring, and calibration.
4. Replace generic memory as the durable learning surface with a forecast ledger.
5. Add CLI commands for the forecast lifecycle.
6. Build historical backtesting against resolved questions.
7. Make every probability auditable and every miss reviewable.
8. Add scheduled self-checks that turn resolved outcomes and repeated errors into calibration memory.
9. Add source planning plus RSS/textual triage so new questions start with a
   broad, auditable evidence map instead of a manually curated feed list.
