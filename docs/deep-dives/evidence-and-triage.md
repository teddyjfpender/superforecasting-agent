# Evidence and Triage

Evidence is the raw material of a forecast, and the desk's discipline is that it
is **timestamped and attached, never silently folded into a number**
([forecasting-methodology.md](../forecasting-methodology.md) §2). This page is
the machinery underneath that discipline: how evidence gets in (import adapters +
watched sources), how it is kept honest (freshness/staleness, archive snapshots,
time-travel pinning), and — the newest layer — how the desk decides *what is even
worth reading* before it hoards it (the information-triage subsystem).

```
   import adapters (~58)      watched sources           web_extract
   FRED · GDELT · arXiv …     scope + role + signature  truncate-and-store
          │                          │                        │
          └───────────┬──────────────┴────────────────────────┘
                      ▼
             ┌──────────────────┐        ┌───────────────────────────┐
             │  candidate feed  │──────▶ │  TRIAGE (keep/skim/skip)  │
             └──────────────────┘        │  triage.py + label_scoring │
                      │  (kept)          └────────────┬──────────────┘
                      ▼                     contested │ trust gate (80%)
             evidence_items (ledger/evidence.py)      ▼
             available_at · snapshot · signature   operator hand-label
```

---

## Evidence lifecycle

### Import adapters

`forecasting/source_adapters.py` holds **~58 `load_*` adapters** (the
architecture overview's "~70" counts source-type aliases and resolved-case
variants) — FRED, GDELT, arXiv, SEC (filings / company-facts / full-text
search), Census, Federal Register, CourtListener, NVD, CISA-KEV, USGS, NWS,
Open-Meteo, ClinicalTrials, openFDA, PubMed, OWID, WHO-GHO, World Bank, IMF,
GitHub (repo/issues/commits/actions), PyPI/npm, Reddit/HN/Bluesky/Mastodon,
Wikipedia, and the prediction-market resolvers (Manifold/Metaculus/Kalshi/Polymarket),
among others. The tool dispatches a `source_type` string to the right loader in
`_load_source_adapter_items` (`tools/forecasting_tool.py`); the CLI's
`forecast import` / `forecast sources` reach the same adapters.

Each adapter is fetch+parse with a shared discipline:

- **Block-page detection.** `detect_block_page` scans the first ~8 KB of a
  response for Cloudflare / DataDome / PerimeterX / Imperva / cookie-wall /
  JS-required / CAPTCHA signatures disguised as HTTP 200 — so a challenge page is
  recognised as a *block*, never treated as evidence content.
- **Honest source-type prior.** `source_type_reliability_prior`
  (`forecasting/source_search.py`) gives each adapter class a reliability prior
  the ledger's scoring machinery reads.

### Watched sources — scope, role, signature

`forecasting/ledger/watches.py` is the D1 domain leaf. A watched source re-pulls
on a cadence and is defined by three axes:

- **Scope** — `WATCH_SCOPE_TYPES = {question, domain, topic, domain_topic,
  portfolio}`, validated on add. A domain-scoped watch feeds every question in
  the domain; a question-scoped watch is the tightest.
- **Role** — `WATCH_SOURCE_ROLES` types a source so the desk stops treating broad
  RSS the same as the source that actually resolves the question: `resolver`,
  `consensus`, `official_primary`, `leading_indicator`, `market_price`,
  `background_context`.
- **Signature** — `_source_signature` computes a per-type change-detection hash
  (`_rss_source_signature`, `_github_source_signature`, … one per adapter family).
  `check_watched_sources` compares the current signature against
  `last_seen_signature` and raises a **change alert** (`watched_source_changed`,
  info) or an **unavailability alert** (`watched_source_unavailable`, warning,
  when the signature starts with `missing:`) — *without touching any
  probability*. Autonomy surfaces the change; it does not silently re-forecast on
  it.

**The bulk-add incentive repair.** Adding sources one at a time is a
disincentive: a real thesis is 35 races × 7 sources, and scripting that loop
through the tool is slow enough that the agent under-watches. The
`add_watched_sources` bulk action (`tools/forecasting_tool.py`) takes an array
(capped at 400/call), with **per-row isolation** — one bad row carries its error
and can be resubmitted alone, never killing the batch. The tool description
steers the agent to *"prefer this over scripting loops"*. The point is
behavioural: make the honest thing (watch the resolver *and* the leading
indicators) cheap enough that the desk actually does it.

### Archive snapshots

`forecasting/ledger/evidence.py` `add_evidence` can archive a **point-in-time
snapshot** of the source alongside the row: `_archive_file_evidence_snapshot`
for local files, `_archive_url_evidence_snapshot` for URLs (best-effort, off by a
flag when the ~5s/row latency isn't worth it). A snapshot that hits a block page
records `blocked` + `block_reason` + `block_signal` at the top level so the desk
sees it was blocked without opening the file — the full diagnostic nests under
`source_snapshot`. The archive is what makes an old citation *checkable* later.

---

## Freshness and staleness

Evidence is stored oldest-first by `available_at` (`list_evidence`), and the
commit gate cares whether a live update is standing on stale ground. The
`require_fresh_evidence` rule (Severity **ERROR**) blocks a live re-run with a
prior that lacks freshly-collected evidence; the operator can bypass with
`acknowledge_stale_evidence`, but then a second rule fires:

- **`stale_evidence_justified` (WARN).** `_check_stale_evidence_justified`
  (`forecasting/hooks/builtins.py`) warns when a live re-run used the freshness
  bypass **without recording why**. The signal
  (`forecasting/hooks/signals.py`) sets `stale_evidence_acknowledged` true *only*
  when acknowledged with no reason — so the WARN is precisely "you skipped
  freshness and didn't say why". Recording a `stale_evidence_reason` (CLI
  `--stale-evidence-reason`) keeps the bypass auditable; the honest alternative
  is `forecast refresh <id>` to collect fresh evidence. This is the
  guide-and-make-visible pattern: the bypass is allowed, but never silent.

---

## web_extract — truncate-and-store

`tools/web_tools.py` never sends a raw page to the model. Pages at or under
`web.extract_char_limit` (default **15,000** chars) return whole; larger pages
are **head+tail truncated** for the model, while the **full clean text is stored
on disk** under `cache/web` (`_store_full_text`), capped at
`MAX_STORED_TEXT_CHARS = 2,000,000` so a pathological page can't blow up the
cache. The footer tells the reader where the full copy lives, so a paging session
(`read_file`) can reach the omitted middle without the extract ever spending that
context up front. It replaces the pre-truncate-store era's 2 MB *refusal* ceiling
with a capped *store* — the content is kept, not dropped.

---

## Time-travel source pinning (backtests)

A backtest must not let the model see the future — evidence pulled "now" for a
question that froze in 2023 would leak the answer. Two mechanisms enforce it:

- **`as_of` on the adapters.** `load_wikipedia_pages`
  (`forecasting/source_adapters.py`) takes an `as_of`: with it set, each page is
  pinned to the **newest revision whose timestamp ≤ `as_of`** via the MediaWiki
  revisions API, and `updated_at` is set to that revision's timestamp so the
  resulting evidence's `available_at` predates the cutoff. Live behaviour is
  unchanged when `as_of` is absent. Pinned by
  `tests/forecasting/test_wikipedia_as_of.py`.
- **The freeze becomes the cutoff.** In ForecastBench ingestion
  (`forecasting/forecastbench.py`) the `freeze_datetime` becomes the question's
  `as_of` / `simulated_forecast_time` / `evidence_cutoff`, and every context
  evidence row and baseline is stamped `available_at = as_of`. The closed-book
  sanitizer (`forecasting/agent_protocol.py`) then filters evidence and baselines
  to **pre-cutoff only** before the agent ever sees the case. (See the
  ForecastBench-grounding work for the market-hidden arm this protects.)

---

## The information-triage subsystem

The newest layer answers a different question than "is this evidence true?" — it
asks *"is this even worth an analyst's scarce attention?"*, **before** anything
becomes evidence. It is a faithful port of the Thinking Machines × Bridgewater
AIA study *Learning to Replicate Expert Judgment in Financial Tasks*. The port is
**data + process discipline, not the RL recipe** (see the non-fit note below).

### Three-way relevance labeling

`forecasting/triage.py` runs a cheap model over candidate readings and emits, per
candidate, one of **three** labels — not a binary relevant/irrelevant:

| label | verdict | meaning |
| --- | --- | --- |
| `relevant_interesting` | **keep** | worth the analyst's scarce attention |
| `relevant_uninteresting` | **skim** | financially real but not worth the attention (a small IPO to a macro desk) |
| `irrelevant` | **skip** | no market/macro/forecast bearing |

The **middle class is the load-bearing distinction** (the study's finding L9):
separating *interesting* from merely *relevant* is what replicates desk judgment.
The label→verdict map, tolerant aliasing (a model that phrases it slightly
differently isn't mis-bucketed), and a conservative **default to skim** (an
unknown/missing label surfaces rather than vanishing as irrelevant) all live in
`triage.py`. The model call is an **injected `TriageRunner`** — `(model, system,
user) -> str`, the same shape as the quorum runner — so tests inject a fake.

### The rubric

What counts as *interesting* is a **desk-authored rubric**, stored scoped like a
calibration lesson (`triage_rubrics` table, scope walk domain_topic → domain →
topic → question_type → global via `active_rubric_for_question`). A seeded
`DEFAULT_TRIAGE_RUBRIC` (macro-desk criteria + worked examples) is used only when
no scoped rubric exists; `set_label_rubric` overrides it. The rubric renders into
the labeler's prompt as an explicit criteria block with worked examples.

### `label_score` — classification scoring the ledger never had

The ledger scores **probabilities** (Brier / log / proper score). A triage label
is a **classification**, which needs a different scoreboard —
`forecasting/label_scoring.py` is the label analog of `score_question`: pure
functions over `(predictions, gold)` giving **accuracy, per-class + macro F1,
positive-class precision/recall/F1, a confusion matrix, and exact-match** (for
the `truncation` task family). Only ids present in *both* are scored; a gold id
with no prediction is counted `skipped` (an abstaining labeler is never silently
credited). A triage label literally could not be scored on its own terms before
this module existed.

### Contested-routing to operator hand-label

The study's highest-leverage trick (L8): route only **contested** examples to
expensive expert adjudication. `triage_contested` opens a `CONTESTED_LABEL`
alert per disputed item (verifier-disagreement, or a boundary/conflict
heuristic). It is a **manual-tier** alert kind — deliberately absent from the
automode sweep's tiers so no automated pass can resolve it. `relabel_route`
records the operator's expert label (`label_source='expert'`) and acks the linked
alert **because real work was done** — never a bare ack. In this port, **the
operator is the verifier**: expert hand-labels are the gold the labeler is
measured against.

### The 80% trust gate

`build_triage_trust_gate` scores held-out **auto-label vs expert-label** over
every adjudicated item. Until accuracy clears the **80% analog** the study's
investors required (`$FORECAST_TRIAGE_TRUST_THRESHOLD`, default 0.8) over at
least `min_sample=20` adjudicated items, the labeler stays **`suggest_only`** —
it surfaces verdicts but is *not* trusted to auto-filter. This mirrors the
`can_claim_live_superforecasting` guardrail: a flag that flips only on real
measured evidence, never by assertion. The gate is surfaced in `forecast doctor`
(`triage_gate`) and the `triage_trust` action, with a recommended-action string
for each state (no sample yet / under-sampled / below bar / cleared). Until it
clears, triage informs the human but never silently drops a reading — the same
earn-it-first stance the [honesty doctrine](estimator-honesty.md) takes toward
market numbers.

### The deliberate RL non-fit

The study's *training* recipe — Qwen3-235B / GRPO / CISPO / on-policy
distillation / Tinker — was **deliberately left unbuilt**. A frontier-orchestrating
harness has no fit for a fine-tuning loop, and faking one would be dishonest. The
port took the transferable half — the three-way label, the rubric, contested
routing, and classification scoring — and left the RL machinery on the floor.

---

## Sources

Verified against the current tree (`superforecasting-agent-snapshot`):

- `forecasting/source_adapters.py` — the `load_*` adapters, `detect_block_page`.
- `forecasting/source_search.py`, `source_planner.py` — source-type priors, candidate feed.
- `forecasting/ledger/watches.py` — scope types, roles, `_source_signature`, `check_watched_sources`.
- `forecasting/ledger/evidence.py` — `add_evidence`, `available_at`, archive snapshots.
- `tools/forecasting_tool.py` — `add_watched_sources` bulk action, `_load_source_adapter_items` dispatch.
- `forecasting/hooks/builtins.py`, `hooks/signals.py` — the `stale_evidence_reason` WARN.
- `tools/web_tools.py` — `web.extract_char_limit`, `_store_full_text`, `MAX_STORED_TEXT_CHARS`.
- `forecasting/source_adapters.py::load_wikipedia_pages`, `forecasting/forecastbench.py`, `forecasting/agent_protocol.py` — `as_of` pinning + pre-cutoff sanitizing.
- `forecasting/triage.py`, `forecasting/label_scoring.py` — three-way labeling, rubric, `score_labels`, `build_triage_trust_gate`.
- Tests: `tests/forecasting/test_triage.py`, `test_triage_contested.py`, `test_triage_trust.py`, `test_label_scoring.py`, `test_stale_evidence_reason.py`, `test_wikipedia_as_of.py`, `test_watch_gate_and_bulk.py`, `test_source_roles.py`.
