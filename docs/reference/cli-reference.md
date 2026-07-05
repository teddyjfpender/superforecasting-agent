# CLI Reference

<!-- GENERATED FILE - DO NOT EDIT BY HAND. -->
<!-- Source of truth: forecasting/cli.py (register_cli argparse tree) -->
<!-- Regenerate:      python -m scripts.docgen -->
<!-- Staleness gate:  python -m scripts.docgen --check -->

> This page is generated from code. Do not edit it by hand — your change would be overwritten on the next regeneration and the staleness gate would fail. Edit the source instead, then run `python -m scripts.docgen`.

> **Source of truth:** `forecasting/cli.py (register_cli argparse tree)`

The full `forecast` command tree — **84 top-level commands** (also reachable as `superforecasting-agent <command>`). This is the exhaustive reference; for task-oriented walkthroughs see [cli.md](../cli.md).


## Commands


| command | summary |
| --- | --- |
| [`forecast ablation`](#forecast-ablation) | AIA P2.2 — 2x2 search/judge Brier ablation over resolved binary backtest cases (read-only) |
| [`forecast about`](#forecast-about) | Show fork identity and forecast-first scope |
| [`forecast agent`](#forecast-agent) | Run a forecast protocol stage through AIAgent |
| [`forecast alerts`](#forecast-alerts) | List + reconcile forecast alerts |
| [`forecast api-key`](#forecast-api-key) | Manage data-provider API keys (FRED, EIA, Firecrawl, Exa, …). Writes to the user .env and activates immediately. |
| [`forecast assumption`](#forecast-assumption) | Manage durable forecast assumptions |
| [`forecast autopilot`](#forecast-autopilot) | Wire watched sources, schedules, materiality, and update proposals |
| [`forecast backtest`](#forecast-backtest) | Run or inspect time-aware historical replay datasets |
| [`forecast backup`](#forecast-backup) | Back up the forecast ledger (online snapshot + integrity check) and manage retention |
| [`forecast base-rate`](#forecast-base-rate) | Store a reference-class base-rate estimate |
| [`forecast bayes`](#forecast-bayes) | Bayesian scratchpad: LR updates, log-odds pooling, polls→prob, de-vig, sensitivity, forecast-diff |
| [`forecast bench`](#forecast-bench) | Show the read-only ForecastBench backtest scoreboard (agent vs market Brier) |
| [`forecast calibration`](#forecast-calibration) | Show calibration summary (add `status` for the readiness cockpit) |
| [`forecast complementarity`](#forecast-complementarity) | AIA P1.3 — fitted convex market+LLM Brier-minimizing blend + LOO additive value (read-only) |
| [`forecast config`](#forecast-config) | Inspect the layered runtime configuration (typed loader + config doctor). |
| [`forecast correction`](#forecast-correction) | Record non-mutating corrections |
| [`forecast crux`](#forecast-crux) | Manage per-forecast crux variables (the decisive inputs) |
| [`forecast cycle`](#forecast-cycle) | Run the closed-loop forecast cycle |
| [`forecast doctor`](#forecast-doctor) | Run operational, pilot, and readiness checks |
| [`forecast drill`](#forecast-drill) | Practice on already-RESOLVED binary questions and get scored instantly |
| [`forecast errors`](#forecast-errors) | Show domain error profile summary |
| [`forecast evidence`](#forecast-evidence) | Manage evidence items |
| [`forecast evidence-map`](#forecast-evidence-map) | Show the crux evidence map for a forecast |
| [`forecast export`](#forecast-export) | Export an auditable forecast packet |
| [`forecast factor`](#forecast-factor) | Build a weighted basket of constituent return distributions and aggregate it |
| [`forecast freshen`](#forecast-freshen) | Put a forecast on a refresh cadence + ensure the nightly self-check cron (one verb) |
| [`forecast hooks`](#forecast-hooks) | Inspect / tune / author the saturation + style hook rules |
| [`forecast import`](#forecast-import) | Run an optional source adapter without making it the core workflow |
| [`forecast ingest`](#forecast-ingest) | Capture a URL, file, or note as external forecast context |
| [`forecast jobs`](#forecast-jobs) | Administer detached background forecast jobs |
| [`forecast lesson`](#forecast-lesson) | Review and promote calibration lessons |
| [`forecast lessons`](#forecast-lessons) | List calibration lessons |
| [`forecast link`](#forecast-link) | Link related forecasts so they cross-pollinate context |
| [`forecast links`](#forecast-links) | List a forecast's links and related forecasts |
| [`forecast lint`](#forecast-lint) | Saturation report for a forecast: 0-100 score + per-rule verdicts (style + completeness) |
| [`forecast list`](#forecast-list) | List forecast questions |
| [`forecast market-nightly`](#forecast-market-nightly) | AIA P2.1 — foreknowledge-proof live benchmark: sample OPEN markets, forecast NOW, score on close |
| [`forecast market-quality`](#forecast-market-quality) | Stratify market readings by liquidity + recency into an advisory pooling weight, so a thin/stale market can't inflate a tail |
| [`forecast model`](#forecast-model) | Record a probabilistic model run (or `model build <ref>` to build a Market Model as a forecast leg) |
| [`forecast new`](#forecast-new) | Create a scoreable forecast question |
| [`forecast next`](#forecast-next) | Rank the book by value-of-information — what should I touch next? |
| [`forecast onboard`](#forecast-onboard) | Curate a new question as a typed QuestionSpec — propose + validate, then commit the full fan-out |
| [`forecast panel`](#forecast-panel) | Run / aggregate / inspect a multi-perspective forecast panel (outside, inside, market, red-team, sanity) |
| [`forecast performance`](#forecast-performance) | Summarize recent backtest performance against available baselines |
| [`forecast pilot-aggregate`](#forecast-pilot-aggregate) | Aggregate tester export packets into live-evidence collection counts |
| [`forecast pilot-bundle`](#forecast-pilot-bundle) | Emit one JSON tester handoff bundle with pilot, readiness, and optional export data |
| [`forecast pilot-cohort`](#forecast-pilot-cohort) | Seed a prospective live tester cohort from a CSV or JSON manifest |
| [`forecast pilot-report`](#forecast-pilot-report) | Summarize tester-pilot ledger coverage and missing artifacts |
| [`forecast pipeline`](#forecast-pipeline) | Show the guided forecasting loop for a question (which stages are done, what is next) |
| [`forecast plugins`](#forecast-plugins) | List forecast-specific extension points |
| [`forecast postmortem`](#forecast-postmortem) | Create a structured post-resolution diagnosis |
| [`forecast practice`](#forecast-practice) | Record YOUR OWN estimate for a question (scored when it resolves) — Tetlock practice |
| [`forecast protocol`](#forecast-protocol) | Render a forecast-stage agent protocol prompt |
| [`forecast quorum`](#forecast-quorum) | Run a model-diverse forecast quorum (Fusion-style): dispatch a panel of models, then a judge synthesizes a verdict. Subcommands: `quorum <id>` (run), `quorum status [run-id]`, `quorum config [set k v]`, `quorum default on|off`. |
| [`forecast readiness`](#forecast-readiness) | Show live/backtest evidence gaps before stronger performance claims |
| [`forecast reference-class`](#forecast-reference-class) | Manage durable reference classes |
| [`forecast refresh`](#forecast-refresh) | Pull latest watched-source readings + re-estimate, then auto-commit a new live snapshot |
| [`forecast rerun`](#forecast-rerun) | Mass LLM re-run: run the FULL formal forecast flow (fresh research + VOI audit + base rate + gated commit + auto-quorum where indicated) for explicit question ids, DETACHED so a keypress can start many multi-minute sessions. Subcommands: `rerun <id> [<id> ...]` (start), `rerun status <run-id>`. |
| [`forecast research`](#forecast-research) | Capture research evidence without updating probability |
| [`forecast resolve`](#forecast-resolve) | Record a forecast resolution |
| [`forecast resolver`](#forecast-resolver) | Manage trusted resolver policies |
| [`forecast review`](#forecast-review) | Review stale or active forecasts |
| [`forecast run-all`](#forecast-run-all) | Refresh every active member forecast, then aggregate every active thesis |
| [`forecast schedule`](#forecast-schedule) | Manage scheduled self-checks |
| [`forecast score`](#forecast-score) | Score the current forecast snapshot |
| [`forecast scores`](#forecast-scores) | List score records |
| [`forecast search`](#forecast-search) | Search forecast questions without remembering IDs |
| [`forecast self-check`](#forecast-self-check) | Create alerts for review work |
| [`forecast set-decision`](#forecast-set-decision) | Set or revise decision_owner / decision_deadline / action_threshold / update_triggers |
| [`forecast show`](#forecast-show) | Show a forecast question |
| [`forecast slack`](#forecast-slack) | Provision this agent's Slack identity and report who it is |
| [`forecast source`](#forecast-source) |  |
| [`forecast sources`](#forecast-sources) | List forecast evidence source adapters |
| [`forecast status`](#forecast-status) | Show forecast desk operational status |
| [`forecast tail-audit`](#forecast-tail-audit) | Probability-mass audit for a categorical distribution: flag UNEARNED tail mass (material outcomes with no named path — the outcome-space-anchoring failure) |
| [`forecast thesis`](#forecast-thesis) | Group member forecasts under a thesis and aggregate their health |
| [`forecast tournament`](#forecast-tournament) | Import a resolved tournament export as a replay benchmark |
| [`forecast track-record`](#forecast-track-record) | Measured Brier edge of each ensemble component / panel perspective over the committed aggregate, with advisory weights |
| [`forecast triage`](#forecast-triage) | Three-way relevance labeling on candidate readings (keep/skim/skip) before they become evidence |
| [`forecast triggers`](#forecast-triggers) | Evaluate a question's executable update_triggers against imported values |
| [`forecast unlink`](#forecast-unlink) | Remove the link(s) between two forecasts |
| [`forecast update`](#forecast-update) | Append a forecast snapshot |
| [`forecast warnings`](#forecast-warnings) | Resolve the open alert_events backlog through real gated work (never a bare ack) |
| [`forecast watch`](#forecast-watch) | Manage watched sources for self-check alerts |

## `forecast ablation`

| argument | help |
| --- | --- |
| `--json` | Emit the raw report as JSON |

## `forecast about`

## `forecast agent`

| argument | help |
| --- | --- |
| `id` |  |
| `--stage` |  |
| `--dry-run` | Print protocol messages without calling a model |
| `--model` |  |
| `--provider` |  |
| `--max-iterations` |  |

## `forecast alerts`

| argument | help |
| --- | --- |
| `--all` |  |
| `--ack` |  |
| `--reconcile` | Auto-acknowledge alerts whose source-change has already been consumed (evidence imported + forecast updated since) |
| `--dry-run` | With --reconcile, preview without acknowledging |
| `--json` | Emit machine-readable output |

## `forecast api-key`

- **`forecast api-key list`** — List known providers and whether a key is currently set (redacted).
- **`forecast api-key set`** — Persist a key to the user .env and activate it (`forecast api-key set fred <key>`).
- **`forecast api-key show`** — Show one provider's status (redacted).
- **`forecast api-key unset`** — Remove a provider's key from .env and the current process.

### `forecast api-key list`

| argument | help |
| --- | --- |
| `--json` | Emit machine-readable JSON. |

### `forecast api-key set`

| argument | help |
| --- | --- |
| `provider` |  |
| `value` | The key value (or, for kalshi, the access key id). |
| `--from-stdin` | Read the key value from stdin (recommended in shared terminals — keeps the key out of shell history). |
| `--pem-file` | Kalshi only: path to the RSA private key PEM (streaming handshake). The PEM is copied 0600 into the workspace. |
| `--pem-stdin` | Kalshi only: read the PEM body from stdin instead of --pem-file. |

### `forecast api-key show`

| argument | help |
| --- | --- |
| `provider` |  |
| `--json` |  |

### `forecast api-key unset`

| argument | help |
| --- | --- |
| `provider` |  |

## `forecast assumption`

- **`forecast assumption add`** — Add an assumption
- **`forecast assumption list`** — List assumptions
- **`forecast assumption status`** — Update assumption status

### `forecast assumption add`

| argument | help |
| --- | --- |
| `id` |  |
| `text` |  |
| `--status` |  |
| `--check-cadence` |  |
| `--evidence-ref` |  |
| `--notes` |  |

### `forecast assumption list`

| argument | help |
| --- | --- |
| `id` |  |

### `forecast assumption status`

| argument | help |
| --- | --- |
| `assumption_id` |  |
| `--status` |  |
| `--last-checked-at` |  |
| `--invalidated-at` |  |
| `--notes` |  |

## `forecast autopilot`

- **`forecast autopilot approve`** — Approve a pending forecast update proposal
- **`forecast autopilot disable`** — Disable active autopilot policy for a question
- **`forecast autopilot enable`** — Enable autonomous forecast maintenance
- **`forecast autopilot history`** — Show autopilot run history
- **`forecast autopilot proposals`** — List forecast update proposals
- **`forecast autopilot reject`** — Reject a pending forecast update proposal
- **`forecast autopilot run`** — Run autopilot source checks and proposal generation
- **`forecast autopilot status`** — Show autopilot policy state

### `forecast autopilot approve`

| argument | help |
| --- | --- |
| `proposal_id` |  |
| `--reviewed-by` |  |

### `forecast autopilot disable`

| argument | help |
| --- | --- |
| `id` |  |

### `forecast autopilot enable`

| argument | help |
| --- | --- |
| `id` |  |
| `--source` |  |
| `--sources` | Comma-separated watched sources |
| `--required-source` |  |
| `--required-sources` | Comma-separated watched sources that block refresh if unavailable |
| `--cadence` |  |
| `--next-run-at` |  |
| `--mode` |  |
| `--materiality-threshold` |  |
| `--max-auto-delta` |  |
| `--min-sources-for-auto-commit` |  |
| `--notify` |  |
| `--quiet-if-unchanged` |  |
| `--created-by` |  |
| `--allow-missing-resolution-source` |  |

### `forecast autopilot history`

| argument | help |
| --- | --- |
| `id` |  |
| `--limit` |  |

### `forecast autopilot proposals`

| argument | help |
| --- | --- |
| `id` |  |
| `--all` |  |

### `forecast autopilot reject`

| argument | help |
| --- | --- |
| `proposal_id` |  |
| `--reviewed-by` |  |

### `forecast autopilot run`

| argument | help |
| --- | --- |
| `id` |  |
| `--now` |  |
| `--trigger-reason` |  |
| `--proposed-probability` |  |
| `--rationale` |  |

### `forecast autopilot status`

| argument | help |
| --- | --- |
| `id` |  |

## `forecast backtest`

| argument | help |
| --- | --- |
| `dataset` |  |
| `--as-of` |  |
| `--evidence-cutoff-policy` |  |
| `--probability-source` | Choose how replay probabilities are produced: dataset uses stored case probabilities, baseline-ensemble combines explicit baselines, forecast-engine generates a local desk-ensemble probability, agent-protocol runs the forecasting protocol through AIAgent or captured JSONL agent outputs, and naive uses 0.5 for binary cases. |
| `--agent-response-jsonl` | JSONL file of captured agent protocol responses keyed by case_id/id/index; used only with --probability-source agent-protocol. |
| `--agent-output-jsonl` | Write agent protocol responses as JSONL for later deterministic replay; used only with --probability-source agent-protocol. |
| `--agent-prompt-jsonl` | Write sanitized agent protocol prompt packets as JSONL for offline model runs; used with --prepare-agent-prompts and --probability-source agent-protocol. |
| `--prepare-agent-prompts` | Only write --agent-prompt-jsonl packets for the selected dataset and do not run the backtest |
| `--agent-model` | Model used for agent-protocol backtests |
| `--agent-provider` | Provider used for agent-protocol backtests |
| `--agent-max-iterations` |  |
| `--closed-book` | Closed-book agent-protocol replay: disable the live web/search toolset so the agent forecasts from the question text and reasoning only. Use for historical questions whose outcome is googleable. Used only with --probability-source agent-protocol. |
| `--market-hidden` | MARKET-HIDDEN ARM (agent-protocol only): withhold the freeze market baseline from the agent's PROMPT so no market price is shown to it, while the market baseline is STILL scored for the head-to-head + complementarity. Pair with --closed-book for a true intrinsic-only forecast (no tooling to look the price up). ForecastBench datasets only. |
| `--allow-calibration-memory` |  |
| `--benchmarks` | List built-in benchmark datasets |
| `--all-benchmarks` | Run every built-in benchmark dataset with the selected probability source |
| `--list` |  |
| `--show` |  |

## `forecast backup`

- **`forecast backup list`** — List existing ledger backups (newest first)
- **`forecast backup run`** — Create an online backup + integrity check now (runs as a durable job)

### `forecast backup list`

| argument | help |
| --- | --- |
| `--dest-dir` | Override the backup directory (default: <ledger dir>/backups) |
| `--json` | Emit machine-readable JSON |

### `forecast backup run`

| argument | help |
| --- | --- |
| `--dest-dir` | Override the backup directory (default: <ledger dir>/backups) |
| `--keep-recent` | Retention override: newest N backups always kept (default 14) |
| `--weekly-weeks` | Retention override: one-per-week for W weeks (default 8) |
| `--json` | Emit the machine-readable job record |

## `forecast base-rate`

| argument | help |
| --- | --- |
| `id` |  |
| `--name` |  |
| `--inclusion-criteria` |  |
| `--exclusion-criteria` |  |
| `--base-rate` |  |
| `--uncertainty` |  |
| `--source-ref` |  |
| `--check-cadence` |  |
| `--notes` |  |

## `forecast bayes`

| argument | help |
| --- | --- |
| `bayes_action` | Toolkit routine: lr_update, decompose_update, combine, evidence_weight, evidence_cluster, blend_base_rates, poll_to_prob, polls, devig, normalize_market, combine_markets, sensitivity, forecast_diff, conditional_chain (omit to list available actions) |
| `--input/-i` | JSON object payload for the chosen action |
| `--input-file` | Path to a JSON payload file (alternative to --input) |
| `--json` | Emit machine-readable JSON (default prints a human rationale) |

## `forecast bench`

| argument | help |
| --- | --- |
| `--limit` | Cap the number of rows shown |
| `--json` | Emit the machine-readable scoreboard JSON |

## `forecast calibration`

| argument | help |
| --- | --- |
| `mode` | `status` = the readiness cockpit (calibration + live track record + readiness gaps + next actions) |
| `--domain` |  |
| `--origin` |  |
| `--by-origin` | Show combined, live, backtest, and imported-baseline calibration sections |
| `--horizon` | Filter by horizon in days, e.g. 7 or 30-90 |
| `--all` | Include calibration-ineligible scores |
| `--operator` | Show the OPERATOR's own calibration (practice/drill estimates) instead of the system's |
| `--window-days` | Operator view: restrict to estimates scored within the trailing N days |
| `--bias` | Show the SIGNED over/under-confidence view (per scope: SCE, CI, status) instead of the unsigned summary |
| `--since` | Bias view: only count resolutions on/after this ISO date |
| `--recency-halflife` | Bias view: recency half-life (days) |

## `forecast complementarity`

| argument | help |
| --- | --- |
| `--origin` | Which resolved score_records to fit the LLM/agent side from (default: live) |
| `--min-sample` | Minimum resolved market+LLM pairs before a weight is fitted (default: 30) |
| `--json` | Emit the raw report as JSON |

## `forecast config`

- **`forecast config doctor`** — Report unknown/typo vars, defaults in effect, secret presence, file-vs-env conflicts, and the Kalshi two-var trap (read-only).

### `forecast config doctor`

| argument | help |
| --- | --- |
| `--json` | Emit the machine-readable report JSON. |

## `forecast correction`

- **`forecast correction add`** — Add a correction record
- **`forecast correction list`** — List correction records

### `forecast correction add`

| argument | help |
| --- | --- |
| `--target-type` |  |
| `--target-id` |  |
| `--reason` |  |
| `--created-by` |  |
| `--old-json` |  |
| `--new-json` |  |
| `--patch-json` |  |
| `--status` |  |

### `forecast correction list`

| argument | help |
| --- | --- |
| `--target-type` |  |
| `--target-id` |  |
| `--status` |  |

## `forecast crux`

- **`forecast crux add`** — Register a decisive crux variable for a forecast
- **`forecast crux list`** — List a forecast's crux variables
- **`forecast crux status`** — Update a crux's evidence status

### `forecast crux add`

| argument | help |
| --- | --- |
| `question` | row number, id, or search words for the question |
| `--variable` | the decisive variable the resolution hinges on |
| `--role` | preferred source role that would satisfy this crux (repeatable) |
| `--materiality` |  |
| `--status` |  |
| `--notes` |  |

### `forecast crux list`

| argument | help |
| --- | --- |
| `question` |  |

### `forecast crux status`

| argument | help |
| --- | --- |
| `crux_id` |  |
| `status` |  |

## `forecast cycle`

- **`forecast cycle run`** — Run the full due cycle: reviews -> reconcile alerts -> re-aggregate theses -> synthesize lessons

### `forecast cycle run`

| argument | help |
| --- | --- |
| `--due` | Run due reviews (the default) |
| `--now` |  |
| `--no-thesis-aggregate` | Skip re-aggregating theses |
| `--no-reconcile` | Skip alert reconciliation |
| `--no-synthesize-lessons` | Never synthesize lessons this run |
| `--synthesize-lessons` | Force lesson synthesis every run |
| `--agent` | Autonomously re-forecast the questions this sweep flags via the LLM update stage (runs before thesis + lesson phases so they see fresh snapshots) |
| `--model` | --agent: model id for the reforecast agent |
| `--provider` | --agent: provider for the reforecast agent |
| `--max-iterations` | --agent: max agent iterations per question |
| `--max-questions` | --agent: cap how many questions to reforecast in one sweep |
| `--force` | --agent: reforecast even when the pipeline update stage is gated |

## `forecast doctor`

| argument | help |
| --- | --- |
| `--last` | Number of recent backtest runs to inspect |
| `--dataset` | Filter readiness to runs whose dataset contains this text |
| `--min-questions` |  |
| `--min-structured-source-questions` |  |
| `--min-scores` |  |
| `--min-postmortems` |  |
| `--min-scheduled-reviews` |  |
| `--min-scheduled-review-runs` |  |
| `--min-live-scores` | Required resolved live scores for readiness accounting |
| `--min-agent-protocol-cases` | Required scored agent-protocol replay cases for readiness accounting |
| `--min-external-source-families` | Required distinct external resolved-question source families for readiness accounting |
| `--require-pilot-ready` | Exit nonzero if tester pilot artifacts are incomplete |
| `--require-readiness` | Exit nonzero if benchmark/live evidence-readiness gaps remain |
| `--json` | Emit machine-readable doctor JSON |

## `forecast drill`

| argument | help |
| --- | --- |
| `--n` | How many questions to drill (default 5) |
| `--domain` | Restrict to a domain (desk corpus only) |
| `--corpus` | Which corpus to drill. 'desk' replays YOUR resolved questions; 'forecastbench' replays obscure resolved market questions you've never seen (deliberate practice, no recall). Default: auto — forecastbench when its dataset is cached and the desk has too few never-drilled questions, else desk. |
| `--date` | ForecastBench question-set date for --corpus forecastbench (e.g. 2026-06-07, or 'latest' to fetch the newest). Defaults to the newest locally-cached set. |

## `forecast errors`

| argument | help |
| --- | --- |
| `--domain` |  |
| `--topic` |  |
| `--limit` | Maximum active learned-error review rows to print |

## `forecast evidence`

- **`forecast evidence add`** — Add evidence to a forecast question
- **`forecast evidence list`** — List evidence for a forecast question

### `forecast evidence add`

| argument | help |
| --- | --- |
| `id` |  |
| `source_or_note` |  |
| `--source` |  |
| `--claim` |  |
| `--claim-type` |  |
| `--summary` |  |
| `--url/--source-url` |  |
| `--source-name` |  |
| `--source-type` |  |
| `--published-at` |  |
| `--available-at` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--stance` |  |
| `--snapshot-path` |  |
| `--not-admissible-for-backtests` |  |

### `forecast evidence list`

| argument | help |
| --- | --- |
| `id` |  |

## `forecast evidence-map`

| argument | help |
| --- | --- |
| `question` | row number, id, or search words for the question |
| `--json` |  |

## `forecast export`

| argument | help |
| --- | --- |
| `id` |  |
| `--format` |  |
| `--output` |  |

## `forecast factor`

- **`forecast factor add`** — Add a constituent return distribution to a factor (short → inverted)
- **`forecast factor aggregate`** — Aggregate constituents into a fresh factor snapshot
- **`forecast factor create`** — Create a factor question (a thesis with aggregation=factor)
- **`forecast factor list`** — List factor questions
- **`forecast factor remove`** — Remove a constituent from a factor
- **`forecast factor show`** — Show the factor distribution + per-constituent contributions (no commit)

### `forecast factor add`

| argument | help |
| --- | --- |
| `factor` | row number, id, or search words for the factor |
| `constituent` | row number, id, or search words for the constituent forecast |
| `--weight` |  |
| `--direction` |  |

### `forecast factor aggregate`

| argument | help |
| --- | --- |
| `factor` | row number, id, or search words for the factor |
| `--rho` |  |

### `forecast factor create`

| argument | help |
| --- | --- |
| `title` |  |
| `--units` | Return units stored on the outcome space (default: return) |
| `--domain` |  |
| `--topics` | Comma-separated topics |
| `--criteria` | Resolution criteria (>=5 words); a sensible default is used when omitted |
| `--rho` | Default constituent correlation stored in question metadata |

### `forecast factor list`

| argument | help |
| --- | --- |
| `--limit` |  |

### `forecast factor remove`

| argument | help |
| --- | --- |
| `factor` | row number, id, or search words for the factor |
| `constituent` | row number, id, or search words for the constituent forecast |

### `forecast factor show`

| argument | help |
| --- | --- |
| `factor` | row number, id, or search words for the factor |
| `--rho` |  |

## `forecast freshen`

| argument | help |
| --- | --- |
| `id` | Question id (or --all for every active question) |
| `--all` | Freshen every active question |
| `--cadence` | Review cadence (daily/weekly, 'every 2 days', '12h', ...). Default daily. |
| `--json` |  |

## `forecast hooks`

- **`forecast hooks add`** — Validate + save a user rule from a spec file
- **`forecast hooks disable`** — Disable a rule (severity off)
- **`forecast hooks edit`** — Validate + replace an existing user rule from a spec file
- **`forecast hooks enable`** — Enable a rule (revert to the profile's severity)
- **`forecast hooks explain`** — Explain a signal (or list every signal the DSL exposes)
- **`forecast hooks lint`** — Validate the configured user-defined rules (teaching errors)
- **`forecast hooks list`** — Show the active rules + their resolved severity (and why)
- **`forecast hooks methods`** — List the reasoning-method taxonomy the reasoning hook checks
- **`forecast hooks preview`** — Dry-run a candidate rule spec against the current ledger (which forecasts would it block?)
- **`forecast hooks profiles`** — List the curated profiles + their rule severities
- **`forecast hooks remove`** — Remove a user rule by id
- **`forecast hooks set-profile`** — Set the active hook profile
- **`forecast hooks set-severity`** — Set a rule's severity override (off|warn|error)

### `forecast hooks add`

| argument | help |
| --- | --- |
| `--spec` | Path to a YAML/JSON rule spec |

### `forecast hooks disable`

| argument | help |
| --- | --- |
| `rule_id` |  |

### `forecast hooks edit`

| argument | help |
| --- | --- |
| `rule_id` |  |
| `--spec` | Path to a YAML/JSON rule spec |

### `forecast hooks enable`

| argument | help |
| --- | --- |
| `rule_id` |  |

### `forecast hooks explain`

| argument | help |
| --- | --- |
| `signal` | Signal name; omit to list all |

### `forecast hooks lint`

### `forecast hooks list`

| argument | help |
| --- | --- |
| `--question` | Resolve severities for a specific question |
| `--json` |  |

### `forecast hooks methods`

### `forecast hooks preview`

| argument | help |
| --- | --- |
| `--spec` | Path to a YAML/JSON rule spec to preview |
| `--json` |  |

### `forecast hooks profiles`

### `forecast hooks remove`

| argument | help |
| --- | --- |
| `rule_id` |  |

### `forecast hooks set-profile`

| argument | help |
| --- | --- |
| `profile` |  |

### `forecast hooks set-severity`

| argument | help |
| --- | --- |
| `rule_id` |  |
| `severity` |  |

## `forecast import`

- **`forecast import airquality`** — Capture airquality context
- **`forecast import arxiv`** — Capture arxiv context
- **`forecast import benchmark`** — Capture benchmark context
- **`forecast import bls`** — Capture bls context
- **`forecast import bluesky`** — Capture bluesky context
- **`forecast import census`** — Capture census context
- **`forecast import cisakev`** — Capture cisakev context
- **`forecast import ckan`** — Capture ckan context
- **`forecast import clinicaltrials`** — Capture clinicaltrials context
- **`forecast import coingecko`** — Capture coingecko context
- **`forecast import courtlistener`** — Capture courtlistener context
- **`forecast import crossref`** — Capture crossref context
- **`forecast import data`** — Capture data context
- **`forecast import eia`** — Capture eia context
- **`forecast import eonet`** — Capture eonet context
- **`forecast import federalregister`** — Capture federalregister context
- **`forecast import fema`** — Capture fema context
- **`forecast import fivethirtyeight`** — Capture fivethirtyeight context
- **`forecast import fred`** — Capture fred context
- **`forecast import gdelt`** — Capture gdelt context
- **`forecast import github`** — Capture github context
- **`forecast import githubactions`** — Capture githubactions context
- **`forecast import githubcommits`** — Capture githubcommits context
- **`forecast import githubissues`** — Capture githubissues context
- **`forecast import githubrepo`** — Capture githubrepo context
- **`forecast import hackernews`** — Capture hackernews context
- **`forecast import imf`** — Capture imf context
- **`forecast import kalshi`** — Capture kalshi context
- **`forecast import manifold`** — Capture manifold context
- **`forecast import market`** — Capture market context
- **`forecast import mastodon`** — Capture mastodon context
- **`forecast import metaculus`** — Capture metaculus context
- **`forecast import news`** — Capture news context
- **`forecast import npm`** — Capture npm context
- **`forecast import nvd`** — Capture nvd context
- **`forecast import nws`** — Capture nws context
- **`forecast import openalex`** — Capture openalex context
- **`forecast import openfda`** — Capture openfda context
- **`forecast import openmeteo`** — Capture openmeteo context
- **`forecast import owid`** — Capture owid context
- **`forecast import packet`** — Import a JSON forecast export packet
- **`forecast import polymarket`** — Capture polymarket context
- **`forecast import pubmed`** — Capture pubmed context
- **`forecast import pypi`** — Capture pypi context
- **`forecast import reddit`** — Capture reddit context
- **`forecast import reliefweb`** — Capture reliefweb context
- **`forecast import sec`** — Capture sec context
- **`forecast import secfacts`** — Capture secfacts context
- **`forecast import socrata`** — Capture socrata context
- **`forecast import stooq`** — Capture stooq context
- **`forecast import tournament`** — Capture tournament context
- **`forecast import treasury`** — Capture treasury context
- **`forecast import usgs`** — Capture usgs context
- **`forecast import weatherhistory`** — Capture weatherhistory context
- **`forecast import whogho`** — Capture whogho context
- **`forecast import wikipedia`** — Capture wikipedia context
- **`forecast import wikipediapageviews`** — Capture wikipediapageviews context
- **`forecast import worldbank`** — Capture worldbank context
- **`forecast import yahoo`** — Capture yahoo context

### `forecast import airquality`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--forecast-days` |  |
| `--api-base-url` | Override Open-Meteo Air Quality API endpoint for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import arxiv`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override arXiv API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import benchmark`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--name` |  |
| `--description` |  |
| `--limit` |  |
| `--api-base-url` | Override API base URL for benchmark adapters such as manifold:resolved, metaculus:resolved, or kalshi:resolved |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import bls`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--start-year` |  |
| `--end-year` |  |
| `--api-base-url` | Override BLS public API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import bluesky`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--sort` |  |
| `--author` | Filter Bluesky search to an author handle or DID |
| `--lang` | Filter Bluesky search by BCP-47 language code |
| `--link-domain` | Filter Bluesky posts by linked domain |
| `--url-filter` | Filter Bluesky posts by linked URL |
| `--api-base-url` | Override Bluesky public search endpoint for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import census`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override U.S. Census API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import cisakev`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override CISA KEV catalog endpoint for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import ckan`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override CKAN package_search endpoint template for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import clinicaltrials`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override ClinicalTrials.gov studies API endpoint for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import coingecko`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--vs-currency` |  |
| `--api-base-url` | Override CoinGecko markets API endpoint for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import courtlistener`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--search-type` | CourtListener search type, defaulting to opinions |
| `--api-base-url` | Override CourtListener search API endpoint for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import crossref`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override Crossref Works API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import data`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import eia`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override EIA API endpoint or endpoint template for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import eonet`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override NASA EONET events API endpoint for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import federalregister`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override Federal Register API endpoint for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import fema`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--state` | Filter FEMA declarations by two-letter state code |
| `--incident-type` | Filter FEMA declarations by incident type, such as Fire or Hurricane |
| `--declaration-type` | Filter FEMA declarations by declaration type, such as DR or EM |
| `--api-base-url` | Override OpenFEMA Disaster Declarations endpoint for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import fivethirtyeight`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--state` | Filter polls by state or seat name |
| `--candidate` | Filter polls by candidate/answer substring |
| `--pollster` | Filter polls by pollster substring |
| `--cycle` | Filter polls by election cycle |
| `--office-type` | Filter polls by office_type |
| `--api-base-url` | Override FiveThirtyEight polling CSV base URL or endpoint template for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import fred`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override FRED CSV endpoint for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import gdelt`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--timespan` | GDELT timespan such as 24h, 7d, or 1month |
| `--source-country` | Limit to a GDELT sourcecountry query operator |
| `--source-lang` | Limit to a GDELT sourcelang query operator |
| `--api-base-url` | Override GDELT DOC API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import github`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override GitHub API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import githubactions`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override GitHub API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import githubcommits`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override GitHub API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import githubissues`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--state` |  |
| `--api-base-url` | Override GitHub API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import githubrepo`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override GitHub API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import hackernews`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override Hacker News Algolia API endpoint for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import imf`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override IMF DataMapper API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import kalshi`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--api-base-url` | Override Kalshi Trade API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import manifold`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--api-base-url` | Override Manifold API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import market`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import mastodon`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--local` | Request only local statuses from the instance |
| `--only-media` | Request only statuses with media |
| `--api-base-url` | Override Mastodon hashtag timeline endpoint for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import metaculus`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--api-base-url` | Override Metaculus API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import news`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--keyword` | Only import RSS/Atom items containing this term; repeatable or comma-separated |
| `--exclude-keyword` | Skip RSS/Atom items containing this term; repeatable or comma-separated |
| `--no-dedupe` | Disable RSS/Atom item deduplication |
| `--materiality` | Expected materiality label to store with imported news metadata |
| `--direction` | Expected directional impact label to store with imported news metadata |
| `--affected-component` | Forecast assumption or component affected by matching news; repeatable |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import npm`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override npm registry API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import nvd`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override NVD CVE API endpoint for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import nws`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override National Weather Service active alerts API endpoint for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import openalex`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override OpenAlex Works API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import openfda`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override openFDA Drugs@FDA API endpoint for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import openmeteo`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--forecast-days` |  |
| `--api-base-url` | Override Open-Meteo forecast API endpoint for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import owid`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--entity` | Filter Our World in Data grapher rows by Entity |
| `--value-column` | Override the OWID value column to import |
| `--api-base-url` | Override Our World in Data grapher base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import packet`

| argument | help |
| --- | --- |
| `source` | Path to a JSON packet, or '-' for stdin |
| `--conflict` |  |
| `--json` | Print the import summary as JSON |

### `forecast import polymarket`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--api-base-url` | Override Polymarket Gamma API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import pubmed`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override PubMed E-utilities search endpoint for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import pypi`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override PyPI JSON API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import reddit`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override Reddit JSON search endpoint for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import reliefweb`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override ReliefWeb reports API endpoint for tests or private mirrors |
| `--appname` | ReliefWeb API appname; defaults to RELIEFWEB_APPNAME or superforecasting-agent |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import sec`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override SEC submissions API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import secfacts`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--concept` | SEC XBRL concept, e.g. Revenues |
| `--taxonomy` | SEC XBRL taxonomy, defaulting to us-gaap |
| `--unit` | SEC XBRL unit to import, e.g. USD, shares, or pure |
| `--api-base-url` | Override SEC company-facts API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import socrata`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override Socrata API endpoint template for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import stooq`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--interval` |  |
| `--api-base-url` | Override Stooq CSV endpoint for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import tournament`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--name` |  |
| `--description` |  |
| `--limit` |  |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import treasury`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--date-field` |  |
| `--value-field` | Treasury Fiscal Data field to use as the primary value |
| `--api-base-url` | Override Treasury Fiscal Data API base URL or endpoint template for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import usgs`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override USGS earthquake event API endpoint for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import weatherhistory`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--start-date` |  |
| `--end-date` |  |
| `--api-base-url` | Override Open-Meteo Historical Weather API endpoint for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import whogho`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--country` | Filter WHO GHO rows by SpatialDim ISO3 country code |
| `--dimension` | Add a WHO GHO OData dimension filter as KEY=VALUE; can be repeated |
| `--api-base-url` | Override WHO GHO OData API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import wikipedia`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override MediaWiki API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import wikipediapageviews`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--access` | Wikimedia access filter |
| `--agent` | Wikimedia agent filter |
| `--api-base-url` | Override Wikimedia pageviews API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import worldbank`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--api-base-url` | Override World Bank API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

### `forecast import yahoo`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--limit` |  |
| `--since` |  |
| `--claim-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--range` |  |
| `--interval` |  |
| `--api-base-url` | Override Yahoo Finance chart API base URL for tests or private mirrors |
| `--resolution-criteria` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--baseline-probability` |  |
| `--baseline-type` |  |
| `--as-of` |  |

## `forecast ingest`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--title` |  |
| `--resolution-criteria` |  |
| `--resolution-source` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--list` |  |
| `--show` |  |
| `--confirm` |  |
| `--domain` |  |
| `--tag` |  |
| `--topic` |  |
| `--claim` |  |
| `--claim-type` |  |
| `--summary` |  |
| `--available-at` |  |
| `--published-at` |  |
| `--source-name` |  |
| `--source-type` |  |
| `--dry-run` |  |

## `forecast jobs`

- **`forecast jobs approve`** — Approve a parked job awaiting operator sign-off and (by default) resume it

### `forecast jobs approve`

| argument | help |
| --- | --- |
| `job_id` | The parked job id (status awaiting_approval) |
| `--no-resume` | Record the approval grant but do not re-run the job |
| `--json` | Emit the job record as JSON |

## `forecast lesson`

- **`forecast lesson list`** — List calibration lessons
- **`forecast lesson status`** — Update calibration lesson status
- **`forecast lesson synthesize`** — Derive signed over/under-confidence lessons from resolved forecasts (FDR-gated; advisory by default)

### `forecast lesson list`

| argument | help |
| --- | --- |
| `--scope-type` |  |
| `--scope-ref` |  |
| `--active` |  |

### `forecast lesson status`

| argument | help |
| --- | --- |
| `lesson_id` |  |
| `--status` |  |
| `--confidence` |  |
| `--recommended-adjustment-json` |  |
| `--supersedes` |  |

### `forecast lesson synthesize`

| argument | help |
| --- | --- |
| `--scope` | 'all', 'global', 'domain', or a specific domain name |
| `--since` | Only count resolutions on/after this ISO date (regime cutoff) |
| `--recency-halflife` | Exponential recency half-life (days) |
| `--mechanical` | Opt in to bounded numeric logit-scale nudges (OFF by default → advisory text only) |
| `--no-activate` | Leave every synthesized lesson tentative |
| `--dry-run` | Measure and decide without writing any lesson |

## `forecast lessons`

| argument | help |
| --- | --- |
| `--scope-type` |  |
| `--scope-ref` |  |
| `--active` |  |

- **`forecast lessons apply`** — Compile a lesson into an enforceable hook rule (auto-detects the enforcement pattern)
- **`forecast lessons audit`** — Per-lesson coverage: is each learning actually being used? (in-scope / applied / dormant)

### `forecast lessons apply`

| argument | help |
| --- | --- |
| `lesson_id` |  |
| `--severity` | WARN (observe, default) or ERROR (blocks at commit) |

### `forecast lessons audit`

| argument | help |
| --- | --- |
| `--json` |  |

## `forecast link`

- **`forecast link add`** — Link two forecasts (related sibling, or component_of for hierarchy)
- **`forecast link list`** — List a forecast's links and related forecasts
- **`forecast link remove`** — Remove the link(s) between two forecasts

### `forecast link add`

| argument | help |
| --- | --- |
| `from_ref` | row number, id, or search words |
| `to_ref` | row number, id, or search words |
| `--type` |  |
| `--rationale` |  |

### `forecast link list`

| argument | help |
| --- | --- |
| `ref` | row number, id, or search words |

### `forecast link remove`

| argument | help |
| --- | --- |
| `from_ref` |  |
| `to_ref` |  |
| `--type` |  |

## `forecast links`

| argument | help |
| --- | --- |
| `ref` | row number, id, or search words |

## `forecast lint`

| argument | help |
| --- | --- |
| `question_id` | Question id to lint |
| `--all` | Lint every active question and summarize (finish sweep) |
| `--json` | Emit machine-readable output |

## `forecast list`

| argument | help |
| --- | --- |
| `--status` |  |
| `--domain` |  |
| `--limit` |  |

## `forecast market-nightly`

- **`forecast market-nightly report`** — Read-only roll-up: pending/scored counts + paired agent-vs-market edge
- **`forecast market-nightly run`** — LIVE proof: fetch currently-OPEN markets from a source adapter, forecast each NOW with the SEARCH-ENABLED informed agent (web search ON — the legitimate live path, NOT closed-book), and record agent-vs-market. The market-hidden ForecastBench result proved the closed-book LLM has NO intrinsic edge; the only way to beat the market is fresh information, provable ONLY forward (searching a resolved question leaks the answer).
- **`forecast market-nightly sample`** — Sample currently-OPEN markets (close STRICTLY in the future) from a markets JSON file and record pending entries (explicit/opt-in; never hits a live API)
- **`forecast market-nightly score`** — Score any pending entry whose market has since resolved (reuses the ledger scoring machinery)

### `forecast market-nightly report`

| argument | help |
| --- | --- |
| `--json` | Emit the report as JSON |

### `forecast market-nightly run`

| argument | help |
| --- | --- |
| `-n/--count` | Max open markets to sample + forecast (default: 10). |
| `--source` | Open-market source adapter (manifold|metaculus|...). Default: manifold. |
| `--model` | Agent model id (overrides the resolved active model). |
| `--research-arm` | A/B research arm (default: config forecasting.market_nightly.research_arm, itself 'plain'). plain = the plain agent-protocol packet (the existing accrued record); voi = the research-disciplined packet (VOI research plan + adequacy floor); both = forecast EACH sampled market TWICE, once per arm (2x LLM calls) recording two pendings, so the voi-vs-plain lift is paired and attributable in `report`. |
| `--seed` | Deterministic sampling seed (default: 0). |
| `--max-iterations` | Agent tool-calling budget per market. |
| `--parallel` | Bounded concurrency over the per-market agent forecasts (default: 1 = sequential). N>1 forecasts up to N markets at once (each gets its own isolated agent); ledger writes stay serialized. |
| `--json` | Emit the run record as JSON. |

### `forecast market-nightly sample`

| argument | help |
| --- | --- |
| `--markets-json` | Path to a JSON array of market dicts (id, probability/yes_price, close_time/resolution_time, ...). No network is contacted. |
| `--as-of` | Forecast instant (default: now). The invariant is close STRICTLY > as_of. |
| `-n/--count` | Max markets to sample (default: 10) |
| `--seed` | Seed for the deterministic pick (default: 0) |
| `--agent-prob` | Constant agent P(yes) for every sampled market (offline; for piloting the loop without an LLM call). |
| `--agent-prob-field` | Read each market's agent P(yes) from this field in the market dict (offline; no LLM call). |
| `--json` | Emit the run record as JSON |

### `forecast market-nightly score`

| argument | help |
| --- | --- |
| `--now` | Scoring instant (default: now) |
| `--json` | Emit the result as JSON |

## `forecast market-quality`

| argument | help |
| --- | --- |
| `--markets` | JSON array of {source, volume?, updated_at?|age_days?, probability?} objects |
| `--json` |  |

## `forecast model`

| argument | help |
| --- | --- |
| `id` | A forecast question id/name — OR the literal 'build' to build a deterministic Market Model as a forecast leg. |
| `build_question` | With `build`: the question ref (id or free-text quant question) to build a Market Model for. |
| `--depth` | model build: research depth |
| `--analysis-type` | model build: pin a model family (overrides the recommender) |
| `--type` |  |
| `--status` |  |
| `--input-json` |  |
| `--parameters-json` |  |
| `--output-json` |  |
| `--diagnostics-json` |  |
| `--prior` |  |
| `--likelihood-if-true` |  |
| `--likelihood-if-false` |  |
| `--series-json` | JSON array for trend_projection model runs |
| `--target-date` | Projection target date for trend_projection |
| `--target-x` | Projection target x value for trend_projection |
| `--date-field` | Date field name in trend_projection series rows |
| `--value-field` | Value field name in trend_projection series rows |
| `--code-ref` |  |
| `--artifact-path` |  |
| `--model-version` |  |
| `--prompt-version` |  |
| `--data-version` |  |
| `--evidence-cutoff` |  |

## `forecast new`

| argument | help |
| --- | --- |
| `title` |  |
| `--description` |  |
| `--resolution-criteria` |  |
| `--resolution-source` |  |
| `--outcome-type` |  |
| `--choice` |  |
| `--unit` |  |
| `--bound` |  |
| `--close-time` |  |
| `--resolution-time` |  |
| `--tag` |  |
| `--domain` |  |
| `--topic` |  |
| `--owner` |  |
| `--impact` |  |
| `--source-plan` | Print recommended sources after creating the question |
| `--apply-source-plan/--apply-watch` | Add (apply) the top recommended watched sources from the generated source plan |
| `--review-cadence` |  |
| `--next-review-at` |  |
| `--decision-owner` | Who owns the decision this forecast informs (e.g. 'ops lead', 'trading desk') |
| `--decision-deadline` | ISO-8601 timestamp by which the decision must be made |
| `--action-threshold` | Probability/threshold that triggers an action (e.g. 'evacuate if P > 0.05') |
| `--update-trigger` | Repeatable. Each value is either a free-form trigger ('PCE release within 24h') or a JSON object with mechanism/threshold/action keys |

## `forecast next`

| argument | help |
| --- | --- |
| `--limit` | How many actions to print (default: 5) |
| `--json` | Emit the machine-readable ranked actions |

## `forecast onboard`

| argument | help |
| --- | --- |
| `prompt` | Plain-language question to seed a draft spec |
| `--spec` | Path to a QuestionSpec JSON file (from a prior --json proposal, edited) |
| `--commit` | Validate and commit the --spec (refuses on error-severity issues) |
| `--auto` | Accept every recommended default, commit the question, then autonomously chain research -> base_rate -> update through the gated agent — a single vague sentence yields a complete, committed forecast |
| `--criteria` | Resolution criteria for the question (skips the LLM criteria draft under --auto) |
| `--model` | --auto: model the pipeline stages run on |
| `--provider` | --auto: provider the pipeline stages run on |
| `--max-iterations` | --auto: agent tool-calling budget per stage |
| `--force-new` | --auto: commit a NEW question even when a strong near-duplicate exists (default routes the refresh onto the existing question instead of forking a rival) |
| `--json` | Emit the proposed spec + issues + clarifications as JSON |

## `forecast panel`

- **`forecast panel aggregate`** — Aggregate a JSON array of perspective estimates without saving
- **`forecast panel list`** — List panel_runs (optionally scoped to a question)
- **`forecast panel perspectives`** — Print the system+user prompt for each panel perspective
- **`forecast panel record`** — Aggregate panel estimates AND save the panel_run for a question
- **`forecast panel show`** — Render a stored panel_run

### `forecast panel aggregate`

| argument | help |
| --- | --- |
| `--input/-i` | JSON array of estimate objects |
| `--input-file` |  |
| `--method` |  |
| `--trim` | Drop this many highest + lowest estimates before pooling (default 1) |
| `--json` |  |

### `forecast panel list`

| argument | help |
| --- | --- |
| `question_id` |  |
| `--limit` |  |

### `forecast panel perspectives`

| argument | help |
| --- | --- |
| `question_id` |  |
| `--perspective` | Subset of perspectives to print (repeatable). Defaults to all five: outside, inside, market, red_team, sanity. |
| `--json` |  |

### `forecast panel record`

| argument | help |
| --- | --- |
| `question_id` |  |
| `--input/-i` | JSON array of estimate objects |
| `--input-file` |  |
| `--method` |  |
| `--trim` |  |
| `--triggered-by` |  |
| `--snapshot-id` |  |
| `--track-record-weights` | Weight perspectives by their measured Brier edge over the committed aggregate (resolved questions only; advisory weights from `forecast track-record`). Estimates that already carry an explicit weight keep it. |

### `forecast panel show`

| argument | help |
| --- | --- |
| `panel_run_id` |  |
| `--json` |  |

## `forecast performance`

| argument | help |
| --- | --- |
| `--last` | Number of recent backtest runs to show |
| `--dataset` | Filter to runs whose dataset contains this text |
| `--live` | Include resolved live forecast performance against scored imported baselines |
| `--json` | Emit machine-readable performance JSON |

## `forecast pilot-aggregate`

| argument | help |
| --- | --- |
| `exports` | JSON files from `forecast export <id|all>` |
| `--min-live-scores` | Minimum live scored forecasts expected across export packets |
| `--require-live-scores` | Exit nonzero when the aggregated live score floor is not met |
| `--json` | Emit machine-readable aggregate JSON |

## `forecast pilot-bundle`

| argument | help |
| --- | --- |
| `--min-questions` |  |
| `--min-structured-source-questions` |  |
| `--min-scores` |  |
| `--min-postmortems` |  |
| `--min-scheduled-reviews` |  |
| `--min-scheduled-review-runs` |  |
| `--last` | Number of recent backtest runs to inspect |
| `--dataset` | Filter to runs whose dataset contains this text |
| `--min-live-scores` | Required resolved live scores for readiness accounting |
| `--min-agent-protocol-cases` | Required scored agent-protocol replay cases for readiness accounting |
| `--min-external-source-families` | Required distinct external resolved-question source families for readiness accounting |
| `--include-export` | Include `forecast export all --format json` data in the bundle; review for sensitive data first |
| `--output` | Write the JSON bundle to this path instead of stdout |

## `forecast pilot-cohort`

| argument | help |
| --- | --- |
| `manifest` | CSV/JSON file or URL containing unresolved live questions |
| `--default-domain` |  |
| `--default-owner` |  |
| `--default-review-cadence` |  |
| `--initial-probability-column` | Column/key containing the operator's initial live probability; set empty to disable |
| `--watch-source-column` | Column/key containing one or more watched sources separated by comma or semicolon |
| `--schedule-cadence` | Create one scheduled review per seeded question |
| `--schedule-next-run-at` | First run timestamp for --schedule-cadence |
| `--schedule-stale-days` |  |
| `--dry-run` | Validate and show the cohort without writing |
| `--json` | Emit machine-readable cohort JSON |

## `forecast pilot-report`

| argument | help |
| --- | --- |
| `--min-questions` |  |
| `--min-structured-source-questions` |  |
| `--min-scores` |  |
| `--min-postmortems` |  |
| `--min-scheduled-reviews` |  |
| `--min-scheduled-review-runs` |  |
| `--require-complete` | Exit nonzero when pilot exit checks still have gaps |
| `--json` | Emit machine-readable pilot-report JSON |

## `forecast pipeline`

| argument | help |
| --- | --- |
| `id` |  |
| `--stage` | Render this stage's protocol prompt. Advancing to 'update' is refused until research+base_rate have produced ledger artifacts (override with --force). |
| `--force` | Bypass the pipeline sequencing gate (e.g. render the update stage early). |
| `--refresh` | Pull latest watched-source readings + re-estimate + auto-commit, then render the post-refresh status. |
| `--json` |  |

## `forecast plugins`

| argument | help |
| --- | --- |
| `--kind` |  |

## `forecast postmortem`

| argument | help |
| --- | --- |
| `id` |  |
| `--summary` |  |
| `--what-happened` |  |
| `--what-was-expected` |  |
| `--missed-evidence` |  |
| `--overweighted-evidence` |  |
| `--base-rate-error` |  |
| `--inside-view-error` |  |
| `--resolution-error` |  |
| `--lesson` |  |
| `--calibration-adjustment-json` |  |
| `--failure-class` | Dominant failure mode. 'noise' means the miss was within expected error of a calibrated forecast; the others mark reusable lessons for domain error profiles. |

## `forecast practice`

| argument | help |
| --- | --- |
| `question_ref` | Question id or free-text name |
| `--note` | Optional rationale for your number |

## `forecast protocol`

| argument | help |
| --- | --- |
| `id` |  |
| `--stage` |  |
| `--json` |  |

## `forecast quorum`

| argument | help |
| --- | --- |
| `target` | Question id to forecast, or one of: status | config | default. |
| `rest` | Sub-arguments (run-id for status; key value for config set; on/off for default). |
| `--preset` | Panel preset (overrides the configured default). 'wide' is the opt-in ~10-draw variance-reduction panel (AIA P1.4). |
| `--models` | Comma-separated OpenRouter model ids (overrides the preset). |
| `--judge` | Judge model id (overrides the preset default). |
| `--pool` | Pooling method for the panel ('mean' is the convexity baseline; the default stays trimmed_geomean_odds). |
| `--trim` | Drop this many extremes before pooling. |
| `--samples` | Self-fusion sample count (self preset). |
| `--attach-snapshot` | Attach the resulting panel run to an existing snapshot id. |
| `--triggered-by` |  |
| `--supervisor-search` | Activate the live agentic-supervisor fresh-search loop (AIA P1.1): when the judge flags an unresolved crux it runs a real bounded web/news search and re-synthesises once on the fresh evidence. Default OFF (byte-identical baseline); also settable via quorum.supervisor_search. |
| `--scope` | For `quorum default`: which indicated panels get a quorum. |
| `--wait` | Run synchronously and print the result (default: background job + run-id). |
| `--seed` | Bootstrap seed for `quorum bench` (deterministic). |
| `--draws` | Bootstrap resamples per ensemble size for `quorum bench` (default 500). |
| `--delphi` | Add one anonymous Delphi-style revision round (shorthand for --delphi-rounds 1). Default OFF (byte-identical baseline). |
| `--delphi-rounds` | Number of Delphi revision rounds (v1 supports 0 or 1). Overrides quorum.delphi_rounds. |
| `--json` | Emit machine-readable JSON. |

## `forecast readiness`

| argument | help |
| --- | --- |
| `--last` | Number of recent backtest runs to inspect |
| `--dataset` | Filter to runs whose dataset contains this text |
| `--min-live-scores` | Required resolved live scores for readiness accounting |
| `--min-agent-protocol-cases` | Required scored agent-protocol replay cases for readiness accounting |
| `--min-external-source-families` | Required distinct external resolved-question source families for readiness accounting |
| `--require-evidence` | Exit nonzero when readiness requirements still have gaps |
| `--run-safe-benchmarks` | First run the OFFLINE builtin benchmark suite (no network / no paid LLM), then re-evaluate readiness and report the gaps that closed |
| `--probability-source` | Generated probability source for --run-safe-benchmarks (default forecast-engine; 'naive' can't beat baselines so it's excluded, and agent-protocol isn't offline) |
| `--dry-run` | With --run-safe-benchmarks: list the benchmarks that would run, without running them |
| `--json` | Emit machine-readable readiness JSON |

## `forecast reference-class`

- **`forecast reference-class list`** — List reference classes
- **`forecast reference-class status`** — Update reference class status

### `forecast reference-class list`

| argument | help |
| --- | --- |
| `id` |  |

### `forecast reference-class status`

| argument | help |
| --- | --- |
| `reference_class_id` |  |
| `--status` |  |
| `--last-checked-at` |  |
| `--invalidated-at` |  |
| `--check-cadence` |  |
| `--notes` |  |

## `forecast refresh`

| argument | help |
| --- | --- |
| `id` |  |
| `--agent` | Run the full LLM update stage instead of the deterministic re-pool |
| `--no-commit` | Preview the re-estimate without importing evidence or committing a snapshot |
| `--dry-run` | Alias for previewing: fetch + re-estimate but write nothing |
| `--carry-forward` | Skip the re-pool; carry the prior probability forward (flags need for --agent / manual re-reasoning) |
| `--extremize` |  |
| `--correlation` | Pass 'estimate' to correlation-adjust pooling weights when sources overlap |
| `--concurrency` |  |
| `--now` |  |
| `--json` |  |
| `--model` |  |
| `--provider` |  |
| `--max-iterations` |  |

## `forecast rerun`

| argument | help |
| --- | --- |
| `ids` | Question ids to reforecast; or `status <run-id>` to poll a run. |
| `--agent` | Explicit opt-in flag (the mass re-run is always the LLM agent flow); accepted for parity with `cycle run --agent`. |
| `--model` | Model id for the reforecast agent. |
| `--provider` | Provider for the reforecast agent. |
| `--max-iterations` | Max agent iterations per question (default 12). |
| `--wait` | Run synchronously and print the result (default: background job + run-id). |
| `--json` | Emit machine-readable JSON. |

## `forecast research`

| argument | help |
| --- | --- |
| `id` |  |
| `sources` |  |
| `--claim` |  |
| `--claim-type` |  |
| `--summary` |  |
| `--available-at` |  |
| `--published-at` |  |
| `--source-name` |  |
| `--source-type` |  |
| `--reliability` |  |
| `--relevance` |  |
| `--stance` |  |

## `forecast resolve`

| argument | help |
| --- | --- |
| `id` |  |
| `--outcome` |  |
| `--source/--resolution-source` |  |
| `--source-snapshot-ref` |  |
| `--resolver-type` |  |
| `--status` |  |
| `--confirmed` | Alias for --status confirmed |
| `--criteria-satisfied/--no-criteria-satisfied` |  |
| `--confidence` |  |
| `--confirmed-by` |  |
| `--notes` |  |
| `--correction-ref` |  |
| `--trusted-policy` |  |
| `--not-scoreable` |  |
| `--auto-score/--no-auto-score` | Automatically score the current live snapshot on a confirmed, criteria-satisfied resolution (default on; --no-auto-score to defer). |

## `forecast resolver`

- **`forecast resolver list`** — List trusted resolver policies
- **`forecast resolver propose`** — Propose a resolution from the latest ingested source value (no commit)
- **`forecast resolver propose-due`** — Run all resolution rules + raise confirm-me alerts for determinable resolutions (autonomy)
- **`forecast resolver rule`** — Attach a metric-threshold resolution rule (propose from an ingested source metric)
- **`forecast resolver trust`** — Create a trusted resolver policy

### `forecast resolver list`

| argument | help |
| --- | --- |
| `--plugin` |  |
| `--scope-type` |  |
| `--enabled` |  |

### `forecast resolver propose`

| argument | help |
| --- | --- |
| `question` | row number, id, or search words for the question |
| `--json` |  |

### `forecast resolver propose-due`

| argument | help |
| --- | --- |
| `--dry-run` | Preview proposals without raising alerts |

### `forecast resolver rule`

| argument | help |
| --- | --- |
| `question` | row number, id, or search words for the question |
| `--field` | parsed source field to read (e.g. segment_revenue) |
| `--comparator` |  |
| `--threshold` |  |
| `--source-role` |  |

### `forecast resolver trust`

| argument | help |
| --- | --- |
| `--plugin` |  |
| `--plugin-version` |  |
| `--scope-type` |  |
| `--scope-ref` |  |
| `--enabled` |  |
| `--approved-by` |  |
| `--audit-log-ref` |  |

## `forecast review`

| argument | help |
| --- | --- |
| `--stale` |  |
| `--last` |  |
| `--domain` |  |
| `--topic` |  |
| `--horizon` | Filter by forecast horizon in days, e.g. 30 or 30-90 |
| `--confidence-below` |  |
| `--confidence-above` |  |
| `--large-delta-threshold` |  |
| `--now` |  |

## `forecast run-all`

| argument | help |
| --- | --- |
| `--limit` | Cap the number of member forecasts run in phase 1 |
| `--rho` |  |
| `--dry-run` | Print what would run without changing anything |

## `forecast schedule`

- **`forecast schedule add`** — Add a scheduled review
- **`forecast schedule automode-cron`** — Start/stop/status the continuous warning-automode cron (free tier + bounded paid tier)
- **`forecast schedule dedupe`** — Collapse duplicate scheduled reviews (keeps one per scope + cadence + reason)
- **`forecast schedule history`** — Show scheduled self-check run history
- **`forecast schedule install-cron`** — Install a no-agent cron bridge for forecast self-checks
- **`forecast schedule list`** — List scheduled reviews
- **`forecast schedule run`** — Run due scheduled self-checks

### `forecast schedule add`

| argument | help |
| --- | --- |
| `--question` |  |
| `--domain` |  |
| `--topic` |  |
| `--portfolio` |  |
| `--horizon` | Scope scheduled review to forecast horizon in days or range |
| `--cadence` |  |
| `--next-run-at` | First run timestamp; defaults to now so the review is due immediately |
| `--stale-days` |  |
| `--trigger-reason` |  |
| `--auto-score` |  |
| `--auto-postmortem` |  |
| `--confidence-below` |  |
| `--confidence-above` |  |
| `--large-delta-threshold` |  |
| `--disabled` |  |

### `forecast schedule automode-cron`

- **`forecast schedule automode-cron start`** — Install the continuous warning-automode cron job (clean re-arm)
- **`forecast schedule automode-cron status`** — Show the continuous warning-automode cron status
- **`forecast schedule automode-cron stop`** — Remove the continuous warning-automode cron job

#### `forecast schedule automode-cron start`

| argument | help |
| --- | --- |
| `--schedule` |  |
| `--name` |  |
| `--deliver` |  |
| `--profile` |  |
| `--no-agent` | Free-tier-only continuous mode (do NOT wire the paid LLM tier) |
| `--paid-budget` | Per-cycle paid-tier agent-run cap (default 3) |
| `--paid-min-interval-hours` | Minimum hours between paid passes (default 6) |
| `--model` |  |
| `--provider` |  |
| `--max-iterations` |  |

#### `forecast schedule automode-cron status`

| argument | help |
| --- | --- |
| `--name` |  |
| `--json` |  |

#### `forecast schedule automode-cron stop`

| argument | help |
| --- | --- |
| `--name` |  |

### `forecast schedule dedupe`

| argument | help |
| --- | --- |
| `--json` | Emit machine-readable dedupe summary |

### `forecast schedule history`

| argument | help |
| --- | --- |
| `--schedule` |  |
| `--limit` |  |
| `--json` | Emit machine-readable run history JSON |

### `forecast schedule install-cron`

| argument | help |
| --- | --- |
| `--schedule` |  |
| `--name` |  |
| `--deliver` |  |
| `--profile` |  |
| `--auto-score` |  |
| `--no-auto-score` | Do NOT auto-score resolved questions in the nightly sweep |
| `--auto-postmortem` |  |
| `--no-auto-postmortem` | Do NOT auto-write postmortems in the nightly sweep |
| `--thesis-aggregate` | Re-aggregate all theses (+ entity suitabilities) after each member review sweep |
| `--no-thesis-aggregate` | Do NOT re-aggregate theses in the nightly sweep |
| `--synthesize-lessons` | Synthesize calibration lessons after the nightly sweep |
| `--no-synthesize-lessons` | Do NOT synthesize calibration lessons in the nightly sweep |
| `--refresh-market-models` | Re-pull + recompute Market Models linked to open questions in the nightly sweep |
| `--no-refresh-market-models` | Do NOT refresh Market Models in the nightly sweep |

### `forecast schedule list`

### `forecast schedule run`

| argument | help |
| --- | --- |
| `--due` | Run due reviews explicitly; this is the default |
| `--now` |  |
| `--auto-score` |  |
| `--auto-postmortem` |  |

## `forecast score`

| argument | help |
| --- | --- |
| `id` |  |
| `--force` |  |
| `--baselines` | Also score imported market/crowd/baseline comparisons without changing the current forecast |

## `forecast scores`

| argument | help |
| --- | --- |
| `--domain` |  |
| `--origin` |  |
| `--horizon` |  |
| `--bucket` |  |
| `--all` | Include calibration-ineligible scores |
| `--include-invalidated` |  |

## `forecast search`

| argument | help |
| --- | --- |
| `query` |  |
| `--status` | Question status to search; default: active |
| `--domain` |  |
| `--topic` |  |
| `--limit` |  |
| `--json` | Emit machine-readable search results |

## `forecast self-check`

| argument | help |
| --- | --- |
| `--question` |  |
| `--domain` |  |
| `--topic` |  |
| `--portfolio` |  |
| `--horizon` | Filter self-check to forecast horizon in days or range |
| `--stale-days` |  |
| `--now` |  |
| `--auto-score` |  |
| `--auto-postmortem` |  |
| `--confidence-below` |  |
| `--confidence-above` |  |
| `--large-delta-threshold` |  |

## `forecast set-decision`

| argument | help |
| --- | --- |
| `id` |  |
| `--decision-owner` |  |
| `--decision-deadline` |  |
| `--action-threshold` |  |
| `--update-trigger` | Repeatable. Replaces existing triggers with the given set. Pass an empty value with --clear-triggers to remove all. |
| `--clear-triggers` | Remove all existing update triggers |

## `forecast show`

| argument | help |
| --- | --- |
| `id` |  |

## `forecast slack`

- **`forecast slack provision`** — Emit a Slack app manifest (this agent's name baked in) + guided setup steps
- **`forecast slack share`** — Post a question's current forecast as an sfp/1 card into a channel
- **`forecast slack whoami`** — Report this agent's name, instance id, and Slack team

### `forecast slack provision`

| argument | help |
| --- | --- |
| `--format` | Manifest format (default yaml — Slack's paste format) |
| `--name` | Override the agent name for this manifest (defaults to AGENT_NAME) |
| `--description` | Override the app description |
| `--out` | Write the manifest to this file instead of stdout |
| `--quiet` | Emit only the manifest (suppress the guided-setup notes) |

### `forecast slack share`

| argument | help |
| --- | --- |
| `question` | Question id whose CURRENT snapshot to share |
| `--channel` | Slack channel id to post the card into |
| `--thread-ts` | Post the card as a reply in this thread (thread = question/round) |
| `--team-id` | Workspace to post in (defaults to first installed) |
| `--json` | Emit the share result as JSON |

### `forecast slack whoami`

| argument | help |
| --- | --- |
| `--team-id` | Workspace to check (defaults to first installed) |
| `--json` | Emit the identity as JSON |

## `forecast source`

- **`forecast source add`** — Watch a source for a question, domain, topic, or portfolio
- **`forecast source check`** — Check watched sources for changes
- **`forecast source list`** — List watched sources

### `forecast source add`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--domain` |  |
| `--topic` |  |
| `--portfolio` |  |
| `--source-type` |  |
| `--source-name` | Human label for the watched source |
| `--cadence` | Expected check cadence for this watched source |
| `--keyword` | RSS/Atom relevance keyword; repeatable or comma-separated |
| `--exclude-keyword` | RSS/Atom exclusion keyword; repeatable or comma-separated |
| `--materiality` | Expected materiality when matching RSS/Atom items change |
| `--direction` | Expected directional impact for matching RSS/Atom items |
| `--affected-component` | Forecast assumption or component affected by matching RSS/Atom items |
| `--role` | Source role: resolver/consensus/official_primary/leading_indicator/market_price/background_context |
| `--metadata-json` |  |

### `forecast source check`

| argument | help |
| --- | --- |
| `--question` |  |
| `--domain` |  |
| `--topic` |  |
| `--portfolio` |  |
| `--now` |  |

### `forecast source list`

| argument | help |
| --- | --- |
| `--question` |  |
| `--domain` |  |
| `--topic` |  |
| `--portfolio` |  |
| `--all` |  |

## `forecast sources`

| argument | help |
| --- | --- |
| `--question` | Plan sources for a forecast question |
| `--plan` | Show forecast-aware source recommendations |
| `--apply-watch` | Add concrete recommended watched sources |
| `--search-watched` | Search active watched RSS/Atom streams for question-relevant candidate evidence |
| `--query` | Extra source-search terms; defaults to question metadata and watch filters |
| `--since` | Only consider watched RSS/Atom items at or after this timestamp |
| `--capture-candidates` | Promote matching watched-source search results into evidence without updating probability |
| `--limit` | Maximum source-plan rows to show |
| `--json` | Emit machine-readable adapter guidance |

## `forecast status`

| argument | help |
| --- | --- |
| `--json` | Emit machine-readable status JSON |

## `forecast tail-audit`

| argument | help |
| --- | --- |
| `--dist` | Categorical distribution as JSON, e.g. '{"A":0.55,"B":0.35,"C":0.1}' |
| `--outcome-path` | Name the causal path for an outcome (repeatable), e.g. --outcome-path 'A=leads polls'. |
| `--json` |  |

## `forecast thesis`

- **`forecast thesis aggregate`** — Aggregate members into a fresh thesis snapshot
- **`forecast thesis create`** — Create a thesis question (outcome type 'thesis')
- **`forecast thesis dashboard`** — Thesis master list (health / score / Δ / coverage / members) — the dedicated thesis dashboard
- **`forecast thesis entity`** — Manage entity suitability under a thesis
- **`forecast thesis list`** — List thesis questions
- **`forecast thesis members`** — List a thesis's member forecasts
- **`forecast thesis set-correlation`** — Pin a pairwise correlation between two thesis members (members co-move unequally)
- **`forecast thesis set-event`** — Configure the thesis as a JOINT THRESHOLD EVENT — P(#member successes >= K) via copula MC
- **`forecast thesis show`** — Show thesis health + per-member contributions (no commit)
- **`forecast thesis tag`** — Tag a member forecast into a thesis (idempotent upsert)
- **`forecast thesis untag`** — Untag a member from a thesis

### `forecast thesis aggregate`

| argument | help |
| --- | --- |
| `thesis` | row number, id, or search words for the thesis |
| `--rho` |  |

### `forecast thesis create`

| argument | help |
| --- | --- |
| `title` |  |
| `--criteria` | Resolution criteria (>=5 words); a sensible default is used when omitted |
| `--domain` |  |
| `--topics` | Comma-separated topics |
| `--horizon` | Free-text review horizon stored in question metadata |
| `--rho` | Default member correlation stored in question metadata |

### `forecast thesis dashboard`

| argument | help |
| --- | --- |
| `--json` | Emit machine-readable thesis dashboard JSON |

### `forecast thesis entity`

- **`forecast thesis entity add`** — Register an entity under a thesis (no weights yet)
- **`forecast thesis entity list`** — List a thesis's entities + their latest suitability
- **`forecast thesis entity remove`** — Remove an entity from a thesis
- **`forecast thesis entity weight`** — Add/replace one member signal weight on an entity

#### `forecast thesis entity add`

| argument | help |
| --- | --- |
| `thesis` | row number, id, or search words for the thesis |
| `name` | entity name (unique within the thesis) |
| `--kind` |  |
| `--label` |  |
| `--action-threshold` |  |

#### `forecast thesis entity list`

| argument | help |
| --- | --- |
| `thesis` | row number, id, or search words for the thesis |
| `--rho` |  |

#### `forecast thesis entity remove`

| argument | help |
| --- | --- |
| `thesis` | row number, id, or search words for the thesis |
| `name` | entity name |

#### `forecast thesis entity weight`

| argument | help |
| --- | --- |
| `thesis` | row number, id, or search words for the thesis |
| `name` | entity name |
| `member` | row number, id, or search words for the member forecast |
| `--weight` |  |
| `--direction` |  |
| `--target` |  |
| `--lo-is-good` | Lower member values are good for this entity (default: higher is good) |
| `--role` |  |

### `forecast thesis list`

| argument | help |
| --- | --- |
| `--limit` |  |

### `forecast thesis members`

| argument | help |
| --- | --- |
| `thesis` | row number, id, or search words for the thesis |

### `forecast thesis set-correlation`

| argument | help |
| --- | --- |
| `thesis` | row number, id, or search words for the thesis |
| `member_a` | member question id |
| `member_b` | member question id |
| `rho` | pairwise correlation in [0, 0.95] |

### `forecast thesis set-event`

| argument | help |
| --- | --- |
| `thesis` | row number, id, or search words for the thesis |
| `--kind` | count_threshold (needs --threshold), all (=every member), or any (>=1 member) |
| `--threshold` | K for count_threshold: P(at least K member successes) |
| `--clear` | remove the event spec (revert to the mean-index headline) |

### `forecast thesis show`

| argument | help |
| --- | --- |
| `thesis` | row number, id, or search words for the thesis |
| `--rho` |  |
| `--sensitivity` | Add the explainability view: biggest marginal movers, stale members, and how the band depends on the correlation assumption |

### `forecast thesis tag`

| argument | help |
| --- | --- |
| `thesis` | row number, id, or search words for the thesis |
| `member` | row number, id, or search words for the member forecast |
| `--weight` |  |
| `--direction` |  |
| `--role` |  |
| `--target` |  |
| `--lo-is-good` | Lower member values are good for the thesis (default: higher is good) |
| `--rationale` |  |

### `forecast thesis untag`

| argument | help |
| --- | --- |
| `thesis` | row number, id, or search words for the thesis |
| `member` | row number, id, or search words for the member forecast |

## `forecast tournament`

| argument | help |
| --- | --- |
| `source` |  |
| `--name` |  |
| `--description` |  |
| `--limit` |  |

## `forecast track-record`

| argument | help |
| --- | --- |
| `--kind` | Restrict to ensemble components or panel perspectives |
| `--origin` | Which snapshots count toward the record (default: live; 'any' = all origins) |
| `--min-count` | Observations required before a weight is recommended (default 5) |
| `--json` |  |

## `forecast triage`

- **`forecast triage contested`** — Route contested/boundary auto-labels to operator hand-labeling
- **`forecast triage label`** — Auto-label candidate readings (three-way)
- **`forecast triage list-rubrics`** — List stored triage rubrics
- **`forecast triage relabel`** — Record an operator expert label (adjudication) + ack its contested alert
- **`forecast triage set-rubric`** — Store/replace a desk triage rubric for a scope
- **`forecast triage trust`** — Show the held-out trust gate for the auto-labeler

### `forecast triage contested`

| argument | help |
| --- | --- |
| `--question` |  |
| `--label-id` | Specific triage_label id(s) to check |
| `--verifier-json` | Optional second-opinion labels [{candidate_ref|id, label}] to define disagreement |
| `--disagreement-threshold` |  |

### `forecast triage label`

| argument | help |
| --- | --- |
| `--question` |  |
| `--use-watched` | Pull candidates from the question's watched sources (requires --question) |
| `--candidates-json` | JSON array of candidate readings [{title, summary?, source_type?, source?, url?, id?}] |
| `--rubric-ref` | Explicit triage rubric id to apply |
| `--model` | Model id for the cheap auto-labeler (default $FORECAST_TRIAGE_MODEL) |
| `--query` | Optional query when pulling watched candidates |
| `--limit` |  |
| `--no-persist` | Do not persist verdicts as triage_labels staging rows |

### `forecast triage list-rubrics`

| argument | help |
| --- | --- |
| `--scope-type` |  |
| `--scope-ref` |  |
| `--all` | Include inactive rubrics |

### `forecast triage relabel`

| argument | help |
| --- | --- |
| `label_id` |  |
| `label` | relevant_interesting | relevant_uninteresting | irrelevant |
| `--adjudications-json` | JSON array [{label_id, label}] for bulk adjudication |

### `forecast triage set-rubric`

| argument | help |
| --- | --- |
| `--scope-type` |  |
| `--scope-ref` |  |
| `--interesting` | What counts as INTERESTING here (required) |
| `--uninteresting` |  |
| `--irrelevant` |  |
| `--notes` |  |

### `forecast triage trust`

| argument | help |
| --- | --- |
| `--threshold` |  |
| `--min-sample` |  |

## `forecast triggers`

| argument | help |
| --- | --- |
| `id` |  |
| `--observation` | Override an observed value, e.g. --observation fred:CPIAUCSL=3.2 (repeatable). Omitted observations are derived from the question's imported evidence. |
| `--observations-json` | JSON object of source_ref->value. |
| `--now` |  |
| `--json` |  |

## `forecast unlink`

| argument | help |
| --- | --- |
| `from_ref` |  |
| `to_ref` |  |
| `--type` |  |

## `forecast update`

| argument | help |
| --- | --- |
| `id` |  |
| `--probability` |  |
| `--numeric-value` |  |
| `--distribution-json` | JSON object mapping categorical outcomes to probabilities or distribution parameters such as mean/std |
| `--rationale` | Forecast rationale; quotes are optional when it is the last update field |
| `--as-of` |  |
| `--confidence` |  |
| `--method` | Ensemble method recorded with the snapshot. With --component-json and no explicit --probability, 'log_odds_pool' (or 'log_pool') pools components through the Bayesian toolkit (geometric pooling of odds, respects confident minorities); 'weighted_ensemble'/'linear' keeps the weighted average. |
| `--component-json` |  |
| `--extremize` | Extremization factor (>1 sharpens) applied when pooling components via a Bayesian method |
| `--correlation` | Correlation handling for Bayesian pooling: 'estimate' or a JSON NxN matrix; downweights double-counted sources |
| `--assumption` |  |
| `--assumption-ref` |  |
| `--reference-class-ref` |  |
| `--evidence-ref` |  |
| `--stale-evidence-days` |  |
| `--ack-stale-evidence` |  |
| `--stale-evidence-reason` | Why committing on stale evidence is OK (records + clears the stale_evidence_justified WARN). |
| `--require-citations` | Require a live forecast to cite at least one evidence/model/reference-class/source-snapshot/assumption/lesson ref. Opt-in (the soul/protocol nudges citing evidence); pass it when committing an evidence-backed forecast. |
| `--model-run-ref` |  |
| `--origin` | 'live' commits a scored forecast (formalities enforced); 'exploratory' is a scratchpad forecast — free of commit-time formalities and not calibration-scored. |
| `--agent-model` |  |
| `--prompt-version` |  |
| `--protocol-version` |  |
| `--toolset-version` |  |
| `--source-snapshot-ref` |  |
| `--reason-up` | Repeatable. One concrete reason the probability should be higher. |
| `--reason-down` | Repeatable. One concrete reason the probability should be lower. |
| `--change-my-mind` | Repeatable. One observation that would force a material update. |
| `--require-structured-reasoning/--no-require-structured-reasoning` | Refuse to save a live snapshot unless --reason-up, --reason-down, and --change-my-mind are all set. On by default; use --no-require-structured-reasoning (or --origin exploratory) to skip. |
| `--require-decision-readiness` | Refuse to save the snapshot unless the question has decision_owner, action_threshold, and at least one update_trigger |
| `--panel-estimates-json` | JSON array of panel estimates (one per perspective). When supplied, the panel is aggregated to derive the snapshot probability and a panel_run record is attached to the snapshot. |
| `--panel-estimates-file` | Path to a JSON file containing panel estimates |
| `--panel-method` |  |
| `--panel-trim` |  |
| `--panel-triggered-by` |  |
| `--require-panel/--no-require-panel` | For a high-impact live forecast, refuse to save unless a panel run is linked (--panel-run-ref / --panel-estimates-json) or --panel-skipped-reason is given. On by default; lower-impact first forecasts are only nudged. Use --no-require-panel (or --origin exploratory) to skip. |
| `--panel-run-ref` | ID of an already-recorded panel run to link to this snapshot as its deliberative-panel evidence. |
| `--panel-skipped-reason` | Recorded reason for committing a panel-indicated forecast without a panel (escape valve for the panel formality). |
| `--outcome-path` | Categorical forecasts: name the causal path for an outcome, e.g. --outcome-path 'Lasher=leads polls + endorsements'. Repeatable. Feeds the probability-mass audit that flags unearned tail mass. |
| `--require-outcome-paths` | Categorical live forecasts: refuse to commit when a material outcome holds mass with no named path (unearned tail mass). |
| `--evidence-cutoff` |  |
| `--backtest-run-id` |  |
| `--calibration-ineligible` |  |
| `--calibration-weight` |  |
| `--calibration-lesson-ref` |  |
| `--calibration-adjustment-json` |  |
| `--use-active-lessons/--no-use-active-lessons` | Attach active global/domain/topic/question-type calibration lessons and apply the measured probability adjustment. ON by default for LIVE commits only (the pre-adjustment raw_probability is recorded for audit); backtest/imported commits are NOT auto-adjusted (pass --use-active-lessons to opt in). Use --no-use-active-lessons to commit your raw number. Exploratory commits are never adjusted. |
| `--preview` | Show update preview without writing a snapshot |

## `forecast warnings`

- **`forecast warnings automode`** — Drain the backlog by priority: classify + dispatch each, then reconcile at the end
- **`forecast warnings list`** — Group the open warnings by reason (counts + priority order + recommended action); read-only
- **`forecast warnings resolve`** — Resolve ONE alert (or every open alert for a question) via the gated dispatcher

### `forecast warnings automode`

| argument | help |
| --- | --- |
| `--dry-run` | Print the plan WITHOUT writing |
| `--limit` | Cap how many alerts to process this pass |
| `--reason` | Filter to reasons containing this text |
| `--scope` | Filter to a single question id / scope ref |
| `--tier` | Per-tier bulk pass: 'free' = the non-LLM kinds {bookkeeping,score,postmortem,material_change}; 'reforecast' = the opt-in LLM reforecast/evidence tier (pair with --agent) |
| `--kinds` | Restrict to these ResolutionKinds (e.g. --kinds score postmortem); UNIONed with --tier when both are given |
| `--agent` | Enable the autonomous LLM reforecast runner for REFORECAST alerts (otherwise they stay OPEN) |
| `--model` | --agent: model id for the reforecast agent |
| `--provider` | --agent: provider for the reforecast agent |
| `--max-iterations` | --agent: max agent iterations per question |
| `--max-questions` | --agent: cap how many questions to reforecast in one sweep |
| `--force` | --agent: reforecast even when the pipeline update stage is gated |
| `--no-reconcile` | Skip the end-of-run reconcile_alerts pass |
| `--now` |  |
| `--json` | Emit machine-readable JSON |

### `forecast warnings list`

| argument | help |
| --- | --- |
| `--reason` | Filter to reasons containing this text |
| `--scope` | Filter to a single question id / scope ref |
| `--limit` | Cap the number of reason groups shown |
| `--json` | Emit machine-readable JSON |

### `forecast warnings resolve`

| argument | help |
| --- | --- |
| `target` | Alert id (al_*) or question/scope ref (fq_*) |
| `--agent` | Enable the autonomous LLM reforecast runner for REFORECAST alerts (otherwise they stay OPEN) |
| `--model` | --agent: model id for the reforecast agent |
| `--provider` | --agent: provider for the reforecast agent |
| `--max-iterations` | --agent: max agent iterations per question |
| `--force` | --agent: reforecast even when the pipeline update stage is gated |
| `--now` |  |
| `--json` | Emit machine-readable JSON |

## `forecast watch`

- **`forecast watch add`** — Watch a source for a question, domain, topic, or portfolio
- **`forecast watch check`** — Check watched sources for changes
- **`forecast watch list`** — List watched sources

### `forecast watch add`

| argument | help |
| --- | --- |
| `source` |  |
| `--question` |  |
| `--domain` |  |
| `--topic` |  |
| `--portfolio` |  |
| `--source-type` |  |
| `--source-name` | Human label for the watched source |
| `--cadence` | Expected check cadence for this watched source |
| `--keyword` | RSS/Atom relevance keyword; repeatable or comma-separated |
| `--exclude-keyword` | RSS/Atom exclusion keyword; repeatable or comma-separated |
| `--materiality` | Expected materiality when matching RSS/Atom items change |
| `--direction` | Expected directional impact for matching RSS/Atom items |
| `--affected-component` | Forecast assumption or component affected by matching RSS/Atom items |
| `--role` | Source role: resolver/consensus/official_primary/leading_indicator/market_price/background_context |
| `--metadata-json` |  |

### `forecast watch check`

| argument | help |
| --- | --- |
| `--question` |  |
| `--domain` |  |
| `--topic` |  |
| `--portfolio` |  |
| `--now` |  |

### `forecast watch list`

| argument | help |
| --- | --- |
| `--question` |  |
| `--domain` |  |
| `--topic` |  |
| `--portfolio` |  |
| `--all` |  |
