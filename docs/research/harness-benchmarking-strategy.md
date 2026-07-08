# Forecast Harness Benchmarking Strategy: Rationale, Formalisms, and Credibility Bar

**Date:** 2026-06-30
**System:** hermes-agent superforecasting fork (`superforecasting-agent-snapshot`)
**Status:** research rationale / benchmark design
**Companions:** [ForecastBench Grounding Study](forecastbench-grounding-study.md),
[Beating the Market Strategy](beating-the-market-strategy.md),
[Live Edge Study](live-edge-study.md)

## Abstract

The benchmark should support a claim about the forecasting **environment**, not a loose claim that an
LLM can guess better than markets. The environment is the harness: question admission, evidence
capture, market baseline capture, independent probability formation, update discipline, resolution
tracking, scoring, postmortems, and calibration memory. A strong benchmark must therefore measure the
whole chain. It must show, within a pre-registered cohort and stated limits, that the harness creates
durable, auditable, non-market-bounded opinions and, where results support it, achieves paired
outperformance against registered market comparators while case audits identify plausible mechanisms.

The current `market_nightly` ledger is a useful pilot, but it is not yet a representative showcase.
It contains 292 live forecasts with preserved market baselines and questions that were
future-resolving at forecast/capture time, which are useful ingredients for foreknowledge control.
But it has no resolved scores yet, no admission
records, no evidence items, no model-run records, no durable agent rationale beyond a generic
benchmark note, no audit manifest for the ledger queries, and mixed question quality. That makes it
valuable as a seed cohort and a diagnostic, not sufficient evidence that the harness improves
forecasting. This memo defines the benchmark formalisms and the strategy needed to make that claim
credible.

The core principle is simple: **do not benchmark the probability alone**. Benchmark the probability
plus the environment that produced it.

## Two Benchmark Theses

The benchmark program has two different theses. They are both valuable, but they should not be
collapsed into one claim.

| Thesis | Core question | Primary value | Primary benchmark shape |
|---|---|---|---|
| Autonomous edge | Can the harness, without human help, add a little independent signal against a registered market comparator? | External credibility: the system is not just a polished probability generator | Prospective market cohort, autonomous arms, paired Brier/log score vs registered market comparator |
| Forecasting desk | Can a user and agent work forecasts over time in an environment that produces superforecasting-level or better judgment? | Product value: the harness is a forecasting gym, desk, and review game that improves practice | Human+agent workflow cohorts, repeated updates, review discipline, calibration, postmortems, lesson reuse |

The first thesis is deliberately narrow. Markets are hard to beat; even a small prospective paired
edge can matter if it is out of sample, evidence-linked, and registered before outcomes. This is the
credibility wedge, not the whole product story.

The second thesis is the larger product claim. In this mode, the market is not only an opponent; it
is also a prior, tutor, calibration reference, and sparring partner. The benchmark asks whether the
environment makes the human+agent pair better than reasonable alternatives: user alone, agent alone,
market comparator alone, generic chat, and first-pass forecasts without desk workflow.

These theses require different evidence. Autonomous edge claims require strict autonomy and market
contamination controls. Forecasting-desk claims require explicit human/agent intervention records,
workflow comparators, temporal scoring, and later cohorts showing that recorded lessons improved
behavior. A result from one thesis should not be used as proof of the other.

## 1. The Claim We Actually Need To Test

The product thesis is not:

- "The model beats markets."
- "The agent diverges from markets."
- "The ledger has many forecasts."
- "The system can produce a probability."

Those are too weak. A model can diverge by being noisy, a ledger can be full of bad questions, and a
probability without evidence is not auditable.

The benchmark should test this stronger claim:

> Given a scoreable forecasting question, the harness can admit the question, freeze a market
> baseline, gather admissible evidence, create an independent forecast, preserve the reasoning trail,
> update only through explicit forecast events, resolve the question, score the agent against the
> baseline, and create learning records from the error. On selected classes of questions, that
> process produces useful signal that is not merely a copy of the market.

That claim decomposes into five measurable subclaims:

| Subclaim | What must be shown | Failure mode if absent |
|---|---|---|
| C1. Clean case creation | Question, close time, resolution criteria, market baseline, and cutoff are frozen before outcome | Leakage, vague targets, hindsight edits |
| C2. Evidence discovery | The harness captures timely, admissible evidence and links it to the forecast | The forecast is a naked probability |
| C3. Independent judgment | The agent forms a probability without mechanically anchoring on the market | The agent is a noisy market clone |
| C4. Proper scoring | Outcomes resolve cleanly and paired scores compare agent vs market | No objective evidence of edge |
| C5. Learning loop | Errors produce postmortems, calibration lessons, and future policy changes that can be tested in later cohorts | No validated compounding judgment |

The current 292-question pilot partially exercises C1: it has questions, timestamps, snapshots, and
market baselines, but it lacks admission records, run records, and an immutable audit manifest. It
does not yet exercise C2, C4, or C5, and it only partially exercises C3 because the stored rationale
does not show how the probability was made.

## 2. Readout From The Current `market_nightly` Pilot

Read-only ledger inspection on 2026-06-30 found the following state for the `market_nightly` cohort.
These numbers are operational audit notes until they are paired with a reproducible ledger export,
query script, schema version, and content hash.

| Item | Observation |
|---|---|
| Questions | 292 active, 0 resolved |
| Forecast snapshots | 292 total, exactly 1 per question |
| Market baselines | 292 total, exactly 1 per question |
| Evidence items | 0 |
| Model runs | 0 |
| Score records | 0 |
| Sources | Manifold 126, Metaculus 73, Polymarket 63, Infer 30 |
| Horizons | 9 under 1 day, 74 from 1-3 days, 8 from 3-7 days, 39 from 7-30 days, 96 from 30-180 days, 66 over 180 days |
| Already due by audit time | 12 |
| Duplicate exact titles | 4 title groups |
| Stored snapshot rationale | Generic benchmark commitment text, not the agent's reasoning |

The agent does materially diverge from the market in places:

| Divergence statistic | Value |
|---|---|
| Average agent probability | 0.3915 |
| Average market probability | 0.3714 |
| Average absolute difference | 0.1445 |
| `abs(agent - market) < 0.01` | 35 questions |
| `abs(agent - market) < 0.05` | 116 questions |
| `abs(agent - market) >= 0.20` | 71 questions |
| Agent above market | 144 questions |
| Agent below market | 145 questions |
| Extreme agent probabilities under 1% | 25 questions |
| Extreme agent probabilities over 99% | 10 questions |

This is enough to show non-trivial movement off the market. It is not enough to show skill. Some of
the largest disagreements may be excellent contrarian calls; some may be naive or malformed. Without
evidence, model runs, and durable rationales, the ledger cannot tell the difference.

The cohort also contains questions that are weak representatives for a serious harness benchmark:
personal markets, fandom markets, sports one-offs, duplicated World Cup questions, short-fuse
markets, and markets whose resolution criteria are more socially or platform-specific than
externally adjudicable. They are not useless, but they should be labeled as low-quality or excluded
from the showcase panel.

### Audit Reproducibility Gap

The pilot report must not ask reviewers to trust local inspection notes. It needs an artifact bundle:

| Artifact | Purpose |
|---|---|
| Ledger export | Exact rows used for the pilot analysis |
| Query script | Re-runnable SQL or Python that produces the counts and divergence tables |
| Schema version | Documents which ledger layout the queries expect |
| Data hash | Content hash of the exported cohort |
| Run timestamp | When the audit was generated |
| Code commit | Repository state used to produce the report |
| Exclusion log | Any rows skipped from the analysis and why |

Without that bundle, the 292-case readout should be treated as internal diagnosis, not an externally
auditable benchmark result.

### Decision On The Current 292

Keep the 292-question set as a **pilot cohort**. Do not discard it, edit it, or retrofit evidence
after the fact. Score it as-is when resolutions arrive and use it to test ingestion, market baseline
capture, pending/scored reports, and failure rates.

Do not use it as the main evidence that the harness improves forecasting. It lacks the artifacts needed
to support that claim.

## 3. Benchmark Unit: The Forecast Case

The unit of evaluation should be a `ForecastCase`, not a row of probabilities.

A forecast case is:

```text
ForecastCase =
  Question
  + CandidatePoolRecord
  + PreRegistrationManifest
  + AdmissionRecord
  + ForecastCutoff
  + MarketBaselineSet
  + MarketSnapshotSet
  + EvidenceSet
  + AgentRunSet
  + ForecastSnapshotSet
  + UpdateSet
  + ReviewInterventionRecord
  + ResolutionRecord
  + ResolutionAdjudicationRecord
  + ScoreRecordSet
  + PostmortemRecord
  + AuditManifest
  + PublicationBundle
```

Each component has a different job:

| Component | Purpose |
|---|---|
| `Question` | Stable title, body, binary direction, resolution source, resolution criteria, open/close/resolution dates |
| `CandidatePoolRecord` | The source pool from which the question was drawn, including rejected candidates and exclusion reasons |
| `PreRegistrationManifest` | Timestamped, content-addressed rules for endpoints, arms, sample size, exclusions, scoring, and stopping |
| `AdmissionRecord` | Why this case was allowed into the benchmark, including quality tier and exclusions checked |
| `ForecastCutoff` | The exact time after which evidence is inadmissible for the forecast event |
| `MarketBaselineSet` | First market baseline at forecast cutoff, including raw venue payload/page snapshot, orderbook/API locator, and hash |
| `MarketSnapshotSet` | Matched market snapshots at every scored agent checkpoint or update checkpoint |
| `EvidenceSet` | Sources available before cutoff, with stance, relevance, reliability, archive locator, retrieval metadata, and captured content hash |
| `AgentRunSet` | Full prompts/messages, raw response, provider response ID, API/model revision, system fingerprint when available, sampling params, tool inputs/outputs, config, code commit, container/tool runtime hash, token/cost metadata, errors |
| `ForecastSnapshotSet` | Probability, rationale, confidence, assumptions, reference classes, and uncertainty drivers |
| `UpdateSet` | Explicit probability changes with evidence deltas and timestamps |
| `ReviewInterventionRecord` | Human or panel interventions, visibility conditions, requested changes, overrides, and timestamps |
| `ResolutionRecord` | Outcome, resolver, resolution timestamp, source, ambiguity notes, archived resolver artifact, and content hash |
| `ResolutionAdjudicationRecord` | Lock-before-score decision, adjudicator identity/type, blinding status, procedure, and excluded/ambiguous handling |
| `ScoreRecordSet` | Brier, log score, market comparison, calibration bucket, stratification labels |
| `PostmortemRecord` | Error cause, lesson, future policy change, calibration implication |
| `AuditManifest` | Canonical serialization, manifest schema, hash algorithm, parent hashes, case-component hashes, signature key identity, signed/timestamped releases, query scripts, dependency lock, and verification logs |
| `PublicationBundle` | Public artifacts, restricted audit artifacts, redactions, derivation map, and hashes for public/redacted/non-public materials |

This formalism prevents a common benchmark failure: treating a single number as if it represents the
whole forecasting process.

## 4. Admission Formalism: Which Questions Count

A benchmark can only showcase harness quality if question quality is controlled before outcomes are
known. Admission should be prospective, deterministic where possible, and recorded in the ledger.

### Required Criteria

A showcase-quality binary question should satisfy all of these:

| Requirement | Rationale |
|---|---|
| Binary, scoreable outcome | Brier/log scoring needs a clean yes/no resolution |
| External resolution source | Avoid platform-only or personal adjudication when possible |
| Clear close and resolution dates | Prevent hindsight and stale-baseline ambiguity |
| Forecast cutoff before outcome | Preserve foreknowledge control |
| Market baseline timestamped at cutoff | Pair agent and market under the same information clock |
| Pre-registered market quality threshold | Avoid meaningless prices from abandoned or one-trader markets |
| Non-duplicative title and semantic target | Prevent overweighting repeated questions |
| Non-personal and non-self-referential | Avoid idiosyncratic questions the harness cannot research well |
| Evidence availability expected | The harness cannot showcase evidence work on evidence-empty trivia |
| Resolution criteria not primarily subjective | Reduce adjudication noise |

### Candidate Pool Ledger

Every benchmark run needs a denominator. The harness should persist the full candidate pool before
outcomes are known, not just admitted questions:

| Field | Purpose |
|---|---|
| `candidate_pool_id` | Stable identifier for a collection run |
| `source` | Venue, dataset, search query, or manual panel source |
| `collection_params` | API query, filters, time window, seed, and source version |
| `response_boundaries` | API pages, pagination cursors, collection windows, and included/excluded response ranges |
| `collected_at` | Timestamp for the candidate scrape/import |
| `collection_log_locator` | Retry log, failed requests, rate-limit events, and collection warnings |
| `raw_candidate_id` | Source-native candidate identifier |
| `raw_payload_locator` | Raw API response, page snapshot, or import file containing the candidate |
| `raw_payload_hash` | Hash of the raw candidate payload or snapshot |
| `normalized_question_key` | Duplicate-detection key |
| `admission_decision` | admitted, excluded, deferred |
| `admission_tier` | Tier A/B/C/D if admitted or excluded |
| `exclusion_labels` | All exclusion reasons that fired |
| `candidate_hash` | Hash of normalized candidate fields |

Curated panels and disagreement panels are only credible if their rejected cases are visible and
reconstructable. If raw payloads cannot legally or operationally be retained for all rejected cases,
the minimum fallback is source ID, normalized fields, retrieval metadata, candidate hash, and a
redaction/restriction reason. If the candidate denominator or collection log is missing, the panel is
a case-study set, not a benchmark estimate.

### Initial Operational Thresholds

These are starting thresholds, not universal truths. A run may change them only by declaring the
change in the pre-registration manifest before outcomes are known.

| Criterion | Tier A | Tier B | Tier C / stress |
|---|---|---|---|
| Horizon at first forecast | 7-180 days | 1-365 days | Outside Tier A/B but scoreable |
| Distinct traders, if available | `>= 25` | `>= 8` | `< 8` or unavailable |
| Venue-relative volume/liquidity | `>= 50th percentile` of that run's venue pool | `>= 25th percentile` | Below Tier B |
| Bid/ask spread or proxy, if available | `<= 0.10` | `<= 0.20` | Wider or unavailable |
| Market staleness, if available | last price/trade/update `<= 72h` | `<= 14d` | Older or unavailable |
| Evidence expectation | `>= 3` independent admissible sources | `>= 1` admissible source | Evidence-poor but scoreable |
| Duplicate rule | no exact normalized-title match and no semantic match above the registered threshold | same | allowed only for stress/audit |
| Resolver | external and objective | external or platform adjudicated but clear | ambiguous allowed only if labeled |

Semantic duplicate detection should use the simplest available rule that is declared before the run:
normalized exact title first; if embeddings or nearest-neighbor matching are used, register the
similarity threshold and keep the matched-pair log.

Missing market-quality fields should fail conservatively. If a venue lacks traders, spread, staleness,
or volume proxies, the run manifest must state the venue-specific fallback before collection. Without
a registered fallback, the case can be scored but should not enter Tier A or headline market-quality
claims.

### Exclusion Labels

Not every excluded question is bad. Some are fine for stress tests. The important part is labeling
them before scoring:

| Label | Meaning |
|---|---|
| `excluded:personal` | Depends on a private individual's future action or self-report |
| `excluded:gimmick` | Entertainment, stunt, or platform in-joke market |
| `excluded:duplicate` | Same semantic target as an admitted case |
| `excluded:ambiguous_resolution` | Outcome could be reasonably disputed |
| `excluded:thin_market` | Baseline is too noisy to serve as a strong comparator |
| `excluded:too_short_horizon` | Not enough time for evidence and update loop |
| `excluded:too_long_horizon` | Resolution too far away for near-term study goals |
| `excluded:source_unavailable` | No durable external evidence source |

### Quality Tiers

Admitted questions should be tiered rather than all treated equally:

| Tier | Use |
|---|---|
| Tier A | Showcase panel: externally resolvable, evidence-rich, non-duplicative, above-threshold market quality |
| Tier B | Live benchmark: scoreable and admissible, but with thinner market or less evidence |
| Tier C | Stress/test cohort: useful for system robustness, not for headline claims |
| Tier D | Excluded from scored benchmark, retained only for audit if already collected |

The current 292-question pilot likely spans all four tiers. The next collection run should assign
tiers at admission time.

## 5. Evidence Formalism

The harness should show that it can discover, capture, and use information, not just emit opinions.
Evidence therefore needs to be first-class ledger state.

Each evidence item should preserve:

| Field | Meaning |
|---|---|
| `source_type` | News, filing, official data, market page, expert analysis, database, social, other |
| `source_name` | Publisher, agency, platform, or dataset |
| `url_or_locator` | Durable link or local snapshot reference |
| `published_at` | When the source became public, if known |
| `captured_at` | When the harness captured it |
| `retrieval_method` | Browser, API, feed, manual import, archive lookup, or tool name |
| `archive_locator` | Local snapshot path, WARC record, immutable export, or external archive reference |
| `available_at_cutoff` | Whether it was admissible for this forecast event |
| `availability_proof` | Archive memento time, feed log, HTTP Date/Last-Modified/ETag, signed dataset version, or equivalent |
| `stance` | Supports yes, supports no, mixed, background, or resolution-only |
| `relevance` | Why this source matters to the question |
| `reliability` | Official, primary, reputable secondary, weak secondary, unknown |
| `claim_summary` | Short factual claim extracted from the source |
| `quoted_spans` | Minimal source spans used to support forecast claims, subject to copyright limits in public reports |
| `content_hash` | Hash of captured text/snapshot for every claim-supporting source |
| `used_by_snapshot_id` | Which forecast event used it |
| `rationale_claim_ids` | Which rationale claims this evidence supports |

For auditability, a URL alone is not evidence, and a boolean `available_at_cutoff` is not proof of
availability. Claim-supporting evidence needs captured content or an archive locator, retrieval
metadata, a content hash, and timestamp evidence that the content was available before the forecast
cutoff. If a source cannot be archived or timestamp-proven, the forecast may still use it, but the
evidence item should be flagged `unarchived` or `availability_unproven` and excluded from
no-leakage and evidence-quality claims.

Evidence coverage should be scored separately from forecast accuracy:

| Evidence metric | Why it matters |
|---|---|
| Evidence count per snapshot | Detect naked probabilities |
| Independent source count | Avoid five articles repeating one wire story |
| Primary-source fraction | Reward official data over commentary |
| Freshness at cutoff | Identify stale reasoning |
| Stance balance | Detect one-sided search |
| Evidence-to-rationale coverage | Ensure claims in rationale are backed by evidence records |
| Inadmissible evidence rate | Catch leakage and post-cutoff contamination |
| Archived-source fraction | Detect reliance on mutable or unverifiable pages |
| Claim-level support rate | Fraction of rationale claims linked to evidence IDs/spans |

For a showcase benchmark, a forecast with zero evidence can still be scored, but it should not count
as evidence of harness value. It belongs in a separate "probability-only" arm.

## 6. Reasoning Formalism

The stored forecast artifact should be inspectable enough that a skeptical reviewer can tell why the
probability moved.

Each forecast snapshot should include:

| Field | Purpose |
|---|---|
| `probability` | The committed forecast |
| `rationale` | Concise argument for the probability |
| `outside_view` | Base rate or reference class |
| `inside_view` | Case-specific evidence and mechanisms |
| `assumptions` | Key assumptions whose failure would change the forecast |
| `yes_drivers` | Strongest reasons the event happens |
| `no_drivers` | Strongest reasons it does not happen |
| `claim_ids` | Stable IDs for factual claims in the rationale, linked to evidence IDs/spans |
| `market_view` | How the market baseline was used, if visible |
| `market_critique` | Why the agent disagrees with the market, if it does |
| `change_my_mind` | Evidence that would cause a material update |
| `confidence` | Epistemic confidence in the estimate, separate from probability |
| `protocol_version` | Parser/prompt/procedure version |

The key benchmark distinction is **market-hidden independent judgment** versus **market-aware
reasoning against the baseline**. Both are useful, but they answer different questions:

| Arm | Market price visible? | What it tests |
|---|---|---|
| Market-hidden | No | Can the harness retrieve evidence and form independent signal? |
| Market-aware | Yes | Can the harness correctly critique, use, or override a market? |
| Market-only | Yes, no agent | Strength of the baseline |
| Ensemble | Yes, after forecasts | Whether independent signal complements the market |

The system should never blur these arms. Showing the market inside the prompt and then claiming
independent signal is an anchoring confound.

Market-hidden must be operationally protected, not merely labeled. A market-hidden run should retain:

- Full prompt/messages proving the market baseline was not supplied.
- Tool and network logs showing which URLs, APIs, redirects, search result pages, snippets, cached
  summaries, and returned content were accessed.
- A registered blocklist for market domains and derivative market-price pages when the arm requires
  no market exposure.
- The blocklist/classifier version used for market-price detection.
- Per-access classification: market price, market discussion, derivative odds, non-market source,
  unknown, or contaminated.
- Evidence-source provenance showing whether a source was a market page, market discussion, or
  non-market source.
- A contamination flag if the run encounters market odds indirectly.
- A fail-closed rule: contaminated or unknown access either excludes the run from market-hidden claims
  or relabels it `market-not-supplied`.

If the system cannot verify those conditions, call the arm `market-not-supplied`, not
`market-hidden`.

For the strictest independence claim, use a controlled retrieval corpus with market pages and
market-quoting derivative sources removed. Open-web search can support a weaker claim, but only with
the contamination audit above.

## 7. Market Baseline Formalism

The market baseline is not a single price. It is a measurement with quality attributes.

Each market baseline should preserve:

| Field | Meaning |
|---|---|
| `venue` | Manifold, Metaculus, Polymarket, Infer, other |
| `market_id` | Venue-native identifier |
| `raw_baseline_artifact` | Raw venue API response, orderbook snapshot, or page snapshot at capture time |
| `raw_baseline_hash` | Hash of the raw baseline artifact |
| `raw_probability` | Raw displayed probability or price |
| `devig_probability` | Normalized fair probability when applicable |
| `captured_at` | Timestamp paired with the agent snapshot |
| `close_time` | Market close time used for foreknowledge checks |
| `resolution_time` | Expected or actual resolution time |
| `volume` | Trading or participation depth |
| `n_traders` | Distinct participants when available |
| `spread` | Bid/ask or proxy where available |
| `staleness` | Time since last material market update |
| `fees_or_subsidy_notes` | Venue mechanics that can distort price |
| `market_quality_tier` | Strong, usable, weak, excluded |

This matters because "beating the market" means different things across venues. Beating a liquid,
fresh Polymarket price is a stronger result than beating an abandoned, low-participation play-money
market. Reports should say "registered market comparator" or name the venue when possible. Pooled
venue results are acceptable only with venue stratification and a clear explanation of the
comparator mix.

The baseline method must also be fixed before the run:

| Method choice | Required decision |
|---|---|
| Price source | bid/ask midpoint, last trade, displayed probability, or venue API probability |
| De-vig formula | exact transformation from raw venue fields to fair probability |
| Stale-market policy | when to exclude, down-tier, or keep a stale baseline |
| Spread policy | whether wide spreads exclude the case or only down-tier it |
| Fees/subsidies | whether and how venue mechanics adjust the baseline |
| Cross-venue pooling | whether venues are pooled, stratified, or reported separately |

If those choices are made after seeing outcomes, the market comparison is no longer a clean benchmark.

For workflow and update claims, the market comparator must be time-matched. Every scored agent
snapshot after the initial cutoff needs either:

- a market snapshot captured at the same checkpoint; or
- a registered rule that the market was unavailable/stale and the comparison is against the initial
  frozen baseline only.

Do not compare an updated agent against a stale market baseline and present it as market edge. Label
that as "agent update vs initial market" instead.

## 8. Forecast Arms To Benchmark

The harness should not be judged by one arm. It needs a small set of controlled arms that isolate
where value is created.

| Arm | Description | Purpose |
|---|---|---|
| M0 | De-vigged registered market comparator at cutoff | Baseline to beat |
| N0 | Registered naive/base-rate probability | Detect whether both agent and market comparators are weak |
| A0 | Closed-book, market-hidden model | Measures parametric knowledge only |
| A1 | Search-enabled, market-hidden agent | Tests independent evidence discovery |
| A2 | Full autonomous harness: evidence capture, structured reasoning, explicit update discipline | Tests the product workflow without human edits |
| A2-review | Human-reviewed harness, with intervention records | Tests the product workflow with review support |
| A2-ablation | Pre-registered ablation/factorial arms for evidence, review, updates, tools, or prompts | Identifies which treatment changed performance |
| A3 | Market-aware critique arm | Tests reasoning against a visible market |
| E1 | Pre-registered market + agent ensemble | Tests complementarity on held-out or nested evaluation |

The main showcase should emphasize A1, A2, A3, and E1. A0 is useful because it keeps the team honest:
if closed-book A0 performs poorly, then parametric model memory is unlikely to explain later gains by
itself. It does not identify causality; search, prompt changes, tool exposure, leakage, or market
visibility can also explain differences unless arms are controlled.

The bundled full-harness arm is a product test, not a causal explanation. It can show that the whole
workflow helped or hurt, but it cannot identify whether the edge came from evidence, review, updates,
tool exposure, prompt changes, or human intervention. For causal claims about a component, the same
admitted cases should be assigned across arms by a pre-registered design:

| Design requirement | Reason |
|---|---|
| Same case set where feasible | Avoid comparing easy A2 questions against hard A0 questions |
| Randomized or counterbalanced arm order | Avoid time/order effects from news arriving during the run |
| Identical forecast cutoffs per arm | Prevent one arm from seeing later information |
| Logged tool access per arm | Verify treatment differences |
| Intervention logs per arm | Separate autonomous agent behavior from human or panel changes |
| Held-out ensemble fitting | Prevent outcome leakage from fitting weights on the scored cohort |

If operational cost prevents every arm from running on every case, the missingness rule must be
pre-registered and skip rates must be reported by arm.

Human involvement must be explicit. Reviewers may be autonomous agents, humans, or mixed panels, but
the record should state what they could see and change: evidence labels, rationale text, probability,
admission/exclusion decisions, resolution interpretation, or postmortem classification. Public claims
should say `autonomous`, `agent-reviewed`, `human-reviewed`, or `mixed-review`; do not call a
human-edited forecast simply "the agent."

The `N0` baseline must be pre-registered too. Define its source, procedure, smoothing/clipping rule,
and scope before results are known: for example a global training-set base rate, domain base rate,
historical reference-class rate, or constant 0.5. A vague or post-hoc base-rate arm is not a useful
comparator.

## 9. Scoring Formalism

Scoring must be paired, proper, and stratified.

### Primary Metrics

| Metric | Use |
|---|---|
| Mean Brier score | Main binary forecast accuracy metric |
| Paired Brier difference | Agent vs market on the same cases |
| Log loss | Penalizes confident misses, with pre-registered clipping, default `[0.01, 0.99]` |
| Calibration curve / ECE | Whether stated probabilities match frequencies |
| Sharpness | Whether forecasts make useful distinctions |
| Resolution coverage | Fraction of admitted cases that resolve cleanly |
| Abstention/skip rate | Whether the harness silently avoids hard cases |

### Statistical Tests

The headline comparison should be paired by question:

```text
edge_i = brier(market_i, outcome_i) - brier(agent_i, outcome_i)
mean_edge = mean(edge_i)
```

Positive `mean_edge` means the agent beats the market on Brier. Report:

- `n` paired resolved cases.
- Mean agent Brier.
- Mean market Brier.
- Mean paired edge.
- 95% clustered or block-bootstrap confidence interval.
- Paired p-value or permutation test with the registered clustering unit.
- Agent wins, market wins, ties.

Do not report only aggregate agent Brier and aggregate market Brier without paired uncertainty. The
same case set must feed both sides.

Question-level pairing is necessary but not sufficient. Questions are correlated by event, venue,
domain, collection date, source, and sometimes by duplicated market targets. The pre-registration
manifest must name the uncertainty method:

| Issue | Required handling |
|---|---|
| Event clusters | Cluster or block by normalized event/semantic target when possible |
| Venue/source clusters | Report venue-stratified results and use venue-aware resampling for pooled claims |
| Time clusters | Block by collection date or forecast batch for live runs |
| Duplicate/near-duplicate questions | Exclude, down-weight, or cluster before scoring |
| Multiple arms | Declare one confirmatory primary comparison before results |
| Multiple strata | Label exploratory strata or apply a registered multiplicity correction |
| Ensemble weights | Fit on historical/previous cohorts, nested folds, or a held-out split only |

The default confirmatory endpoint should be one paired Brier edge on one pre-registered cohort. Other
arms and strata are exploratory unless the manifest says otherwise. For confirmatory families, use a
registered correction such as Holm for family-wise error control or Benjamini-Hochberg for discovery
claims.

Held-out and nested splits must respect time, venue, event, and semantic clusters. Random row-level
splits can leak duplicates, shared event regimes, and market conditions into the fitted ensemble.

### Power And Sample Size

Sample sizes should be justified by a minimum detectable paired Brier edge, not round numbers. Before
collection, the manifest should declare:

- Target minimum detectable edge, for example `0.01` or `0.02` Brier.
- Expected outcome base rate.
- Expected resolution attrition and ambiguous-resolution rate.
- Estimated standard deviation of paired Brier differences from prior resolved cohorts.
- Expected intra-cluster correlation or the block bootstrap plan used to estimate effective `n`.
- Required effective resolved `n` after clustering and attrition.
- Simulation or analytic method used to justify the effective `n`.
- Rule that the result is labeled `underpowered` or `inconclusive` if the effective resolved `n` falls
  below the registered adequacy threshold.
- Stopping rule: fixed calendar, fixed admitted `n`, fixed resolved `n`, or sequential rule.

Small panels can still be useful for case audits and workflow testing, but they should not be used
for calibration or market-beating claims unless the power analysis supports that use.

### Stratification

Overall score is necessary but insufficient. The harness should report edge by:

| Stratum | Why |
|---|---|
| Venue | Market quality varies by platform |
| Horizon | Short-fuse and long-horizon questions behave differently |
| Market quality tier | Thin markets are easier but weaker evidence |
| Evidence density | Exploratory unless evidence access/intensity is assigned as a treatment |
| Disagreement size | Tests whether contrarian calls are signal or noise |
| Question domain | Politics, macro, sports, AI, technology, geopolitics differ |
| Question depth and market liquidity | Tests the thesis that surface/liquid questions are harder to beat than deep, multifactor, thinly priced questions |
| Update count | Tests whether the desk workflow improves over one-shot forecasts |
| Resolution ambiguity | Separates clean outcomes from noisy adjudication |

The benchmark should expect some strata to fail. A credible result says where the harness works and
where it does not.

Evidence-density strata are endogenous: evidence-rich questions may simply be different questions.
To claim that research caused improvement, compare different evidence/search treatments on the same
case set or pre-register evidence access as a randomized treatment arm.

Update-count strata are endogenous for the same reason: volatile questions attract more evidence and
operator attention. To claim the update workflow improves accuracy, use fixed update schedules,
randomized update intensity, or paired update-policy arms on the same case set. Otherwise update
metrics are descriptive workflow diagnostics.

### Question Depth And Liquidity Stratum

The benchmark should explicitly separate surface/liquid questions from deep, multifactor, thinly
priced questions. This is a product-thesis stratum, not a license to cherry-pick hard-looking wins
after scoring.

| Stratum | Definition | Expected product value |
|---|---|---|
| `surface_liquid` | Salient, simple, externally resolvable questions with few major inputs and a fresh, liquid, high-attention market | Calibration baseline; market edge should be hard and likely small |
| `deep_multifactor_thin` | Externally resolvable questions requiring multiple evidence streams, domain context, explicit assumptions, and aggregation, with stale, thin, wide-spread, or low-attention markets | Core harness thesis; human+agent evidence aggregation may outperform weak market pricing |
| `complex_unusable` | Multifactor questions that are subjective, evidence-poor, personal, platform-native, or resolution-ambiguous | Down-tier or exclude from headline claims |

The labels must be assigned before outcomes are known using registered criteria such as input-factor
count, expected independent source count, domain-context requirement, market participation, spread,
volume, staleness, and venue attention. Complexity alone is not enough. A deep question only supports
the product thesis if it is still scoreable, evidence-rich, and resolvable.

Reports should show `surface_liquid` and `deep_multifactor_thin` results separately. A credible
outcome may show little or no edge on surface/liquid questions while showing stronger value on the
deep/multifactor/thin stratum. That should be presented as support for the product boundary, not as
a pooled universal market-beating claim.

### Resolution And Adjudication

Resolution must be archived and locked before scoring. Each resolved case should preserve:

| Field | Purpose |
|---|---|
| `resolver_artifact` | Raw resolver API response, page snapshot, official filing, or adjudication document |
| `resolver_artifact_hash` | Hash of the raw resolution artifact |
| `resolver_retrieved_at` | When the resolver artifact was captured |
| `resolver_retrieval_method` | API, browser, feed, manual import, or official data release |
| `resolver_archive_locator` | Local snapshot, WARC record, immutable export, or external archive reference |
| `resolver_source_version` | Resolver API/data/schema version when available |
| `resolver_availability_proof` | Evidence that the resolver artifact was public or authoritative before scoring |
| `resolution_procedure` | Pre-registered rule mapping resolver output to yes/no/ambiguous |
| `adjudication_locked_at` | Timestamp when the outcome/exclusion decision was frozen |
| `adjudicator_type` | Automatic resolver, blind human adjudicator, platform resolution, or mixed |
| `adjudicator_visibility` | Whether adjudicator saw forecasts, market prices, scores, or only criteria/evidence |
| `ambiguity_action` | score, exclude, defer, or sensitivity analysis |

Manual or ambiguous adjudication should be blind to agent probabilities, market probabilities, and
paired score impact where possible. If blinding is impossible, the report should say so and run a
sensitivity analysis for disputed cases.

Ambiguous cases should follow an intention-to-score report: list all ambiguous, excluded, deferred,
and sensitivity-only cases by arm, venue, stratum, forecast extremity, and potential score impact.
Otherwise ambiguous-resolution attrition can quietly improve the headline result.

## 10. Environment Metrics

The harness is an environment, so its operational behavior is part of the benchmark.

| Metric | Target behavior |
|---|---|
| Time to admitted case | Fast enough for nightly/live operation |
| Evidence capture latency | Fresh evidence appears before forecast cutoff |
| Agent runtime | Predictable enough for scaled benchmark runs |
| Tool failure rate | Failures are visible, not silently converted into weak forecasts |
| Parse failure rate | Invalid outputs are counted and debugged |
| Cost per forecast | Allows repeatable large-n studies |
| Snapshot immutability | Forecast probabilities are append-only |
| Baseline immutability | Market baselines are not refreshed after scoring |
| Reproducibility | Prompt/protocol/model/tool versions are recoverable |
| Audit completeness | Every score can be traced back to question, evidence, run, and snapshot |
| Artifact completeness | Required prompts, raw responses, tool logs, source snapshots, hashes, and configs are present |
| Market-hidden contamination rate | Market-hidden arms record and report any direct or indirect market-price exposure |

These metrics prevent a polished score report from hiding a brittle workflow.

## 11. Benchmark Tracks

No single benchmark can support every product claim. Use separate tracks with different claims.

| Track | Thesis served | Claim type |
|---|---|---|
| A. Historical closed-book grounding | Support for both, but not headline proof for either | Calibration and leakage-control sanity check |
| B. Prospective live market benchmark | Autonomous edge | Confirmatory market-comparator test when powered and pre-registered |
| C. Curated evidence-rich showcase | Both, mostly case audit | Mechanism-rich examples; headline only if representative and powered |
| D. Market-disagreement panel | Autonomous edge, exploratory | Tests contrarian signal when the agent disagrees with the market comparator |
| E. Forecast desk workflow benchmark | Forecasting desk | Human+agent environment value over time |

### Track A: Historical Closed-Book Grounding

Purpose: establish model calibration and detect market anchoring.

Strengths:

- Fast.
- Resolved outcomes already known to the evaluator.
- Useful for calibration gates and regression tests.

Limits:

- Search is foreknowledge-unsafe on resolved questions.
- Closed-book historical tests can still be contaminated by model pretraining, benchmark
  memorization, or public writeups; register model cutoff and contamination checks.
- It does not test live evidence capture.
- It cannot support live market-edge claims.

This is the role of the ForecastBench grounding study.

### Track B: Prospective Live Market Benchmark

Purpose: test foreknowledge-safe market comparison.

Strengths:

- Open questions resolve in the future.
- Market baseline is naturally available.
- Paired scoring is clean.

Limits:

- Slow to mature.
- Market quality varies.
- Without evidence/run persistence, it says little about the harness beyond collection and scoring.

This is the right role for `market_nightly`, after instrumentation is tightened.
This is the first-choice track for the autonomous-edge thesis.

### Track C: Curated Evidence-Rich Showcase Panel

Purpose: demonstrate the full harness on questions where research should matter.

Admission should require:

- Tier A question quality.
- Enough time before close for evidence collection and updates.
- Expected evidence availability.
- A mechanical pre-registered trigger for why research may matter, such as stale market, wide spread,
  low participation, new primary evidence, venue outage, or missing source coverage.
- Pre-registered inclusion before outcome.
- A published candidate denominator with rejected cases and exclusion reasons.

This is the best public showcase track because it lets the reviewer inspect the chain from evidence
to probability to score. It is not the headline estimate of general market-beating performance unless
its candidate pool and inclusion rule are representative and pre-registered. If inclusion depends on
human judgment about a plausible anti-market story, label the track as case-study showcase only.

### Track D: Market-Disagreement Panel

Purpose: test whether large deviations from market are skill or noise.

Selection must be prospective. It is acceptable to select questions where the agent and market
disagree, but only before resolution and with fixed rules such as:

- `abs(agent - market) >= 0.20`.
- Evidence density above threshold.
- Market quality not excluded.
- No resolution leakage.
- Candidate pool and all non-selected cases retained.

Report this separately. It is not an unbiased estimate of general forecasting skill, but it is a
direct test of what happens when the agent disagrees with markets. "Markets were wrong" is a
post-outcome stratum, not a prospective selection condition.

### Track E: Forecast Desk Workflow Benchmark

Purpose: test the workflow that is intended to compound judgment over time.

This track should score not just first forecasts, but:

- Research event creation.
- Scheduled updates.
- Watch-source alerts.
- Probability update quality.
- Review discipline.
- Postmortem quality.
- Calibration lesson reuse.

This is the track that best represents the product direction in `AGENTS.md`: a forecasting desk that
records and reuses judgment over time, not a one-shot probability generator.

Workflow claims need a temporal scoring rule. Use fixed checkpoints, time-weighted Brier, or another
pre-registered update metric, with market snapshots captured at the same checkpoints. Do not select
only the final or most flattering update after resolution.

This is the first-choice track for the forecasting-desk thesis. Its comparisons should include
human+agent desk versus user alone, agent alone, registered market comparator, generic chat, and
first-pass forecasts without the desk workflow where feasible. Its headline is not "the agent beat
the market"; its headline is whether the environment improves repeated judgment, calibration,
update quality, and lesson reuse.

## 12. Product Value Readout

The benchmark should not read only as a statistical leaderboard. The product is a forecasting desk,
so the report should also show what the environment lets a real operator do that a market page,
spreadsheet, or generic chat window does not.

### Product Scorecard

Each public benchmark report should include a compact scorecard that maps product value claims to
auditable artifacts:

| Product value claim | Required artifact |
|---|---|
| Finds non-market signal | Paired market edge, disagreement-panel results, and case audits |
| Makes reasoning auditable | Evidence-to-claim links, archived sources, run logs, and artifact hashes |
| Improves user judgment | Human+agent desk versus user-alone, agent-alone, and generic-chat workflow cohort |
| Compounds learning | Postmortem lessons and later-cohort tests of reused policies |
| Saves analyst time | Time to admitted case, time to first forecast, evidence coverage per minute, and cost per case |
| Prevents bad forecasts | Abstentions, down-tiered questions, ambiguity flags, and exclusion logs |

This scorecard keeps the benchmark connected to the reason the harness exists. Accuracy is necessary,
but a desk also needs to improve evidence handling, review discipline, speed, and learning.

### Forecast Replay Pages

Selected cases should be published as replay pages, not just rows in a results table. A replay page
should show the timeline:

```text
market baseline
-> candidate admission
-> evidence captured
-> agent forecast
-> human or agent review, if any
-> updates
-> resolution
-> score
-> postmortem lesson
```

The report should include at least:

- one strong win;
- one strong loss;
- one case where the market was right and the harness learned from it;
- one case where the desk correctly abstained, down-tiered, or rejected the question.

That mix is more credible than cherry-picking wins. It shows whether the environment creates
inspectable judgment, handles uncertainty, and improves after errors.

### Operator-Lift Benchmark

The forecasting-desk thesis needs an operator-centered comparison. A minimal workflow benchmark
should compare the same user or user pool across:

| Arm | What it tests |
|---|---|
| Spreadsheet/manual workflow | Existing low-tech forecasting practice |
| Generic chat | Whether ordinary LLM assistance is enough |
| Agent alone | Autonomous harness behavior |
| Human+agent desk | The product workflow: evidence, review, updates, and postmortems |

Score the arms on Brier/log score, calibration, update timeliness, evidence quality, review
completeness, time spent, and cost per completed forecast. Where possible, repeat the same design
across later cohorts to test whether the operator and desk improve together.

### Market-Failure Taxonomy

The report should pre-register where the harness expects a market-comparator advantage. Useful
categories include:

| Market condition | Why the harness may help |
|---|---|
| Stale market | Fresh evidence may not be priced yet |
| Thin or low-liquidity market | The price may be noisy or dominated by a few traders |
| Wide spread or poor depth | The displayed probability may not represent a reliable clearing price |
| Missing primary evidence | The market may not have integrated a filing, dataset, release, or domain-specific source |
| Cross-domain question | Traders may underweight evidence outside the venue's usual attention field |
| High-disagreement case | The harness can test whether divergence is signal or noise |
| Ambiguous or platform-native market | The desk can down-tier or reject cases that should not support headline claims |

This taxonomy should be prospective. "The market was wrong" is a post-outcome label, not an
admission rule.

### Decision Utility

If the benchmark claims practical value, it should include a decision-utility readout in addition to
proper scoring. This can be a paper portfolio, alert-quality test, or decision-threshold simulation,
but the rule must be fixed before outcomes:

- decision rule, such as fixed stake, capped Kelly, or act/no-act threshold;
- fees, slippage, liquidity, and venue restrictions where market actions are simulated;
- no-action, market-only, and generic-chat baselines;
- downside and drawdown metrics, not only average return;
- separation between decision utility and forecast accuracy claims.

This should not replace Brier/log scoring. It answers a different product question: whether better
probabilities would have changed decisions in a useful way.

### Operational Readiness

The report should also include a small readiness panel because a slow or brittle desk has limited
product value even if some forecasts score well:

| Metric | Product interpretation |
|---|---|
| TUI boot time | Whether an operator can start work immediately |
| Desk-view load time | Whether the dashboard is usable as a live workspace |
| Time to new forecast | Friction from question entry to committed probability |
| Time to first evidence item | Whether the harness accelerates research |
| Tool/run failure rate | Whether failures are visible and recoverable |
| Cost per completed forecast case | Whether the study can scale |
| Artifact completeness rate | Whether public claims remain auditable |

These metrics should be reported alongside forecast scores, not buried as engineering notes.

## 13. Strategy

### Phase 0: Freeze The Pilot

Treat the existing 292 `market_nightly` questions as an immutable pilot cohort.

Actions:

- Score them when resolution data arrives.
- Report missing artifacts honestly.
- Publish the query script, schema version, export hash, and code commit used for every pilot table.
- Use them to validate scoring, report generation, duplicate detection, and market-source handling.
- Do not backfill evidence or rationales as if they existed at forecast time.

Expected output:

- A pilot report with paired agent/market scores when enough cases resolve.
- A failure analysis of missing artifacts and low-quality cases.

### Phase 1: Make Forecast Artifacts Complete

Before collecting the next showcase cohort, require every admitted forecast to persist:

- Agent rationale from the actual protocol response.
- Full model run artifacts: prompts/messages, raw response, provider/model version, sampling params,
  provider response ID, API version, system fingerprint/model revision where available, config, code
  commit, container/image hash, tool runtime hash, tool calls, tool outputs, runtime, and cost.
- Evidence items with archive locators, availability proof, retrieval metadata, content hashes, and
  claim-level links.
- Raw candidate payloads and hashes for admitted and rejected cases.
- Market baseline quality fields plus raw venue/orderbook/page snapshots and hashes.
- Matched market snapshots for every scored update checkpoint.
- Resolution artifacts, adjudication locks, resolver hashes, and ambiguity decisions.
- Review/intervention records for every human, panel, or agent-review change.
- Admission tier and exclusion checks.
- Prompt/protocol version.

This is the highest-leverage fix. Without it, the benchmark remains probability-only.

### Phase 2: Add Admission Gates And Tiers

Create deterministic gates for the next live cohort:

- Persist the full candidate pool, not just admitted questions.
- Register missing-field fallback rules for each venue.
- Drop exact and semantic duplicates.
- Exclude personal/gimmick markets from showcase tiers.
- Register numeric market-quality thresholds for market-comparison claims.
- Register evidence-count/source-quality thresholds for evidence-harness claims.
- Separate Tier A/B/C instead of pooling everything.

This prevents the benchmark from being dominated by easy, noisy, or unserious questions.

### Phase 3: Run A Prospective Cohort

Pre-register a live cohort before outcomes in a timestamped, content-addressed manifest. The
manifest should be committed to the repo or an external archive, hashed, and changed only through
append-only amendments. Each amendment must state when it was made, what outcomes/resolutions were
visible, which endpoints or strata it affects, and whether affected analyses are downgraded from
confirmatory to exploratory:

- Target `n` by tier and venue.
- Primary endpoint and primary comparison.
- Minimum detectable paired Brier edge.
- Expected resolution attrition and ambiguous-resolution handling.
- Fixed collection dates.
- Fixed models/protocols.
- Fixed evidence cutoff rules.
- Fixed scoring rules.
- Fixed uncertainty, clustering, and multiplicity rules.
- Fixed stratification plan.
- Fixed stopping rule.
- Ensemble fitting method and holdout/nested-evaluation rule.
- Autonomous, agent-reviewed, human-reviewed, and mixed-review labeling rules.
- Public-bundle and restricted-audit-bundle publication rules.
- Manifest schema, hash algorithm, signature key identity, external timestamp/transparency target,
  and append-only amendment verification rules.

Default first public confirmatory claim: Track B on the powered Tier A/B live market cohort,
A2-autonomous versus M0 paired Brier against registered market comparators. Track C, Track D, workflow
claims, ensembles, and strata are exploratory unless separately powered and pre-registered.

Default first forecasting-desk claim: Track E on a prospective workflow cohort, human+agent desk
versus user-alone, agent-alone, and generic-chat comparators, with registered temporal scoring and
intervention labels. Treat this as a separate confirmatory family from autonomous edge.

The cleanest version is power-driven:

```text
Tier A showcase: n chosen for case-audit depth, not headline calibration unless powered
Tier B live market: n chosen to detect the registered paired Brier edge after attrition
Disagreement panel: all prospective cases with abs(agent - market) >= registered threshold
Workflow panel: n chosen for process audit unless temporal scoring is powered
```

Operational capacity can cap a run, but the cap and the resulting minimum detectable effect should be
declared before results are known. If sample sizes change after launch, the report should label the
reason and avoid confirmatory claims that depend on the change.

### Phase 4: Publish Paired Results And Case Audits

The report should include:

- Overall paired Brier edge.
- Clustered/block confidence intervals.
- Calibration curves.
- Venue/domain/horizon/evidence strata.
- Confirmatory versus exploratory labels and multiplicity policy.
- Disagreement-panel results.
- Ensemble weights evaluated out of sample.
- Market snapshots matched to update checkpoints.
- Skip/failure rates.
- Candidate-pool denominator and exclusions.
- Raw-artifact and redaction manifest.
- Representative wins and losses.
- Full case pages for selected examples.

A result with no edge is still valuable if it identifies where the harness fails. The worst result is
a vague partial report that cannot be audited.

### Phase 5: Convert Errors Into Harness Policy

Every resolved miss should be classified:

| Error class | Example policy response |
|---|---|
| Bad question admission | Tighten admission gate |
| Missing evidence | Add source/watch requirement |
| Evidence over-weighted | Update reliability weighting |
| Base rate ignored | Require outside-view field |
| Market was right | Adjust market-aware pooling policy |
| Market was stale | Add freshness/staleness feature |
| Overconfidence | Calibration lesson or de-extremization |
| Ambiguous resolution | Exclude similar future questions |

The benchmark should demonstrate that the desk records lessons and policy changes. Validated
learning requires a later cohort showing that reused lessons improved behavior. Postmortems are not
an afterthought; they are part of the product.

## 14. What A Strong Showcase Looks Like

A strong public case should let a reviewer answer these questions without trusting us:

1. Which thesis is this case supporting: autonomous edge, forecasting desk, or case-study mechanism?
2. What exactly was forecast?
3. When was the forecast made?
4. What did the market say at that same time?
5. What evidence was available before the cutoff?
6. Which evidence did the agent use?
7. What probability did the agent commit?
8. Why did it disagree with the market, if it did?
9. Did it update later, and why?
10. What happened?
11. How did the agent or desk score against the registered comparator?
12. What lesson or policy change did the system record?

The published artifact should include:

- Pre-registration manifest and candidate-pool denominator.
- Question and resolution criteria.
- Forecast timeline.
- Evidence table with archived source locators, retrieval metadata, and hashes.
- Claim-to-evidence links.
- Prompt/messages, raw model response, and tool access logs.
- Review/intervention record and autonomy label.
- Agent rationale.
- Market baseline table.
- Raw venue/orderbook/page snapshot hashes.
- Probability history chart.
- Resolution source, resolver artifact hash, and adjudication lock.
- Score comparison.
- Postmortem.

This is how the benchmark showcases the harness rather than merely displaying a leaderboard number.

### Public And Restricted Audit Bundles

Auditability does not require publishing secrets or copyrighted/private content in full. Each report
should define two bundles:

| Bundle | Contents |
|---|---|
| Public bundle | Redacted prompts/responses/logs, evidence excerpts within copyright limits, tables, hashes, manifests, scoring scripts, and final report |
| Restricted audit bundle | Full raw prompts, raw responses, tool outputs, source snapshots, provider metadata, and any non-public artifacts available to trusted auditors |

Every redacted artifact in the public bundle should include the hash of the unredacted restricted
artifact, the hash of the redacted public artifact, redaction reason, replacement summary, and a
redaction-manifest entry linking public artifact to restricted original. Secrets, API keys, private
data, unreleasable system prompts, and long copyrighted source text should be redacted from public
bundles, not omitted silently.

## 15. Claims We Can And Cannot Make

### Allowed Claims After The Current 292 Pilot Resolves

Only if the data supports them:

- "The live market pipeline can collect questions that were future-resolving at forecast time and
  pair agent forecasts with market baselines."
- "The agent materially diverged from market prices on a subset of live questions."
- "On this pilot cohort, agent Brier was X versus market Brier Y, with paired edge Z, if accompanied
  by the query script, export hash, schema version, and uncertainty method."
- "The pilot lacked evidence/model-run persistence, so it should not be treated as a full harness
  showcase."

### Not Allowed From The Current 292 Alone

- "The harness improved forecasts through evidence."
- "The system beat markets because its reasoning was better."
- "The agent had a durable non-market-bounded opinion."
- "The benchmark demonstrates the forecasting desk workflow."

Those claims require evidence records, model runs, rationales, updates, and postmortems.

### Allowed Autonomous-Edge Claims After A Proper Cohort

If the cohort is pre-registered and the results support it:

- "On a prospective Tier A live cohort of N questions, the full harness scored Brier X versus the
  registered market comparator set Y, paired edge Z, clustered 95% CI [L, U], under the registered
  endpoint and venue-stratified report."
- "The agent+market-comparator ensemble improved over comparator-only out of sample on the registered
  metric, with held-out or nested weights, paired uncertainty, and multiplicity handling."
- "The edge concentrated in high-disagreement, evidence-rich, stale/thin-market cases, either as a
  pre-registered stratum or clearly labeled exploratory analysis."
- "The harness underperformed the market in strata A/B/C, and those failures produced policy changes."

That is a credible bar for the autonomous-edge thesis.

### Allowed Forecasting-Desk Claims After A Proper Workflow Cohort

If the workflow cohort is pre-registered, intervention-labeled, and temporally scored:

- "In a prospective workflow cohort of N questions, the human+agent desk scored Brier/log score X
  versus user-alone Y, agent-alone Z, generic-chat W, and registered market comparator M under the
  registered endpoint."
- "The desk improved update quality: scheduled or randomized update-policy arm A outperformed
  first-pass/no-workflow arm B on the registered temporal score."
- "The desk produced better calibration or resolution discipline over time, and the result replicated
  in a later cohort after controlling for model, prompt, and question-mix changes."
- "Postmortem lessons produced policy changes that improved a later cohort under the registered
  counterfactual design."

Those claims support the forecasting-desk thesis. They do not imply autonomous market edge unless
the autonomous arms separately show it.

## 16. Minimum Contract For The Next Benchmark Run

The next benchmark run should not start as another probability-only batch. The minimum contract is
staged so launch gates are not confused with scoring, publication, or validated-learning gates.

### Before Collection

1. Every run declares its benchmark thesis: autonomous edge, forecasting desk, or case-study
   mechanism.
2. Every run has a timestamped pre-registration manifest and candidate-pool ledger.
3. The candidate pool records collection parameters, pagination/response boundaries, retry/rate-limit
   logs, and raw payload/page/API artifacts or registered fallback fields for admitted and rejected
   cases.
4. Every admitted question has an admission tier and admission record.
5. Market baselines store timestamp, venue, raw probability, de-vigged probability, quality fields,
   raw venue/orderbook/page artifacts, hashes, and the registered baseline method.
6. Market-hidden and market-aware arms are labeled distinctly and backed by prompt/tool/network logs,
   returned-content archives, access classification, and fail-closed contamination rules.
7. Every forecast snapshot has the actual agent rationale and links to full model-run artifacts,
   including provider response IDs, API/model revision, runtime environment hash, and tool runtime
   hash where available.
8. Evidence-rich arms require archived evidence records and availability proof before the probability
   is committed.
9. Human/agent review and interventions are recorded and public claims use autonomy labels.
10. Probability updates are append-only and tied to new evidence.

### Before Scoring Or Publication

11. Updated forecasts have matched market snapshots or are labeled against the initial market only.
12. Resolution artifacts are archived, hashed, locked before scoring, and include retrieval metadata,
    resolver source version, availability proof, and ambiguity handling.
13. Scores are paired by question and reported with registered clustered/block uncertainty.
14. Duplicates, excluded cases, ambiguous cases, and attrition are reported from the full candidate
    pool, including arm/venue/stratum/forecast-extremity breakdowns.
15. Ensemble weights are evaluated out of sample or with nested folds split by time/event/semantic
    cluster.
16. Public and restricted audit bundles are defined, with redaction manifests, hashes of public and
    restricted artifacts, and derivation links from public redactions to restricted originals.

### Before Validated-Learning Claims

17. Resolved misses generate postmortem records and policy changes.
18. A later cohort evaluates those policy changes under a counterfactual design that separates policy
    reuse from model drift, prompt changes, and question-mix changes.

If the relevant eighteen stage gates hold, the benchmark can showcase the harness for that stage. If they do
not, it is still a useful engineering test, but it should be labeled as such.

## 17. Bottom Line

The skeptical read is the right one: the current 292-question ledger is a promising live seed, not a
finished benchmark. It shows that the system can commit forecasts against open markets, subject to a
future reproducibility bundle. It does not yet show that the environment improves judgment, because
the artifacts that would show evidence, reasoning, and learning are absent.

The path forward is not to cherry-pick better-looking questions or smooth the results after the fact.
The path is to formalize the case object, admit better questions prospectively, persist the evidence
and reasoning trail, score paired against frozen market baselines, stratify the results, and turn
errors into forecast policy. That is the benchmark that can credibly demonstrate a forecasting
harness rather than a forecasting demo.
