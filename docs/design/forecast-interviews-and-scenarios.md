# Forecast interviews, assumptions, and scenarios

Status: implementation design, 18 September 2026. This document defines the full
requested feature, not a claim that the feature is shipped. Implementation progress
and acceptance evidence belong in the checklist below.

## Outcome

A forecast is a question with a defensible resolution contract, an explicit model
of what matters, and an auditable sequence of beliefs. The interface should help a
user build that structure through an adaptive interview, revisit it when evidence
changes, and compare alternative analyses without accidentally rewriting the
forecast that will be scored.

Entry points: Desk new question; Desk review selected forecast; Markets create
forecast from selected series or prediction-market outcome; News attach the
selected article to an existing forecast. All paths use the same application owner.

## Research and design implications

These are implementation recommendations informed by research, not evidence that
this particular interface improves forecasting accuracy.

- Anthropic's [AskUserQuestion reference](https://code.claude.com/docs/en/tools-reference#askuserquestion-tool-behavior)
  describes multiple-choice questions with free-text alternatives/notes. Questions
  remain open by default. Adopt the clear choice interaction, but persist answers
  independently of a model call. Never treat a timeout as a user answer. The
  [user-supplied walkthrough](https://www.atcyrus.com/stories/claude-code-ask-user-question-tool-guide)
  illustrates interview-before-specification; it is interaction inspiration, not
  forecasting validation.
- [Mellers et al., 2014](https://faculty.wharton.upenn.edu/wp-content/uploads/2015/07/2014---psychological-strategies-for-winning-a-tournament.pdf)
  report benefits from probability training and collaborative forecasting in a
  geopolitical tournament. Probability training outperformed scenario training
  in the first year. Therefore, do not equate more narrative branches with better
  judgment: include base rates, probability coherence, counterevidence and feedback.
- [SHELF](https://shelf.sites.sheffield.ac.uk/download-shelf) provides structured
  elicitation material, including discrete quantities and many quantities of
  interest. Use staged elicitation and clear definitions; an unsupported numeric
  estimate must remain visibly subjective rather than acquire a false evidence label.
- [EFSA's expert elicitation guidance](https://efsa.onlinelibrary.wiley.com/doi/10.2903/j.efsa.2014.3734)
  motivates a formal process because unaided judgments can be biased. Record the
  question, available information, reasoning and uncertainty rather than collect
  unexplained point estimates through a form.
- [Hüllermeier and Waegeman](https://arxiv.org/abs/1910.09457) distinguish uncertainty
  from incomplete knowledge and variability under a model. The distinction depends
  on the analysis. A questionnaire can expose missing knowledge, reduce ambiguity,
  or identify useful conditioning variables; it cannot promise to eliminate
  irreducible future randomness. An exact numeric epistemic/aleatoric split requires
  an identifiable model and must not be fabricated from model confidence scores.
- [Bayesian network decomposition research](https://cdn.aaai.org/ocs/5642/5642-23862-1-PB.pdf)
  treats structure elicitation, probabilities and evidence updates as separate
  steps. Model shared causes explicitly: multiplying marginal probabilities of
  correlated conditions is not an acceptable shortcut.

## Existing owners and gaps found in the code

- `forecasting/question_spec.py` already stages and validates question onboarding.
  `forecast.onboard_propose` and `forecast.onboard_commit` expose it through
  `tui_gateway/forecast_rpc.py`. Extend this path; do not create a second question API.
- `ui-tui/src/components/questionOnboardModal.tsx` is a manual step form. Replace
  its internal steps with a durable interview client, retaining manual entry and
  deterministic validation when no model is configured.
- `forecasting/models.py` has immutable question/snapshot dataclasses. Snapshots
  already carry assumption, evidence, model-run and calibration lesson references.
- `forecasting/ledger/question_meta.py` stores assumptions, reference classes and
  cruxes. Existing assumption rows are insufficient as versioned interview answers;
  retain compatibility and reference immutable revisions from each analysis run.
- `forecasting/ablation_study.py` compares panel versus solo forecasts. That is a
  methodological evaluation, not a user's conditional scenario. Keep the concepts
  and APIs distinct.
- `forecasting/jobs/` already owns durable jobs, cancellation and progress. Use it
  for interview generation and scenario runs rather than a modal-owned worker.
- News rebuilds its article list for individual feed completions and selects by
  index. This explains changing articles while the user is reading. Publication
  into the visible list must be distinct from background acquisition.

## Forecast semantics: three operations, three labels

1. **Belief revision:** update an assumption's probability or evidence-supported
   state. An unknown answer remains unknown; an unchecked box is not false.
2. **Conditional scenario:** evaluate the target assuming specified conditions.
   Label the result `P(target | conditions)` and retain the original target's
   resolution criteria. It is not the unconditional forecast.
3. **Ablation:** run the same estimation procedure without selected evidence,
   assumptions or model components. Disabling an assumption removes its use in that
   run; it does not assert its negation. Label the measured change as sensitivity
   of this procedure, not proof of causal effect or improved accuracy.

Every run freezes the baseline snapshot, assumption revisions, evidence cutoff,
source independence groups, model/provider/settings, prompt version, selected
components and seed where supported. Run the baseline and variant under matched
conditions. Nondeterministic model differences are not automatically meaningful;
show repeated-run dispersion when available and `not measured` otherwise.

Scenarios never enter calibration as ordinary forecasts. Promoting an unconditional
candidate requires an explicit review and the existing snapshot commit gates. A
conditional forecast can be separately scoreable only under a declared conditional
resolution/scoring policy, not by borrowing the parent question's outcome.

## Interview content and interaction

Use an adaptive sequence of short sections, not a giant mandatory form. Support
many questions overall, with one active question and a section/progress list. A
short route covers required settlement fields; deeper branches remain available.

| Section      | Questions and saved outputs                                                                                        |
| ------------ | ------------------------------------------------------------------------------------------------------------------ |
| Define       | Exact actor/entity, measurable event, horizon, timezone, what counts and what does not                             |
| Resolve      | Canonical source, units, observation period, first-release/revised policy, cancellation and censoring rules        |
| Outside view | Candidate reference classes, inclusion rules, sample size, base-rate uncertainty, exclusions                       |
| Drivers      | What must happen, what can prevent it, shared causes, necessary versus merely influential factors                  |
| Beliefs      | Current estimate/distribution, evidence, provenance, disputed claims, unanswered questions                         |
| Uncertainty  | Unknown present facts; future variability; measurement/revision error; disagreement between models                 |
| Challenge    | Opposite outcome, strongest counterevidence, assumption most likely to fail, falsification triggers                |
| Scenarios    | Conditions to assume, factors to exclude in an ablation, incompatible combinations                                 |
| Update plan  | Sources/feeds, triggers, decision deadline, review cadence, changes that would matter                              |
| Review       | Resolution contract, unresolved blockers, answer/evidence diffs, baseline and conditional results, explicit commit |

For binary outcomes, elicit probabilities with a plain-language frequency check.
For continuous outcomes, ask plausible bounds and quantiles, checking their order
and units. For categorical outcomes, require exhaustive/mutually exclusive labels
or an explicit residual category, and a normalized probability vector. Do not show
an agent's suggested probability before the user's first independent estimate by
default. Reveal it afterward as a comparison to reduce anchoring.

Each generated question has a stable ID, section, reason for asking, answer type,
options, optional custom answer, linked assumption IDs, applicable branches and
validation rules. The agent may propose follow-ups but cannot silently change the
meaning of an answered question. Changed meanings get new revisions.

TUI: left section list, central question with concise options, right context/diff
when width permits. At narrow widths context is an explicit tab, not squeezed
beside the question. Arrow keys select; Space toggles multi-select; Enter confirms;
Tab moves between options and free text; Esc saves and exits. Show shortcuts with
the shared hint design. Provide Back, Skip/Unknown, Save and Review. Do not advance
on merely moving the highlight. State saves before navigation succeeds.

Scenario controls: each factor has `Use baseline`, `Assume true`, `Assume false`,
`Specify distribution`, or `Exclude from analysis`, as appropriate to its type.
A separate enabled toggle controls inclusion in a named variant. Explain the
selected operation beside the result. Contradictory conditions block evaluation.
Disabling a dependency either prompts for an explicit model substitution or marks
that analysis unevaluable; it never supplies an implicit 50%.

## Example: a third presidential-term question

First disambiguate announcing a campaign, appearing on a ballot, winning an
election and taking office. Choose one measurable event and a deadline. These
are different targets; their probabilities must not share a score by accident.

Possible driver branches include intent, legal eligibility/path, health and
capacity, party support, election administration and political conditions.
Midterms, economic conditions and geopolitics may share causal links to support
and intent; do not count their coverage independently as multiple confirmations.
These are illustrative factors, not present-day legal or medical conclusions.
Ask which facts are actually known, which outcomes remain contingent, what source
would establish each, and which result would change the forecast most.

## Application and persistence contract

Create `forecasting/interviews/` for strict models, validation, orchestration and
storage integration, with a brief README. Keep UI rendering in Ink; keep persistence
and model execution in Python. Generate TypeScript from the shared protocol.

Persist interview ID, parent question/draft ID, revision, status, actor, creation
and update times, source seed, answered question revisions and unresolved branches.
Use optimistic concurrency on every answer/update. Retrying the same idempotency
key returns the previous result; conflicting data for that key fails. Never overwrite
an answer submitted by another client. Resume reconstructs state from durable storage.

Application operations: start/resume; generate next section; save answer; revise
assumption; define variant; evaluate variant; preview commit; commit. RPC, CLI and
agent tools call the same owner. Domain errors stay typed. Unknown fields, invalid
units, out-of-range probabilities, stale revisions and foreign evidence references
fail before persistence. All writes remain profile-scoped.

Generation is a cancellable durable job with a response schema and budget. Store
provider/model, evidence cutoff, input digest and status. Reject malformed responses;
preserve the user's completed answers on provider failure. Offer a retry or manual
continuation. Reconnect reattaches to the same job and current revision. A generated
recommendation is not a user-confirmed answer.

Before committing, preflight all references and requirements. Question, assumptions,
source links and baseline linkage need one atomic local transaction or a resumable,
idempotent operation with explicit partial status where existing owners cannot
share a transaction. Audit QuestionSpec's current multi-write commit before reusing
it as a claimed atomic boundary. Success cannot be reported after only its first write.

## Agent and scheduled review behavior

Expose the same interview/analysis operations to the forecasting tool. In headless
mode, the agent answers only from cited available evidence or an explicit model
estimate, recording actor `agent` and provenance. It must not impersonate the user,
invent preferences or resolution criteria, or block a cron worker awaiting input.
Unanswerable items become `needs_user`/`needs_research` tasks. Scheduled work may
collect evidence, challenge assumptions, run variants and propose an update; it
must not silently move the active probability. Existing schedule authorization
and commit rules remain authoritative.

Evidence/news are untrusted input, never instructions. Link original URL, publisher,
source timestamp when supplied, capture time, content digest and extraction status.
Do not substitute acquisition time for unknown publication time. The update draft
must distinguish new independent evidence from syndication, duplicate URLs or a
revision of the same source.

## Markets and News entry points

- Markets: use a collision-checked shortcut and matching footer action for
  `Create forecast`. A prediction-market seed contains venue/event/outcome IDs,
  exact question, close time, source URL, raw price and capture time. Price is a
  timestamped market observation, not the user's initial belief. Require the user
  to confirm settlement rules; source-market rules can differ from the desk's.
- Numeric feed: capture provider/series identity, units, cadence, revision policy
  and observation period. Ask whether the target is a threshold at a date, a future
  value, or a change over a defined interval. A row's latest value is not a forecast.
- News: `Attach to forecast` opens a searchable existing-question picker and a
  preview of the claim/source. The user chooses `Attach evidence` or `Attach and
prepare update`. Evidence linking is idempotent; model failure after attaching
  cannot duplicate the item on retry. The draft update references the interview
  and highlights affected assumptions; committing probability remains explicit.
- Background News acquisition updates the cache, not the reader's current article
  or list order. Show pending updates and an explicit apply action. Source/filter
  changes remain deliberate navigation. Preserve the selected article and scroll
  position until the user changes selection or applies updates.

## Evaluation and delivery checklist

Do not infer forecasting improvement from passing UI tests or from one attractive
scenario. Engineering correctness and predictive usefulness need separate evidence.

- [x] Inspect current owners and write a research-grounded design.
- [ ] Implement and test stable News publication independently of acquisition.
- [ ] Add strict interview/answer/assumption/variant models and migrations.
- [ ] Add durable application operations, idempotency and concurrency tests.
- [ ] Integrate adaptive structured generation with budget, cancellation and retry.
- [ ] Replace onboarding and add Desk update interview shortcut.
- [ ] Implement coherent scenario evaluation and matched ablation records.
- [ ] Add Markets-to-interview and News-to-question evidence/update flows.
- [ ] Integrate cron/tool execution with explicit unresolved-user status.
- [ ] Verify terminal layouts, keyboard collisions, reconnect/resume and failure paths.
- [ ] Run focused unit, integration and generated-contract checks, then required gates.
- [ ] Publish a reviewable implementation with current README/usage instructions.

Acceptance fixtures: ambiguous geopolitical question; monthly first-release CPI;
revised economic series; weather threshold; multi-outcome prediction market;
missing timestamp; syndication duplicates; contradictory assumptions; correlated
evidence; skipped answer; stale revision; duplicate commit; model timeout; killed
worker; reconnect; repeated refresh while reading. Test at 80x24 and a wide terminal.

Measure elicitation completion time, skip/revision rate, unresolved settlement
ambiguity, provenance completeness and recovery success. For forecasting quality,
preregister paired structured-versus-existing forecasts with the same information
cutoff and model budget, cluster by independent outcome family, and compare proper
scores only after resolution. Keep ablation sensitivity separate from demonstrated
improvement. An outcome that is not yet resolved provides no score evidence.
