# Live lifecycle recovery and learning measurement

PRs #30 and #31 were merged on September 10, 2026. This follow-up exercises the
actual instance through the public CLI and fixes shared ledger behavior exposed
by that work. No active forecast probabilities were changed.

## Live operations

The operator made consistent SQLite backups of both the forecast ledger and
session store, checked their integrity, and saved a private hash manifest before
mutation. Recovery completed 96 previously missing score/postmortem handoffs.
Two confirmed outcomes have no historical forecast: they remain explicitly
unscoreable work items with append-only review notes. Creating forecasts after
seeing those outcomes would manufacture performance evidence.

Settlement review was restricted to 12 questions. Six were resolved from official
sources: five archived first-release BLS reports and one certified election vote
vector. Six were reviewed and deferred: two year-long baskets whose outcome
horizon has not arrived, two elections pending retrieval of certified statewide
vectors, one right-censored flight-time outcome, and one question lacking an
unambiguous external market identity. Review notes record findings, inspected
sources, and suggested revisit times. A revisit timestamp does not schedule a job.
Private question IDs, source extracts, corrections and review notes remain in the
instance and its private verification files, not this public repository.

## Shared boundary fixes

- Resolution validation runs before database writes, source archival or scheduler
  teardown. Numeric CLI strings become finite numeric outcomes. Vote-share JSON
  becomes an object; malformed JSON, duplicate labels, nonnumeric values,
  booleans, nonfinite values, negative shares and mismatched vectors are rejected.
- Share scoring requires matching complete labels. Forecast totals distinguish
  fractions from percentages; resolved shares are explicitly percentage values.
  Totals allow 0.5 percentage points of rounding. Partial overlap no longer
  silently creates a deceptively good score. The existing vector accuracy metric
  is explicitly excluded from the proper-loss learning comparison.
- Sparse-CDF CRPS now integrates error over outcome distance. The previous
  unweighted sum depended on arbitrary threshold count and ignored units.
  `crps_piecewise_linear_cdf_v2` uses linear interpolation, with remaining tail
  mass at endpoint thresholds; this finite-support approximation is explicit,
  not inferred Gaussian tail behavior. `crps_discrete_pmf_v2` integrates the
  finite PMF exactly. Gaussian scoring also recognizes `standard_deviation`.
- The integral follows Tilmann Gneiting and Adrian E. Raftery, *Strictly Proper
  Scoring Rules, Prediction, and Estimation* (2007), equation 20, in loss
  orientation: [original paper](https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf).
  Regression references include the independent expectation identity for a PMF,
  analytic uniform and normal distributions, unit scaling and out-of-support
  observations.
- Score migration retains original scores, appends corrections, invalidates
  derived learning, and creates replacement postmortems. The five newly settled
  BLS questions were corrected this way. A subsequent reviewed migration fixed
  15 additional existing numeric scores without adding resolutions or forecasts;
  another preview found zero scores requiring migration. The command
  `forecast scoreboard backfill-crps` remains read-only unless `--apply` is passed.
- Settlement attention uses the declared resolution time, falling back to close
  time only when absent. A forecast submission cutoff is not an outcome date.

## Lesson reconciliation

Ten competing weather lessons are explicitly superseded, retaining their full
history and source references. One consolidated daily-maximum-temperature lesson
states applicability conditions and separates pre-maximum, uncertain-peak,
post-maximum and official-report reasoning. Station identity and measurement
honesty remain separate active guidance. No universal confidence cap is inferred
from a small cluster of correlated station-day outcomes.

The shared lesson evaluator accepts outcome-type, topic and metadata conditions.
Unknown facts do not satisfy conditions. Conditional advice is visible in agent
context and `forecast lessons explain`, but its rules are not enforced until the
required facts are recorded. Those facts are asserted metadata, not independently
verified weather observations. Each new snapshot freezes lesson text, conditions,
source score/postmortem references and the actual decision. Editing a lesson later
cannot rewrite that snapshot's provenance.

## What the measurement establishes

`forecast lessons effectiveness --json` selects the earliest eligible live
snapshot *durably stored* before both forecast close and confirmed resolution,
one per question. It does not select the latest or best-scoring update. It checks
source-score timing and invalidation, excludes invalidated/quarantined scores,
and computes otherwise-unscored selected snapshots read-only. Legacy CRPS is
recomputed under the corrected convention for this diagnostic, without rewriting
historical records. Cohorts separate domain, score rule and units.

The report distinguishes lesson references, recorded decisions, source lineage,
self-reported mechanical probability adjustments and subsequent forecast updates.
Historical snapshots do not acquire invented application records. Distinct
questions are not automatically statistically independent: shared station-days,
news events and outcome sources can still cluster them.

**Learning benefit is not established.** Later weather updates improved scores,
but observation of the daily maximum is new information, not proof that a lesson
improved reasoning. There are no usable recorded raw/adjusted probability pairs
in the inspected live sample. Application coverage and historical cohort means
cannot identify the counterfactual forecast without lessons.

The next valid accuracy experiment should be specified before outcomes arrive:

1. Use the existing live question cohort; randomize at an event/source cluster
   level where questions are correlated. Keep a frozen lesson-enabled arm and a
   no-lesson arm, including removal of learned error-profile advice in control.
2. Match model, tool budget, evidence packet and evidence cutoff. Save both runs
   as separate evaluation artifacts, never silently change the live probability.
3. Freeze assignment, lesson versions, source lineage, scoring convention and
   exclusion rules. Record failure/missing-output rates as well as accuracy;
   never select only successful or favorable questions after resolution.
4. Compare paired proper losses after independently verified outcomes. Report
   uncertainty by event cluster and split horizon/weather phase. No minimum
   sample count alone guarantees power; size the trial against a predeclared
   practically meaningful improvement.

That prospective outcome evidence requires time. This deployment provides an
honest audit and enforceable provenance; it does not claim a completed causal
trial or a demonstrated accuracy gain.

## Forecast Desk

The existing Ink desk now exposes lifecycle attention and executable shared CLI
recovery actions, plus an outcome-backed learning evidence panel. It separates
recoverable score/postmortem work from missing forecasts and failed tasks, and
separates recorded decisions from historical unverified references. Question
inspection links to lesson conditions and provenance. The dashboard continues to
embed this same TUI; no second transcript or composer was added.

The concise review and learning views keep their findings in the viewport instead
of repeating the full book. The shared report pager counts wrapped visual lines
for both display and keyboard navigation, including after terminal resize; long
reports no longer overflow the screen because of logical-line pagination.

See the companion verification JSON for final test and deployment evidence.
