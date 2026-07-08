# Forecast Hooks (Built-in Rules)

<!-- GENERATED FILE - DO NOT EDIT BY HAND. -->
<!-- Source of truth: forecasting/hooks/builtins.py (BUILTIN_RULES, RULE_DOCS) -->
<!-- Regenerate:      python -m scripts.docgen -->
<!-- Staleness gate:  python -m scripts.docgen --check -->

> This page is generated from code. Do not edit it by hand — your change would be overwritten on the next regeneration and the staleness gate would fail. Edit the source instead, then run `python -m scripts.docgen`.

> **Source of truth:** `forecasting/hooks/builtins.py (BUILTIN_RULES, RULE_DOCS)`

Before a forecast snapshot commits, the hook engine runs these checks. Each rule resolves to a severity — `error` **blocks** the commit, `warn` surfaces without blocking, `off` is disabled — via the active profile and any per-rule override. `weight` is the penalty points a failed rule adds to the saturation score. There are **35 built-in rules**; operators can add their own with the hooks DSL.


Severities shown are the **defaults** — the shipped profile or an operator override can raise or lower any of them (`forecast hooks list` shows the resolved severity).

## calibration

| rule | default severity | weight | what it checks |
| --- | --- | --- | --- |
| `lessons_applied` | `warn` | 6.0 | Active calibration lessons should be applied to the commit. |
| `terminal_calibration_applied` | `warn` | 6.0 | A linked panel run must pass through the terminal Platt calibration stage. |

## confidence

| rule | default severity | weight | what it checks |
| --- | --- | --- | --- |
| `calibration_bias_applied` | `warn` | 6.0 | When measured under-confident, apply the calibration lesson. |
| `confidence_committed` | `warn` | 6.0 | Avoid near-maximum hedging unless genuine uncertainty is justified. |
| `granularity_disciplined` | `warn` | 4.0 | WARN when a binary commit sits on a round-number anchor (a 0.10 multiple / quarter-point) no pooled component produced (Tetlock's granularity finding); never blocks. |
| `tails_justified` | `warn` | 10.0 | No-path tails must be justified; do not over-weight unearned outcomes. |

## decision

| rule | default severity | weight | what it checks |
| --- | --- | --- | --- |
| `no_watched_sources` | `warn` | 8.0 | A live forecast must have at least one active watched source the desk can refresh. |
| `readiness_floor` | `warn` | 10.0 | A live forecast's machine-readiness (Desk RDY) score must clear the floor so the autonomous desk has the inputs to keep it alive. |
| `require_decision_readiness` | `warn` | 6.0 | The decision card should have no missing fields. |
| `update_cadence_honored` | `warn` | 8.0 | SWEEP-SIDE: a live forecast past its review cadence (x the grace multiple) with no recorded stale_evidence_reason fails on lint/finish_sweep (badge + alert, never a commit block). |

## output

| rule | default severity | weight | what it checks |
| --- | --- | --- | --- |
| `candidate_intervals_coherent` | `error` (blocks) | 12.0 | Per-candidate vote-share intervals, when present, must be coherent (finite p05<=median<=p95, median near the committed share, in bounds). |
| `candidate_intervals_present` | `warn` | 10.0 | A high-impact vote-share forecast must carry per-candidate intervals (auto-computed from the ensemble spread; record no_interval_reason to opt out). |
| `output_renderable` | `error` (blocks) | 12.0 | A distribution needs a central tendency + an ordered interval the charts can draw. |
| `uncertainty_well_formed` | `error` (blocks) | 12.0 | Intervals must be ordered, nested, finite, non-degenerate, in-bounds. |
| `uncertainty_width_sane` | `warn` | 6.0 | Intervals must not be implausibly wide vs the question range. |

## quorum

| rule | default severity | weight | what it checks |
| --- | --- | --- | --- |
| `market_anchor_engaged` | `warn` | 10.0 | A commit on a market-linked question must record the market price + deviation (via a quorum run or metadata.market_comparison) — engagement, never agreement. |
| `quorum_judged` | `warn` | 6.0 | A model quorum must carry a judge synthesis (consensus + contradictions). |
| `quorum_participation` | `warn` | 8.0 | A panel/quorum that runs needs enough distinct perspectives. |
| `quorum_required` | `warn` | 10.0 | Serious forecasts (high-impact / re-commit) need an actual panel or quorum run. |

## reasoning

| rule | default severity | weight | what it checks |
| --- | --- | --- | --- |
| `crux_named` | `warn` | 8.0 | A high-impact commit must carry >=1 registered crux (question_cruxes) OR record crux_skip_reason naming why no single crux exists. |
| `outside_view_refresh` | `warn` | 6.0 | A routine re-forecast of a question that has never carried a reference class WARNs (pure inside view since birth) — visibility, not a block. |
| `reasoning_composition` | `warn` | 8.0 | Declare a sufficient set + count of reasoning methods. |
| `require_outside_view_anchor` | `warn` | 9.0 | A serious live forecast (high-impact OR the FIRST commit of any question) must carry an outside-view anchor (reference class / base rate). |
| `require_tail_base_rates` | `warn` | 14.0 | Every named, non-residual outcome above the anchor-share threshold (categorical OR vote-share) must carry a cited base rate — else the mass belongs in the residual bucket. |

## saturation

| rule | default severity | weight | what it checks |
| --- | --- | --- | --- |
| `require_citations` | `warn` | 8.0 | The forecast should cite evidence / model runs. |
| `require_components` | `error` (blocks) | 15.0 | The forecast must decompose into pooled ensemble components. |
| `require_evidence` | `error` (blocks) | 16.0 | A live forecast MUST carry at least one evidence record (hard requirement). |
| `require_fresh_evidence` | `error` (blocks) | 15.0 | Evidence must be freshly collected for this commit (no stale re-run). |
| `require_outcome_paths` | `warn` | 10.0 | Every material categorical / vote-share outcome needs a named path (no unearned tails). |
| `require_panel` | `error` (blocks) | 12.0 | A deliberation panel must run (or record an explicit skip reason). |
| `require_structured_reasoning` | `error` (blocks) | 15.0 | Reasons up / down / change-my-mind must all be present. |
| `research_adequate` | `warn` | 10.0 | Research must cover the levers that would move the forecast (reference class, evidence floor, independent + disconfirming + fresh evidence, watched triggers). |
| `stale_evidence_justified` | `warn` | 6.0 | If you acknowledge stale evidence to skip the freshness gate, record a reason. |
| `thesis_aggregate_fresh` | `warn` | 8.0 | A thesis/factor must re-aggregate after its members move (no stale health). |

## style

| rule | default severity | weight | what it checks |
| --- | --- | --- | --- |
| `style_clean` | `error` (blocks) | 5.0 | Prose must be house-clean (no em-dashes / formatting issues). |

Inspect and tune from the CLI: `forecast hooks list` (resolved severities), `forecast hooks profiles`, `forecast hooks explain <signal>`, `forecast hooks set-severity <rule> off|warn|error`, and `forecast hooks add <spec.json>` to author a custom rule. See [forecasting-methodology.md](../forecasting-methodology.md) for how the gate fits the desk workflow.
