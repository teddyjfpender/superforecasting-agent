# Forecast Tool Actions

<!-- GENERATED FILE - DO NOT EDIT BY HAND. -->
<!-- Source of truth: tools/forecasting_tool.py (FORECAST_LEDGER_SCHEMA) -->
<!-- Regenerate:      python -m scripts.docgen -->
<!-- Staleness gate:  python -m scripts.docgen --check -->

> This page is generated from code. Do not edit it by hand — your change would be overwritten on the next regeneration and the staleness gate would fail. Edit the source instead, then run `python -m scripts.docgen`.

> **Source of truth:** `tools/forecasting_tool.py (FORECAST_LEDGER_SCHEMA)`

The agent operates the forecast desk through a single tool, **`forecast_ledger`**. Its `action` parameter selects one of **114 operations**; the remaining parameters form a shared bag (each operation reads the subset it needs). The only globally-required parameter is `action`; per-action requirements are enforced in the handler.


## Actions


Operate on the forecast ledger: create questions, add evidence, append forecast snapshots, resolve, score, review, self-check, and render forecast protocol context. Search actions can locate questions by title, topic, rationale, and evidence without requiring IDs. Forecast snapshots are append-only; source actions can plan and search watched RSS/Atom evidence candidates without moving probabilities; autopilot actions maintain watched-source update proposals through the ledger. The action='bayes' family runs an auditable Bayesian scratchpad (likelihood-ratio updates, log-odds pooling of disagreeing sources, evidence weighting that discounts correlated/biased signals, reference-class base-rate blending, poll→probability conversion, market de-vigging, sensitivity/tornado analysis, and forecast-diff decomposition) so probability moves are transparent rather than ad hoc.

| action |
| --- |
| `acknowledge_alert` |
| `add_assumption` |
| `add_baseline_comparison` |
| `add_evidence` |
| `add_reference_class` |
| `add_watched_source` |
| `add_watched_sources` |
| `aggregate_panel` |
| `approve_forecast_update_proposal` |
| `autopilot_readiness` |
| `autopilot_status` |
| `backfill_market_ids` |
| `backtest_performance_report` |
| `bayes` |
| `build_model` |
| `calibration_summary` |
| `check_update_triggers` |
| `check_watched_sources` |
| `commit_spec` |
| `component_track_record` |
| `configure` |
| `create_correction` |
| `create_question` |
| `create_trusted_resolver_policy` |
| `detect_templated_batches` |
| `disable_autopilot` |
| `doctor_report` |
| `enable_autopilot` |
| `evidence_readiness` |
| `export_all` |
| `export_question` |
| `forecast_complementarity` |
| `full_forecast` |
| `import_packet` |
| `import_source_evidence` |
| `import_source_evidence_batch` |
| `keep_fresh` |
| `label_score` |
| `link_forecasts` |
| `list_alerts` |
| `list_assumptions` |
| `list_autopilot_policies` |
| `list_autopilot_runs` |
| `list_backtest_runs` |
| `list_baseline_comparisons` |
| `list_calibration_lessons` |
| `list_corrections` |
| `list_domain_error_profiles` |
| `list_forecast_update_proposals` |
| `list_label_rubrics` |
| `list_links` |
| `list_model_runs` |
| `list_panel` |
| `list_postmortems` |
| `list_questions` |
| `list_reference_classes` |
| `list_resolution_proposals` |
| `list_scheduled_reviews` |
| `list_scores` |
| `list_trusted_resolver_policies` |
| `list_watched_sources` |
| `market_quality` |
| `market_query` |
| `operator_calibration` |
| `panel_perspectives` |
| `pilot_report` |
| `pipeline` |
| `pm_query` |
| `postmortem` |
| `propose_resolution` |
| `propose_resolutions` |
| `propose_spec` |
| `protocol` |
| `record_model_run` |
| `record_operator_estimate` |
| `record_panel` |
| `refresh_forecast` |
| `reject_forecast_update_proposal` |
| `relabel_route` |
| `rename_question` |
| `research_audit` |
| `research_plan` |
| `resolve` |
| `resolve_warning` |
| `review` |
| `run_autopilot` |
| `run_backtest_dataset` |
| `run_scheduled_reviews` |
| `run_warning_automode` |
| `schedule_review` |
| `score` |
| `search_questions` |
| `self_check` |
| `set_decision` |
| `set_label_rubric` |
| `set_resolution_rule` |
| `share_forecast` |
| `show_panel` |
| `show_question` |
| `show_quorum_status` |
| `source_plan` |
| `source_search` |
| `start_quorum` |
| `tail_audit` |
| `thesis_dashboard` |
| `triage_contested` |
| `triage_label` |
| `triage_trust` |
| `unlink_forecasts` |
| `update_assumption` |
| `update_calibration_lesson` |
| `update_forecast` |
| `update_reference_class` |
| `workflow_report` |

## Sub-mode selectors


Several actions branch on a secondary enum parameter (e.g. `bayes` picks a routine via `bayes_action`):

- **`pm_mode`** — the `pm_query` action's read mode: `search`, `event`, `book`, `history`
- **`stage`** — the `pipeline`/`protocol` forecast stage: `parse`, `research`, `base_rate`, `model`, `update`, `resolve`, `postmortem`, `self_check`
- **`source_type`** — the evidence-source adapter for `import_source_evidence`: `file`, `url`, `manual`, `manual_note`, `rss`, `gdelt`, `fivethirtyeight`, `github`, `githubrepo`, `githubissues`, `githubcommits`, `githubactions`, `coingecko`, `pypi`, `npm`, `hackernews`, `reddit`, `bluesky`, `mastodon`, `reliefweb`, `federalregister`, `courtlistener`, `nvd`, `cisakev`, `openmeteo`, `airquality`, `weatherhistory`, `usgs`, `eonet`, `nws`, `clinicaltrials`, `openfda`, `pubmed`, `owid`, `whogho`, `fema`, `fred`, `eia`, `treasury`, `bls`, `worldbank`, `imf`, `census`, `socrata`, `ckan`, `stooq`, `yahoo`, `sec`, `secfacts`, `secsearch`, `arxiv`, `openalex`, `crossref`, `wikipedia`, `wikipediapageviews`, `manifold`, `metaculus`, `polymarket`, `kalshi`

## Parameters


Every parameter the tool accepts, sorted by name. Descriptions are often prefixed with the action they apply to.

| parameter | type | allowed values | description |
| --- | --- | --- | --- |
| `accept_defaults` | boolean |  | propose_spec/commit_spec: auto-apply the recommended default of every gap/error clarification and commit in one shot (for a vague/casual ask). Only error-severity issues still surface and block; the applied choices come back as `applied_defaults` to echo in a one-line summary. |
| `access` | string |  |  |
| `ack_stale_evidence` | boolean |  |  |
| `acknowledged_at` | string |  |  |
| `action` | string | 114 values (see source) |  |
| `action_threshold` | string |  | Probability/threshold that triggers an action (e.g. 'evacuate if P > 0.05'). |
| `active_only` | boolean |  |  |
| `actor` | string |  | Who is making the change (recorded in audit trails, e.g. rename_question). |
| `adjudications` | array<object> |  | relabel_route: operator expert labels [{label_id, label}] for contested items. |
| `admissible_for_backtests` | boolean |  |  |
| `affected_components` | array<string> |  |  |
| `agent` | string |  |  |
| `agent_model` | string |  |  |
| `alert_id` | string |  |  |
| `allow_calibration_memory` | boolean |  |  |
| `allow_duplicate` | boolean |  | full_forecast: by default a strong near-duplicate routes the stage chain onto the EXISTING question (routed_to_existing=true) instead of forking a rival. Set true to force a NEW question anyway (the duplicate warning is surfaced either way). |
| `allow_missing_resolution_source` | boolean |  |  |
| `analysis_type` | string |  | build_model: preferred model family (overrides the recommender). |
| `api_base_url` | string |  |  |
| `apply_watch` | boolean |  |  |
| `appname` | string |  |  |
| `approved_by` | string |  |  |
| `artifact_paths` | array<string> |  |  |
| `as_of` | string |  |  |
| `assumption_id` | string |  |  |
| `assumption_refs` | array<string> |  |  |
| `audit_log_ref` | string |  |  |
| `author` | string |  |  |
| `auto_postmortem` | boolean |  |  |
| `auto_score` | boolean |  |  |
| `auto_watch` | boolean |  | For import_source_evidence: after a successful import, also attach the (source_type, source) tuple as a watched source on the question so future reruns start from the known identifier instead of broad search. Deduped — a no-op if an identical watch already exists. |
| `available_at` | string |  |  |
| `backtest_case_id` | string |  |  |
| `backtest_run_id` | string |  |  |
| `base_rate` | number |  |  |
| `base_rate_error` | string |  |  |
| `baseline_type` | string |  |  |
| `bayes_action` | string |  | For action='bayes': which Bayesian toolkit routine to run — lr_update, decompose_update, combine, evidence_weight, evidence_cluster, blend_base_rates, poll_to_prob, polls, devig, normalize_market, combine_markets, sensitivity, forecast_diff. |
| `bayes_payload` | object |  | For action='bayes': the inputs for the chosen bayes_action (e.g. {prior_p, lrs} for lr_update; {components, method, extremize, correlation_matrix} for combine; {previous, current, components} for forecast_diff). sensitivity requires {components:[{name, probability, weight?}], parameter_ranges:{component_name:[low, high]}}. |
| `bounds` | array<number> |  |  |
| `bucket` | string |  |  |
| `cadence` | string |  |  |
| `calibration_adjustment` | object |  |  |
| `calibration_eligible` | boolean |  |  |
| `calibration_lesson_refs` | array<string> |  |  |
| `calibration_weight` | number |  |  |
| `candidate` | string |  |  |
| `candidates` | array<object> |  | triage_label: candidate readings to classify as [{title, summary?, source_type?, source?, url?, id?}, ...] (pre-ingest, before they become evidence). |
| `capture_candidates` | boolean |  |  |
| `cases` | array<object> |  |  |
| `change_my_mind` | array<string> |  | Specific observations that would force a material update. |
| `channel` | string |  | For share_forecast: the Slack channel id to post the forecast card into. |
| `check_cadence` | string |  |  |
| `choices` | array<string> |  |  |
| `claim` | string |  |  |
| `claim_type` | string | `fact`, `estimate`, `rumor`, `opinion`, `assumption` |  |
| `close_time` | string |  |  |
| `code_ref` | string |  |  |
| `commit` | boolean |  | refresh_forecast: write the re-estimate as a new live snapshot (default true). |
| `comparator` | string | `>=`, `>`, `<=`, `<`, `==`, `!=` | For set_resolution_rule: how the observed value is compared to threshold. |
| `components` | object |  | update_forecast: the structured ensemble you pooled, as {"components":[{name, probability, weight, source}]}. PERSIST THIS on any snapshot that combines sources — do not leave the pool in prose or a model_run. Give each market/crowd component a stable `source` slug (e.g. 'polymarket:<slug>') so `forecast refresh` can match and re-pool it next run. |
| `concept` | string |  |  |
| `concurrency` | integer |  | import_source_evidence_batch: max parallel fetch workers (default 4, capped at 8). |
| `confidence` | number |  |  |
| `confidence_above` | number |  |  |
| `confidence_below` | number |  |  |
| `confirmed_by` | string |  |  |
| `conflict` | string | `error`, `skip`, `replace` |  |
| `context` | string |  |  |
| `correction_ref` | string |  |  |
| `correlation` | string |  | refresh_forecast: pass 'estimate' to correlation-adjust pooling weights when sources overlap. |
| `cost` | number |  | label_score: optional total inference cost for the scored batch; reported as cost_per_task. |
| `created_by` | string |  |  |
| `criteria_satisfied` | boolean |  |  |
| `cycle` | integer |  |  |
| `data_version` | string |  |  |
| `dataset` | string |  |  |
| `date_field` | string |  |  |
| `db` | string |  |  |
| `decision_deadline` | string |  | ISO-8601 timestamp by which the decision must be made. |
| `decision_owner` | string |  | Who owns the decision this forecast informs (e.g. 'ops lead'). |
| `declaration_type` | string |  |  |
| `dedupe` | boolean |  | For import_source_evidence / import_source_evidence_batch: skip a reading already imported for this question (same source_type + adapter entry_id), so repeated refreshes don't pile up duplicate observations. Default true; the response reports skipped_duplicates. Free-form notes (no entry_id) are never deduped. |
| `default_forecast_time_cutoff` | string |  |  |
| `delphi_rounds` | integer | `0`, `1` | start_quorum: 0 (default) runs the standard sealed quorum; 1 adds one anonymous Delphi revision round. |
| `depth` | string |  | build_model: research depth (quick|standard|deep|ultra). |
| `description` | string |  |  |
| `diagnostics` | object |  |  |
| `direction` | string | `upward`, `downward`, `ambiguous` |  |
| `disagreement_threshold` | number |  | triage_contested: relevance band around 0.5 within which an auto-label is treated as boundary/uncertain and flagged for review (default 0.15; used only when no verifier_labels). |
| `distribution` | object |  | For the `tail_audit` action: the categorical distribution to audit as {outcome_label: probability}. (For update_forecast, pass the distribution via probability_or_distribution instead.) The audit also returns a NULL-MODEL comparison: your no-path tail vs a deliberately simple model that floors any outcome without a named path — if yours is much fatter, justify it or compress. |
| `domain` | string |  |  |
| `dry_run` | boolean |  | refresh_forecast: preview the re-estimate without importing evidence or committing a snapshot. |
| `enabled` | boolean |  |  |
| `end_date` | string |  |  |
| `end_year` | integer |  |  |
| `entity` | string |  |  |
| `estimates` | array<object> |  | Per-perspective panel estimates. |
| `event_id` | string |  | pm_query mode='event': the venue event id (Polymarket Gamma event id or Kalshi event ticker). |
| `evidence_cutoff` | string |  |  |
| `evidence_cutoff_policy` | string |  |  |
| `evidence_refs` | array<string> |  |  |
| `exclude_keywords` | array<string> |  |  |
| `exclusion_criteria` | string |  |  |
| `extremize` | number |  | refresh_forecast: extremization factor applied during the deterministic re-pool (default 1.0). |
| `failure_class` | string | `aggregation`, `base_rate`, `definition`, `inside_view`, `motivated_reasoning`, `noise`, `other`, `tail`, `timing` | Dominant failure mode assigned in a postmortem. |
| `field` | string |  | For set_resolution_rule: the parsed source value to read (e.g. 'yoy_percent'). |
| `force` | boolean |  | For action='pipeline' with a stage: bypass the sequencing gate that refuses advancing to 'update' before research+base_rate produced refs. |
| `forecast_days` | integer |  |  |
| `forecast_id` | string |  |  |
| `forecast_origin` | string | `live`, `exploratory`, `backtest`, `imported_baseline` | 'live' commits a scored forecast with commit-time formalities enforced; 'exploratory' is a scratchpad forecast — exempt from those formalities and never calibration-scored. |
| `forecasting_protocol_version` | string |  |  |
| `format` | string | `json`, `markdown` |  |
| `forms` | string |  | For source_type=secsearch: comma-separated SEC form types to restrict the EDGAR full-text search (e.g. '8-K,10-Q'). |
| `from_question_id` | string |  | For link/unlink: the source forecast id. |
| `gold` | array<object> |  | label_score: gold labels as [{id, label}, ...] (the expert/ground-truth labels). |
| `guardrail_policy` | object |  |  |
| `hooks` | object |  | For action='configure': per-forecast saturation-hook settings. {profile?: standard|strict|exploratory-lenient|superforecaster, overrides?: {<gate_id>: off|warn|error}, thresholds?: {min_perspectives|min_reasoning_methods|max_width_ratio|min_sharpness|null_excess_tolerance: <number>}}. lesson:* gates are NOT settable here (they stay non-demotable). A LOOSER override is allowed but flagged in resolve_question_config. |
| `horizon` | string |  |  |
| `impact` | string |  |  |
| `incident_type` | string |  |  |
| `include_assumptions` | boolean |  | show_question: include the assumptions array (default true). |
| `include_baselines` | boolean |  | show_question: include the baseline_comparisons array (default true). |
| `include_evidence` | boolean |  | show_question: include the evidence array (default true). |
| `include_history` | boolean |  | show_question: include the forecast_history array (default true). |
| `include_inactive` | boolean |  |  |
| `include_invalidated` | boolean |  |  |
| `include_model_runs` | boolean |  | show_question: include the model_runs array (default true). |
| `include_postmortems` | boolean |  | show_question: include the postmortems array (default true). |
| `include_reference_classes` | boolean |  | show_question: include the reference_classes array (default true). |
| `include_reviewed` | boolean |  |  |
| `include_scores` | boolean |  | show_question: include the scores array (default true). |
| `inclusion_criteria` | string |  |  |
| `inputs` | object |  |  |
| `inside_view_error` | string |  |  |
| `invalidated_at` | string |  |  |
| `judge` | string |  | start_quorum: provider/model id for the judge synthesis pass. |
| `key_assumptions` | array<string> |  |  |
| `keywords` | array<string> |  |  |
| `kinds` | array<string> |  | run_warning_automode: restrict to these ResolutionKinds (e.g. ['score','postmortem']); UNIONed with tier when both are given. |
| `label` | string |  | relabel_route: the operator's expert three-way label (relevant_interesting|relevant_uninteresting|irrelevant). |
| `label_id` | string |  | relabel_route: single triage_label id to adjudicate (with `label`). |
| `label_ids` | array<string> |  | triage_contested: specific triage_label row ids to check (else all auto-labeled, un-adjudicated rows for question_id). |
| `lang` | string |  |  |
| `large_delta_threshold` | number |  |  |
| `last` | integer |  |  |
| `last_checked_at` | string |  |  |
| `last_days` | integer |  |  |
| `last_evidence` | integer |  | show_question: cap evidence to the most recent N items. |
| `last_history` | integer |  | show_question: cap forecast_history to the most recent N snapshots. |
| `last_model_runs` | integer |  | show_question: cap model_runs to the most recent N items. |
| `lesson` | string |  |  |
| `lesson_id` | string |  |  |
| `lesson_status` | string | `tentative`, `active`, `superseded`, `rejected` |  |
| `limit` | integer |  |  |
| `limit_timeline` | integer |  | workflow_report: cap the chronological events list to the most recent N (default 25). |
| `link_domain` | string |  |  |
| `link_type` | string | `component_of`, `related` | related (symmetric sibling) or component_of (from=child, to=parent). |
| `local` | boolean |  |  |
| `market_id` | string |  | pm_query mode='book'|'history': the outcome-market id (Polymarket clobTokenId or Kalshi market ticker). |
| `market_model_id` | string |  | Link a model_run (or build_model result) to a Market Model. |
| `market_series` | array<object> |  | market_query: explicit series refs to read, each {provider, symbol, name?, category?, unit?, line?} (e.g. {'provider':'frankfurter','symbol':'EUR'} or {'provider':'bea','symbol':'T20305','line':'1'}). |
| `markets` | array<object> |  | For the `market_quality` action: market readings to stratify by liquidity + recency, each {source, volume?, updated_at? (ISO) or age_days?, probability?}. Returns an advisory pooling weight in [0,1] per market so a thin/stale price can't inflate a tail — multiply it into the component weight, never drop silently. |
| `materiality` | string | `low`, `medium`, `high` |  |
| `materiality_policy` | object |  |  |
| `max_auto_delta` | number |  |  |
| `max_iterations` | integer |  | full_forecast: agent tool-calling budget per chained stage (default 12). |
| `metadata` | object |  |  |
| `method` | string |  |  |
| `min_agent_protocol_cases` | integer |  |  |
| `min_cluster` | integer |  | detect_templated_batches: min forecasts sharing a template to flag a cluster (default 3). |
| `min_external_source_families` | integer |  |  |
| `min_live_scores` | integer |  |  |
| `min_postmortems` | integer |  |  |
| `min_questions` | integer |  |  |
| `min_sample` | integer |  | triage_trust: minimum adjudicated labels before the labeler can be trusted to auto-filter (default 20 / $FORECAST_TRIAGE_TRUST_MIN_SAMPLE). |
| `min_scheduled_review_runs` | integer |  |  |
| `min_scheduled_reviews` | integer |  |  |
| `min_scores` | integer |  |  |
| `min_source_changes` | integer |  |  |
| `min_sources_for_auto_commit` | integer |  |  |
| `min_structured_source_questions` | integer |  |  |
| `missed_evidence` | string |  |  |
| `mode` | string | `propose`, `auto-commit`, `auto_commit`, `alert-only`, `alert_only` |  |
| `model` | string |  | triage_label: model id for the cheap auto-labeler (default $FORECAST_TRIAGE_MODEL or the house judge model). research_audit: optional model for the advisory change_my_mind-coverage check (omit for deterministic-only). |
| `model_run_refs` | array<string> |  |  |
| `model_status` | string | `success`, `failure` |  |
| `model_type` | string |  |  |
| `model_version` | string |  |  |
| `models` | array<string> |  | start_quorum: explicit provider/model panelist ids (overrides the preset). |
| `name` | string |  |  |
| `new_value` | any |  |  |
| `next_review_at` | string |  |  |
| `next_run_at` | string |  | First run timestamp for schedule_review or enable_autopilot; defaults to now when omitted. |
| `note` | string |  | record_operator_estimate: an optional rationale for the operator's number. |
| `notes` | string |  |  |
| `notification_policy` | object |  |  |
| `notify` | string |  |  |
| `now` | string |  |  |
| `observations` | object |  | For action='check_update_triggers': map of source_ref -> latest numeric value to evaluate executable update_triggers against. Omitted values are derived from the question's imported evidence. |
| `office_type` | string |  |  |
| `old_value` | any |  |  |
| `only_media` | boolean |  |  |
| `outcome` | string |  |  |
| `outcome_paths` | object |  | CATEGORICAL forecasts: a {outcome_label: path-info} map naming the causal PATH that routes mass to each material outcome. path-info is a string (the path) or an object {path, classification, evidence_strength: strong|mixed|weak, base_rate, base_rate_source}. Used by the probability-mass audit (also the `tail_audit` action) to flag UNEARNED tail mass and uncited named outcomes — material outcomes with no named mechanism or no cited outside-view anchor. Stored on the snapshot for re-lint. |
| `outcome_type` | string | `binary`, `categorical`, `numeric`, `distribution` |  |
| `output` | object |  |  |
| `overweighted_evidence` | string |  |  |
| `owner` | string |  |  |
| `packet` | object |  |  |
| `panel_run_id` | string |  |  |
| `panel_run_ref` | string |  | ID of a panel run to link to this snapshot as the deliberative-panel evidence for the forecast (satisfies the high-impact panel formality). |
| `panel_skipped_reason` | string |  | Recorded reason for committing a panel-indicated forecast without a panel (the escape valve for the panel formality). Stored on the snapshot. |
| `parameters` | object |  |  |
| `params` | object |  | build_model: Market Model build params (depth, analysis_type, tickers, horizon, target_year, assumptions). |
| `patch` | object |  |  |
| `payload` | object |  | record_model_run: the market_compute payload for a deterministic family (ols/loglinear/timeseries_trend/montecarlo/correlation/arima/...) — e.g. {"x":[...],"y":[...]} for ols, {"values":[...],"horizon":6} for timeseries_trend. Its summary + block are merged into the model_run output via the single market_compute engine. |
| `persist` | boolean |  | triage_label: persist the verdicts as triage_labels staging rows (label_source='auto'). Default true. |
| `perspectives` | array<string> |  | Panel perspectives to use, e.g. outside, inside, market, red_team, sanity. |
| `plugin_version` | string |  |  |
| `pm_mode` | string | `search`, `event`, `book`, `history` | pm_query: which read to run. 'search' → list live events + de-vigged distributions across Polymarket+Kalshi (market priors); 'event' → one event's full outcome distribution (categorical buckets, de-vigged to sum to ~1); 'book' → an outcome market's YES order book (bid/ask depth as a liquidity signal); 'history' → the price-probability time series. |
| `policy_id` | string |  |  |
| `pollster` | string |  |  |
| `pool_method` | string | `log_odds_pool`, `mean`, `median`, `trimmed_geomean_odds` | start_quorum: panel aggregation method (default trimmed_geomean_odds). |
| `portfolio` | string |  |  |
| `positive_class` | string |  | label_score: optional class to treat as positive for a binary confusion matrix + positive-class F1 (e.g. 'relevant_interesting'). |
| `predictions` | array<object> |  | label_score: predicted labels as [{id, label}, ...] (the auto-labeler's output). |
| `preset` | string | `frontier`, `budget`, `self`, `wide` | start_quorum: model panel preset. |
| `preview` | boolean |  | update_forecast: PREVIEW FIRST. Run every gate and saturation scoring WITHOUT writing a snapshot — the result carries the saturation score, its advisories, and any blockers a commit would raise. See them, FIX them (add the panel / components / structured reasoning / clean the style), THEN commit ONCE with preview omitted. Never commit-then-remediate: do not save a snapshot just to read its advisories and immediately re-save a cleaned one. A preview starts NO quorum, writes NO brief, and pins the snapshot count. Returns {preview:true, would_commit, saturation, blockers}. |
| `probability` | number |  |  |
| `probability_or_distribution` | any |  |  |
| `prompt` | string |  | propose_spec/full_forecast: the user's plain-language question. full_forecast turns this one sentence into a committed forecast — it structures + commits the question (accept-defaults) then autonomously chains research -> base_rate -> update through the gated pipeline. |
| `prompt_version` | string |  |  |
| `proposal_id` | string |  |  |
| `proposal_status` | string | `pending`, `approved`, `rejected`, `expired`, `auto_committed` |  |
| `proposed_probability` | number |  |  |
| `proposed_probability_or_distribution` | any |  |  |
| `protocol_version` | string |  |  |
| `provider` | string |  | full_forecast: provider the chained pipeline stages run on (default: house model). |
| `providers` | array<string> |  | market_query shorthand: one provider applies to all `symbols`, else zipped. |
| `published_at` | string |  |  |
| `query` | string |  |  |
| `question` | string |  | build_model: the quant question text (defaults to the linked question's title/description when question_id is given). |
| `question_id` | string |  |  |
| `question_title` | string |  |  |
| `quiet_if_unchanged` | boolean |  |  |
| `range` | string |  | pm_query mode='history': lookback window (e.g. '1d', '1w', '1m'). Default '1w'. |
| `range_value` | string |  |  |
| `rationale` | string |  |  |
| `re_estimate` | string | `deterministic`, `carry_forward` | refresh_forecast: 'deterministic' re-pools the prior components after refreshing market/crowd readings; 'carry_forward' keeps the prior probability and flags that agent re-reasoning is needed. |
| `reason` | string |  |  |
| `reasoning_methods` | array<string> |  | The named reasoning methods you actually used, from the taxonomy (outside_view, inside_view, base_rate, bayesian, decomposition, causality, analogy, comparative, fermi, conditional, trend_extrapolation, mean_reversion, extremizing, systems, game_theory, dialectics, calibration, disconfirmation, pre_mortem, steelmanning, deductive, inductive, abductive, reductive, question_framing). Serious forecasts compose several. The reasoning-composition hook checks these against the active profile. |
| `reasons_down` | array<string> |  | Concrete reasons the probability should be LOWER. |
| `reasons_up` | array<string> |  | Concrete reasons the probability should be HIGHER. |
| `ref` | string |  | resolve_warning: an al_* alert id (resolve that one) or a scope/question ref (resolve every open alert for it). |
| `reference_class` | object |  | Inline outside-view anchor: create + link a reference class to THIS forecast in one call (alternative to a separate add_reference_class). Reuses an existing same-name class on the question if present. |
| `reference_class_id` | string |  |  |
| `reference_class_refs` | array<string> |  |  |
| `relevance_rating` | number |  |  |
| `reliability_rating` | number |  |  |
| `require_citations` | boolean |  |  |
| `require_components` | boolean |  | Refuse to save a live snapshot unless ensemble_components is populated (the pooled drivers — base rate, mechanism, market/crowd, case-specific — each with a stable source slug). Defaults true; stops a serious forecast collapsing into a bare number. Set false or use forecast_origin='exploratory' for scratch work. |
| `require_decision_readiness` | boolean |  | Refuse to save the snapshot unless the question has decision_owner, action_threshold, and at least one update_trigger. |
| `require_outcome_paths` | boolean |  | Categorical live forecasts: refuse to save when any material outcome holds mass with no named path (unearned tail mass). Provide outcome_paths, compress the mass, set false, or record as exploratory. Default false. For named outcomes above the anchor-share threshold, include base_rate + base_rate_source. |
| `require_panel` | boolean |  | For a high-impact live forecast, refuse to save unless a deliberative panel/quorum run is linked (panel_run_ref) or panel_skipped_reason is recorded. Defaults true; lower-impact first forecasts are nudged (panel_recommended), not blocked. Run a panel/quorum for serious forecasts regardless — see the process discipline. |
| `require_structured_reasoning` | boolean |  | Refuse to save the snapshot unless reasons_up, reasons_down, and change_my_mind are all populated. Defaults true for live forecasts. |
| `required_source` | string |  |  |
| `required_sources` | array<string> |  |  |
| `resolution_criteria` | string |  |  |
| `resolution_error` | string |  |  |
| `resolution_source` | string |  |  |
| `resolution_source_snapshot_ref` | string |  |  |
| `resolution_status` | string | `proposed`, `confirmed`, `disputed`, `corrected` |  |
| `resolution_time` | string |  |  |
| `resolver` | string |  | For set_resolution_rule: the resolver engine (default 'metric_threshold'). |
| `resolver_notes` | string |  |  |
| `resolver_plugin` | string |  |  |
| `resolver_type` | string | `manual`, `source_adapter`, `scheduled_check` |  |
| `review_cadence` | string |  |  |
| `reviewed_by` | string |  |  |
| `rubric` | object |  | set_label_rubric: the desk taste {interesting_criteria (required), uninteresting_criteria?, irrelevant_criteria?, examples?:[{title,label,why}], notes?}. |
| `rubric_ref` | string |  | triage_label: explicit triage rubric id to apply (else the most-specific active rubric for the question, else the default macro-desk rubric). |
| `run_id` | string |  |  |
| `run_safe_benchmarks` | boolean |  | evidence_readiness: first run the OFFLINE builtin benchmark suite (no network / no paid LLM) to advance readiness, then evaluate. |
| `sample_size` | integer |  | n observations behind the base rate (how strong the outside view is). |
| `scope` | string |  | run_warning_automode: restrict the sweep to a single question/scope ref. |
| `scope_ref` | string |  |  |
| `scope_type` | string | `question`, `domain`, `topic`, `domain_topic`, `portfolio`, `horizon`, `source`, `question_type`, `global` |  |
| `score_record_id` | string |  |  |
| `scoreable` | boolean |  |  |
| `search_type` | string |  |  |
| `series` | array |  |  |
| `series_ticker` | string |  | pm_query mode='history' on Kalshi: the parent series ticker (required by Kalshi's candlesticks endpoint). |
| `since` | string |  |  |
| `snapshot_id` | string |  |  |
| `snapshot_path` | string |  |  |
| `sort` | string | `latest`, `top` |  |
| `source` | string |  |  |
| `source_country` | string |  |  |
| `source_lang` | string |  |  |
| `source_name` | string |  |  |
| `source_or_note` | string |  | add_evidence: REQUIRED source URL or a durable note identifying the evidence. For a raw web page use action='ingest' or add_evidence with this field; do not send source_type='url' to import_source_evidence. |
| `source_refs` | array<string> |  |  |
| `source_role` | string |  | For set_resolution_rule: which watched-source role supplies the value (default 'resolver'). |
| `source_snapshot_refs` | array<string> |  |  |
| `source_type` | string | 59 values (see source) | Action-dependent source kind. import_source_evidence accepts structured adapters such as fred, polymarket, kalshi, rss, and SEC—not raw 'url'. For a raw URL use action='ingest'. add_watched_source may use url, file, or manual. |
| `source_url` | string |  |  |
| `sources` | array<string> |  |  |
| `spec` | object |  | propose_spec/commit_spec/full_forecast: an explicit QuestionSpec draft (overrides `prompt` when both are given). |
| `stage` | string | `parse`, `research`, `base_rate`, `model`, `update`, `resolve`, `postmortem`, `self_check` |  |
| `stale` | boolean |  |  |
| `stale_days` | integer |  |  |
| `stale_evidence_days` | integer |  |  |
| `stale_evidence_reason` | string |  | If ack_stale_evidence is set, WHY nothing material changed since the prior forecast. Recorded + clears the stale_evidence_justified WARN; otherwise the bypass is flagged. |
| `stance` | string | `supports`, `opposes`, `mixed`, `context` |  |
| `start_date` | string |  |  |
| `start_year` | integer |  |  |
| `state` | string |  |  |
| `status` | string |  |  |
| `summary` | string |  |  |
| `supervisor_search` | boolean |  | start_quorum: opt into the live fresh-search supervisor loop (fails closed for historical cutoffs). |
| `symbols` | array<string> |  | market_query shorthand: symbols paired with `provider`/`providers`. |
| `tag` | string |  | pm_query mode='search': optional Polymarket tag/category filter. |
| `tags` | array<string> |  |  |
| `target_date` | string |  |  |
| `target_id` | string |  |  |
| `target_type` | string | `forecast_snapshot`, `evidence_item`, `assumption`, `reference_class`, `resolution`, `score_record`, `postmortem`, `calibration_lesson` |  |
| `target_x` | number |  |  |
| `task_type` | string | `relevance`, `truncation` | label_score: 'relevance' (multi-class classification, headline=accuracy) or 'truncation' (cut-point extraction, headline=exact-match). |
| `taxonomy` | string |  |  |
| `team_id` | string |  | For share_forecast: the Slack workspace to post in (defaults to the only/first installed). |
| `text` | string |  |  |
| `thread_ts` | string |  | For share_forecast: post the card as a reply in this thread (thread = question/round). |
| `threshold` | number |  | For set_resolution_rule: the numeric threshold the observed value is compared against. |
| `tier` | string | `free`, `reforecast` | run_warning_automode: per-tier bulk pass. 'free' = non-LLM kinds {bookkeeping,score,postmortem,material_change}; 'reforecast' = the opt-in LLM reforecast/evidence tier. |
| `timespan` | string |  |  |
| `title` | string |  |  |
| `to_question_id` | string |  | For link/unlink: the target forecast id. |
| `toolset_version` | string |  |  |
| `topic` | string |  |  |
| `topics` | array<string> |  |  |
| `trigger_reason` | string |  |  |
| `triggered_by` | string |  |  |
| `trim` | integer |  | Drop N highest + N lowest panel estimates before pooling. |
| `trusted_policy_id` | string |  |  |
| `uncertainty` | number |  |  |
| `unit` | string |  |  |
| `units` | string |  |  |
| `unresolved_only` | boolean |  |  |
| `update_triggers` | array |  | List of mechanism/threshold triggers that should prompt a review. Each entry is either a free-form mechanism string or an object with mechanism, threshold, action, window, source_ref, or notes keys. A trigger becomes EXECUTABLE (checkable via action='check_update_triggers') when it sets operator (>, >=, <, <=, ==, !=) plus a source_ref and a numeric threshold — then it fires automatically when the imported value for that source crosses the threshold. |
| `url_filter` | string |  |  |
| `use_active_lessons` | boolean |  | update_forecast: apply the ledger's measured calibration-bias correction (active in-scope lessons) to the committed probability. DEFAULT TRUE for LIVE commits only — the learned correction lands automatically and the pre-adjustment raw_probability is recorded for audit. backtest/imported_baseline are NEVER auto-adjusted (the correction is live-derived and would contaminate the closed-book benchmark); pass true to opt in explicitly. Pass false to opt out (commit your raw number). Exploratory commits are never adjusted. |
| `use_watched` | boolean |  | triage_label: instead of `candidates`, pull candidate readings from the question's watched sources (requires question_id). |
| `value_column` | string |  |  |
| `value_field` | string |  |  |
| `venue` | string | `polymarket`, `kalshi` | pm_query: which prediction-market venue. Omit on mode='search' to query both. |
| `verifier_labels` | array<object> |  | triage_contested: optional second-opinion labels [{candidate_ref|id, label}]; an item is CONTESTED where the verifier disagrees with the auto-label (the L8 trick). Without it, the labeler's own boundary/conflict cases are flagged. |
| `view` | string | `full`, `summary` | show_question preset: 'summary' returns just question essentials + current forecast + counts (no arrays); 'full' (default) returns everything. |
| `vs_currency` | string |  |  |
| `wait` | boolean |  | start_quorum: run inline to completion and return the finished job (default false = detached). |
| `watches` | array<object> |  | For add_watched_sources (BULK): one entry per watch — {question_id (or scope_type+scope_ref), source, source_type?, role?, label?}. ONE call covers a whole thesis (e.g. 35 races x 7 sources); prefer this over scripting loops. |
| `what_happened` | string |  |  |
| `what_was_expected` | string |  |  |
| `window_days` | integer |  | detect_templated_batches: look-back window (default 7). |
