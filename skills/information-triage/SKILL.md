---
name: information-triage
description: "How to TRIAGE a stream of readings before it becomes evidence — decide what is relevant_interesting vs relevant_uninteresting vs irrelevant (keep/skim/skip) against the desk rubric, score the labeler, and route disputed auto-labels to operator hand-labeling. Invoke when a candidate stream is large, when deciding what to read/import, or whenever you are about to import many sources as evidence at once, e.g. /information-triage"
version: 1.0.0
author: Superforecasting Agent
license: MIT
platforms: [linux, macos, windows]
aliases: [information-triage, triage, relevance-labeling, what-to-read]
metadata:
  hermes:
    tags: [forecasting, triage, relevance, labeling, evidence, filtering, superforecasting]
    category: forecasting
    related_skills: [ledger-interaction, forecasting-loop, research]
---

# Information triage — read the signal, not the firehose

A forecasting desk drowns in candidate readings (news, reports, market items,
watched-source hits). Importing every one as evidence buries the signal and
templates your research. The triage layer (after Thinking Machines / Bridgewater
AIA, *Learning to Replicate Expert Judgment in Financial Tasks*) makes the small,
repeated "is this worth reading?" judgment explicit, scoreable, and improvable.

The load-bearing reframe: **relevant is not the same as interesting.** A small IPO
is financially *relevant* but *uninteresting* to a macro desk. So labels are
three-way, each mapping to a reading verdict:

| label | verdict | meaning |
|-------|---------|---------|
| `relevant_interesting`   | keep | broad significance — worth your scarce attention |
| `relevant_uninteresting` | skim | real but narrow / already-priced |
| `irrelevant`             | skip | no bearing on markets, macro, or any desk forecast |

## The flow (all through the `forecast_ledger` tool — never a script)

1. **Set the desk taste once** (what counts as *interesting* HERE). Stored scoped
   like a calibration lesson; the labeler retrieves the most-specific active rubric
   per question (domain_topic → domain → topic → question_type → global):
   `set_label_rubric { scope_type, scope_ref?, rubric:{interesting_criteria (required),
   uninteresting_criteria?, irrelevant_criteria?, examples?:[{title,label,why}]} }`.
   If you set none, a sensible macro-desk default is used. List with
   `list_label_rubrics`.

2. **Triage the candidates** before importing anything:
   `triage_label { candidates:[{title, summary?, source_type?, source?, url?}] | use_watched:true + question_id, rubric_ref?, model? }`.
   Returns one verdict per candidate (label / keep-skim-skip / relevance /
   materiality / rationale, `label_source='auto'`) and persists them as staging
   rows. **Import only the keep/skim readings** as evidence (`import_source_evidence`);
   drop the skips. Point the cheap labeler at a small model via `$FORECAST_TRIAGE_MODEL`.

3. **Route what you dispute to operator review** (the contested-routing trick — only
   the *disputed* labels cost expensive judgment):
   `triage_contested { question_id | label_ids, verifier_labels?, disagreement_threshold? }`.
   With `verifier_labels` (a second opinion), items where the verifier disagrees with
   the auto-label are flagged; without it, the labeler's boundary/conflict cases are.
   Each contested item opens a **MANUAL `contested_label` alert** — surfaced for a
   human, never auto-resolved by the automode.

4. **Hand-label the contested items** (operator):
   `relabel_route { adjudications:[{label_id, label}] | label_id + label }`. Records
   the expert label (`label_source='expert'`), and acknowledges the linked alert
   *because the real work was done* — never a bare ack.

5. **Check whether the labeler has earned trust**:
   `triage_trust { threshold?, min_sample? }` (also in `forecast doctor` →
   `triage_gate`). It scores the auto-label against your expert adjudications. Until
   accuracy clears the bar (default 80%) over enough adjudicated items, the labeler is
   `suggest_only` — surface verdicts, never auto-filter.

## Score a labeling task on its own terms

The ledger scores *probabilities* (Brier/log). A label is a *classification* — score
it with `label_score { predictions:[{id,label}], gold:[{id,label}], task_type:
'relevance'|'truncation', positive_class? }` → accuracy / positive-class F1 /
exact-match / confusion / macro-F1.

## Discipline

- Triage is **pre-ingest filtering**, not evidence. Only import the material readings.
- The three-way label and the contested-routing trick are general; the *rubric content*
  (what's interesting to THIS desk) and the *trust threshold* are yours to author — see
  `set_label_rubric` and `$FORECAST_TRIAGE_TRUST_THRESHOLD`.
- Never bare-acknowledge a `contested_label` alert — close it only via `relabel_route`
  with a real expert label. (See [[ledger-interaction]].)
