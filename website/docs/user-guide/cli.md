---
sidebar_position: 1
title: "CLI Interface"
description: "Use the Superforecasting Agent command-line forecast desk."
---

# CLI Interface

The main product surface is the command-line forecast desk. Use it to maintain a standing book of scoreable questions, timestamped evidence, probability updates, model runs, scores, postmortems, backtests, and scheduled reviews.

## Entry Points

```bash
forecast                         # Open the forecast desk dashboard
forecast status                  # Operational summary
forecast list                    # Active and recent questions
superforecasting-agent           # Fork-native runtime entrypoint
superforecasting-agent --tui     # Ink TUI with forecast shortcuts
```

Compatibility entrypoints such as `hermes` and `hermes chat` still exist for inherited runtime workflows. They are not the center of the fork.

## Forecast Lifecycle

```bash
forecast new "Will X happen by 2026-12-31?" \
  --resolution-criteria "Resolved yes if ..." \
  --close-time 2026-12-31T00:00:00Z \
  --domain policy \
  --topic legislation

forecast evidence add <id> "New source or note" \
  --available-at 2026-05-21T00:00:00Z \
  --claim-type fact \
  --stance increases

forecast base-rate <id> --name "Comparable cases" \
  --population "Similar historical cases" \
  --sample-size 100 \
  --successes 47

forecast model <id> --type bayesian_update \
  --input-json '{"prior":0.47,"likelihood_ratio":1.3}' \
  --rationale "Evidence is positive but noisy."

forecast update <id> \
  --probability 0.58 \
  --confidence 0.66 \
  --method weighted_ensemble \
  --rationale "Base rate plus new evidence moves the estimate upward."

forecast review --stale
forecast resolve <id> --outcome yes --confirmed --resolution-source <url>
forecast score <id>
forecast postmortem <id> --lesson "What should change next time."
```

Every forecast update is append-only. Corrections are explicit records; past probabilities are not silently overwritten.

## Importing Evidence And Baselines

```bash
forecast sources
forecast sources --json
forecast import data ./rows.csv --question <id>
forecast import gdelt "query terms" --question <id>
forecast import fivethirtyeight president --state PA --question <id>
forecast import fred UNRATE --question <id>
forecast import eia PET.RWTC.M --question <id>
forecast import treasury v2/accounting/od/avg_interest_rates --question <id>
forecast import bls LNS14000000 --question <id>
forecast import worldbank US/NY.GDP.MKTP.CD --question <id>
forecast import census "2023/acs/acs5?get=NAME,B01003_001E&for=state:*" --question <id>
forecast import socrata data.cdc.gov/abcd-1234 --question <id>
forecast import stooq AAPL.US --question <id>
forecast import yahoo AAPL --question <id>
forecast import coingecko bitcoin --question <id>
forecast import sec 0000320193 --question <id>
forecast import secfacts 0000320193/Revenues --question <id>
forecast import arxiv "cat:cs.AI AND forecasting" --question <id>
forecast import openalex "forecasting calibration" --question <id>
forecast import wikipedia "topic" --question <id>
forecast import wikipediapageviews en.wikipedia.org/Topic --question <id>
forecast import github owner/repo --question <id>
forecast import githubissues owner/repo --question <id>
forecast import githubcommits owner/repo --question <id>
forecast import githubactions owner/repo --question <id>
forecast import pypi package-name --question <id>
forecast import npm package-name --question <id>
forecast import hackernews "product query" --question <id>
forecast import reddit "topic query" --question <id>
forecast import federalregister "rule query" --question <id>
forecast import courtlistener "case or legal query" --question <id>
forecast import nvd CVE-2026-0001 --question <id>
forecast import cisakev CVE-2026-0001 --question <id>
forecast import clinicaltrials "NCT01234567" --question <id>
forecast import openfda "BLA125514" --question <id>
forecast import pubmed "forecasting calibration" --question <id>
forecast import openmeteo 38.7,-9.1 --question <id>
forecast import usgs "minmagnitude=5" --question <id>
forecast import eonet "category=wildfires&status=open" --question <id>
forecast import nws "area=CA&event=Flood Warning" --question <id>
forecast import owid grapher-slug --question <id>
forecast import manifold <slug-or-url> --question <id>
forecast import metaculus <id-or-url> --question <id>
forecast import polymarket <slug-or-url> --question <id>
forecast import kalshi <ticker-or-url> --question <id>
```

Run `forecast sources` when you need the current adapter list, import command
shape, or watched-source prefix. Use `--json` for scripts and dashboard helpers.

Market and crowd imports are stored as baselines or evidence. They do not replace the agent's forecast unless you explicitly save a forecast update.

## Review, Learning, And Backtesting

```bash
forecast alerts
forecast calibration --by-origin --all
forecast errors
forecast lessons
forecast backtest --benchmarks
forecast backtest --all-benchmarks --probability-source forecast-engine
forecast backtest path/to/cases.json --probability-source agent-protocol --agent-response-jsonl path/to/agent-responses.jsonl
forecast backtest path/to/cases.json --probability-source agent-protocol --agent-output-jsonl path/to/captured-responses.jsonl
forecast performance --last 5 --json
forecast readiness
forecast readiness --json
forecast readiness --require-evidence
forecast pilot-report
forecast pilot-report --json
forecast pilot-cohort live-cohort.csv --schedule-cadence 1d --schedule-next-run-at 2026-05-25T09:00:00Z
forecast pilot-aggregate tester-a-export.json tester-b-export.json --json
```

Backtests are time-aware. Evidence after the simulated forecast timestamp is excluded unless it is part of the resolution step.
`forecast calibration` reports Brier/log scores, calibration buckets, sharpness,
probability movement before close, and ensemble component contribution so
reviewers can see whether late updates and weighted model inputs are improving
or simply adding churn.
Agent-protocol backtests additionally hide answer-side replay fields from the
agent prompt, can write captured JSONL responses, and can replay captured JSONL
outputs. `forecast performance --json` includes an `evidence_status` section so
automation can see live-score counts, agent-protocol replay counts, leakage-free
runs, positive baseline-edge runs, distinct dataset coverage, and remaining
claim gaps without scraping terminal text. `forecast readiness` exposes the same
claim-readiness state directly for cron jobs and evaluation harnesses, prints
next actions for missing evidence such as live scoring or agent-protocol replay,
and `forecast readiness --require-evidence` exits nonzero when readiness gaps remain.
`forecast pilot-report` is narrower: it checks whether a tester ledger has the
workflow artifacts needed for a small pilot, including questions, updates,
timestamped evidence, structured-source evidence, scheduled self-checks, scores,
and postmortems. `forecast pilot-cohort` seeds prospective live forecast cohorts
from CSV/JSON manifests so testers can start from the same unresolved question
book without copying outcomes into the ledger. `forecast pilot-aggregate` reads JSON exports from testers and
summarizes live-score collection across packets without treating those artifacts
as proof of superiority.

## Scheduled Self-Checks

```bash
forecast watch add --question <id> gdelt:"topic query"
forecast watch add --question <id> openalex:"research query"
forecast watch add --question <id> hackernews:"product query"
forecast watch add --question <id> pypi:package-name
forecast watch add --question <id> npm:package-name
forecast watch add --question <id> reddit:"topic query"
forecast watch add --question <id> federalregister:"rule query"
forecast watch add --question <id> courtlistener:"case or legal query"
forecast watch add --question <id> census:"2023/acs/acs5?get=NAME,B01003_001E&for=state:*"
forecast watch add --question <id> socrata:data.cdc.gov/abcd-1234
forecast watch add --question <id> cisakev:CVE-2026-0001
forecast watch add --question <id> pubmed:"forecasting calibration"
forecast watch add --question <id> owid:grapher-slug
forecast watch add --question <id> yahoo:AAPL
forecast watch add --question <id> coingecko:bitcoin
forecast watch add --question <id> secfacts:0000320193/Revenues
forecast watch add --question <id> usgs:minmagnitude=5
forecast watch add --question <id> eonet:category=wildfires
forecast watch add --question <id> nws:area=CA
forecast watch add --question <id> manifold:<slug>
forecast watch add --question <id> wikipediapageviews:en.wikipedia.org/Topic
forecast watch add --question <id> githubcommits:owner/repo
forecast watch add --question <id> githubactions:owner/repo

forecast schedule add --question <id> --cadence 1d --next-run-at 2026-05-22T09:00:00Z
forecast schedule add --domain policy --topic elections --cadence 12h --stale-days 3 --auto-score --auto-postmortem
forecast schedule add --domain macro --cadence 6h --confidence-below 0.5 --next-run-at 2026-05-22T09:00:00Z
forecast schedule add --domain macro --cadence 6h --large-delta-threshold 0.2 --next-run-at 2026-05-22T09:00:00Z
forecast schedule add --horizon 30 --cadence 1d --next-run-at 2026-05-22T09:00:00Z
forecast schedule list
forecast schedule run --due
forecast self-check --domain macro --confidence-below 0.5
forecast self-check --domain macro --large-delta-threshold 0.2
```

Scheduled jobs and watched sources create review work. They can be scoped by question, domain, topic, portfolio, horizon, confidence band, and large forecast-delta threshold. They should not silently change active probabilities. Automatic scoring and learning writes are opt-in.

## TUI Shortcuts

Launch:

```bash
superforecasting-agent --tui
```

Useful shortcuts:

| Shortcut | Route |
|---|---|
| `/forecast` | Forecast dashboard or raw forecast subcommand |
| `/new-forecast` | Create a scoreable question |
| `/base-rate` | Add or inspect reference-class work |
| `/update-forecast` | Save a probability update |
| `/resolve` | Resolve a question |
| `/score` | Score a resolved question |
| `/postmortem` | Write a post-resolution review |
| `/review` | Review stale or focused forecasts |
| `/alerts` | Inspect forecast alerts |
| `/calibration` | Inspect calibration |
| `/lessons` | Inspect learning records |
| `/backtest` | Run benchmark replay |
| `/schedule` | Inspect scheduled self-checks |
| `/performance` | Summarize recent backtests |
| `/readiness` | Inspect claim-readiness gaps |
| `/pilot-cohort` | Seed prospective live pilot questions |

The TUI status bar also shows forecast desk health such as active forecast count, open alerts, review queue size, calibration sample count, and learned lesson count when available.

## Interactive Runtime Commands

The inherited interactive runtime still supports model switching, tool configuration, sessions, context references, and command autocomplete. Common commands:

| Command | Purpose |
|---|---|
| `/help` | Show command help |
| `/model` | Show or change the current model |
| `/tools` | List available tools |
| `/status` | Show forecast desk/session status |
| `/sessions` | Resume prior sessions |
| `/background <prompt>` | Run a bounded side task |
| `/busy queue` | Queue input while the agent is working |
| `/busy interrupt` | Interrupt the current run with new input |

Use these as support tools for forecasting work. Durable forecast state belongs in the ledger, not in chat memory.

## Background Sessions

The inherited `/background <prompt>` command still runs a bounded side task in a separate session. Use it for support work such as source triage, log inspection, or independent research threads, then write durable conclusions back into the forecast ledger with evidence, model, or update commands.

## Keybindings

| Key | Action |
|---|---|
| `Enter` | Send input |
| `Alt+Enter`, `Ctrl+J`, or supported `Shift+Enter` | Insert a newline |
| `Ctrl+C` | Interrupt the current run; press twice within 2 seconds to force exit |
| `Ctrl+D` | Exit |
| `Tab` | Accept autosuggestion or slash-command completion |
| `Ctrl+G` | Open the input buffer in `$EDITOR` |
| `Ctrl+Z` | Suspend to background on Unix; run `fg` to resume |

## Research Sessions And State

Interactive session transcripts are stored in SQLite for resume and search. Forecast learning state is stored separately in the forecast ledger: questions, evidence, forecast snapshots, baselines, model runs, resolutions, scores, postmortems, corrections, alerts, schedules, and calibration lessons.

New installs default to `~/.superforecasting-agent`. Existing `~/.hermes` homes are reused during the fork transition, and compatibility environment variables such as `HERMES_HOME` still bridge inherited modules.

## Configuration

```bash
superforecasting-agent setup
superforecasting-agent model
superforecasting-agent tools
superforecasting-agent config
```

Config lives in `config.yaml`; secrets live in `.env`. For command examples and settings, see [Configuration](configuration.md).

## Compatibility Notes

- Generic chat is available, but the fork's default workflow is forecast lifecycle management.
- Messaging gateways are inherited and useful for notifications, but not the primary product surface.
- Skills and memory are compatibility features unless they improve evidence quality, modeling, review, or calibration.
- The dashboard embeds the real TUI for chat instead of reimplementing the transcript in React.
