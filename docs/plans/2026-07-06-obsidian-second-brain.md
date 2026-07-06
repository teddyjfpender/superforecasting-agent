# Design: Obsidian Second Brain — Human-Agent Collaboration With Deep Pruning

**Date:** 2026-07-06
**Status:** P1 implemented; P2/P3 designed, deferred
**Pattern source:** ar9av/obsidian-wiki (Karpathy's "LLM Wiki" as an agent
framework: ingest→pull→merge→schema, concept pages with provenance
frontmatter + wikilinks, a delta-tracking manifest, wiki skills)
**Primary files:** `plugins/obsidian/{wiki,manifest,ingest,prune}.py`,
`forecasting/jobs/types/wiki_prune.py`, `plugins/obsidian/tools.py`,
`forecasting/cli/core.py` (doctor)

## Goal

Turn the Obsidian vault from a one-way publishing target
(`obsidian_sync_learnings`) into a SECOND BRAIN for human-agent
collaboration on the forecast desk:

1. the agent publishes a wikilinked concept-page graph of everything it
   knows (questions, lessons, theses, cruxes, postmortems, entities);
2. the operator annotates those pages in Obsidian; the agent detects the
   deltas and ingests them AS EVIDENCE — through the triage trust gate,
   never around it;
3. a PRUNING doctrine keeps the vault dense instead of rotting — the edge
   over obsidian-wiki, which only grows.

Direction of trust is unchanged: **the ledger DB is the source of truth;
the vault is a view plus an operator inbox.** Vault content never mutates
ledger state directly — it can only become *evidence*, staged through the
same triage machinery any other reading passes.

## Non-Goals

- No RL / fine-tuning of the triage labeler (deliberate non-fit, per the
  information-triage subsystem decision).
- No auto-application of prune proposals without operator confirm or an
  explicit policy grant.
- No writes to any vault other than the resolved one
  (`OBSIDIAN_VAULT_PATH` or the managed `<home>/docs/vault`); tests use
  scratch vaults exclusively.
- `sync_learnings` keeps its exact behaviour (back-compat); the enriched
  sync is a superset alongside it.
- No new Python dependencies.

## The vault schema (concept pages for the forecast domain)

Everything lives under `Forecasting/` in the vault. One page = one
concept, generated content inside the existing managed markers
(`<!-- superforecasting:begin/end -->`) so operator annotations above and
below survive every re-sync.

| Section | Page | Concept |
|---|---|---|
| `Questions/` | `<title-slug>-<id6>.md` | question dossier: forecast, criteria, rationale, analyst-note timeline, **cruxes**, related forecasts (forecast_links), thesis membership, domain lessons |
| `Lessons/` | `lesson-<scope>-<id6>.md` | calibration lesson: distilled opinion, scope, confidence, evidence refs |
| `Theses/` | `<title-slug>-<id6>.md` | thesis/macro view: health snapshot, member questions (wikilinked), entities (wikilinked) |
| `Cruxes/` | `<variable-slug>-<id6>.md` | decisive variable: materiality, evidence status, preferred source roles, back to its question |
| `Postmortems/` | `pm-<title-slug>-<id6>.md` | resolution retrospective: what happened/was expected, errors, lesson link |
| `Entities/` | `<name-slug>.md` | named entity (org / race / polling house / ticker) aggregated across theses; P1 sources them from `thesis_entities`, P2 widens the taxonomy |
| `Archive/` | mirrors sections | full former content of tombstoned pages (auditability) |
| — | `Forecast Desk Index.md` | entry point, links every section |
| — | `.sync-manifest.json` | the delta manifest (dotfile — invisible to Obsidian) |

**Frontmatter contract** (every generated page): `summary`, `provenance`
(`ledger:<kind>:<id>` for agent pages; operator pages have none),
`as_of`, `ledger_refs` (list), `status`, plus `question_id` where the
page maps to a question (the ingest router key) and type tags
(`forecasting/question`, `forecasting/thesis`, …). Frontmatter stays at
byte 0 and outside the managed block (Obsidian requirement), so it is
written on first publish and refreshed only by full-page rewrites
(tombstoning).

## The two-way collaboration loop

### Ledger → vault: `sync_wiki` (enriched, beyond `sync_learnings`)

`plugins/obsidian/wiki.py::sync_wiki(vault, db=…)` publishes all six
sections plus the index, splicing managed blocks so operator edits
survive, then records every published page in the manifest. Tombstoned
pages are never resurrected by a sync (the tombstone frontmatter is the
skip signal). Surfaced as the `obsidian_wiki_sync` tool.

### The delta manifest (the watch-signature pattern, applied to pages)

`plugins/obsidian/manifest.py` keeps, per tracked page, the same
compare-signatures shape as `watched_sources.last_seen_signature`:

```json
"Forecasting/Questions/foo-abc123.md": {
  "content_sha": "…", "managed_sha": "…", "operator_sha": "…",
  "mtime": 1751830000.0, "synced_at": "…", "provenance": "ledger:question:fq_…",
  "ledger_refs": ["fq_…"], "ingested_operator_sha": "…"
}
```

`operator_sha` hashes exactly the text OUTSIDE the managed block and
frontmatter — the operator-authored layer. `compute_deltas` classifies
every page: `operator_edited` (operator_sha moved), `operator_created`
(untracked .md in a section dir), `missing` (tracked page gone),
`unchanged`. `ingested_operator_sha` is the high-water mark so the same
note is never ingested twice.

### Vault → agent: operator notes as triage-gated evidence

`plugins/obsidian/ingest.py::ingest_operator_notes` (tool:
`obsidian_ingest_notes`):

1. collect operator deltas from the manifest; route each to its question
   via the page's `question_id` frontmatter (pages with no question
   mapping are *reported*, never guessed);
2. run the deltas through `forecasting.triage.triage_candidates` with
   the question's active rubric (runner injected — tests use a fake,
   the tool wires the real cheap-model caller);
3. persist the verdicts as `triage_labels` staging rows (always — the
   contested-routing and trust-gate machinery see every call);
4. read `build_triage_trust_gate`: in `suggest_only` mode a skip-labeled
   note is NOT imported but is *surfaced* in the report
   (`needs_review`), never silently dropped; in trusted `auto` mode
   skips are filtered (still staged + reported);
5. keep/skim verdicts land via `ledger.add_evidence` with:
   - provenance `operator-note:<vault-relative-page>` (in `source_name`
     and `metadata.provenance`),
   - `source_type="operator_note"`,
   - the page's REAL modified time as `published_at`/`available_at`
     (the epistemic timestamp backtests and hedging care about;
     `captured_at` stays ledger-capture time by schema contract — the
     mtime additionally rides `metadata.page_modified_at`),
   - `archive_url_snapshot=False` (there is no URL; the page is local);
6. bump `ingested_operator_sha` in the manifest.

No gate is bypassed: evidence enters through `add_evidence` (leak-domain
choke point and all), triage enters through `record_triage_labels`, and
the trust gate decides filter authority exactly as it does for watched
sources.

### Retrieval-before-forecast: `obsidian_wiki_query`

A tool action that, given a `question_id` (or free-text query), returns
the question's page plus one hop of its wikilink neighbourhood — cruxes,
lessons (reference classes), theses, entities — bounded (≤8 pages, per-
page truncation). This is the "@vault" analog: the agent pulls the
second brain's context before forecasting instead of re-deriving it.

## The pruning doctrine (our edge over obsidian-wiki)

Context rot is the failure mode of every append-only wiki. The prune
pass (`plugins/obsidian/prune.py`) detects seven rot classes and emits a
PROPOSAL report — **dry-run is the default; nothing mutates until an
operator confirms or the policy matrix grants it.**

| Class | Detection | P1 apply? |
|---|---|---|
| `broken_links` | wikilink resolves to no page | report-only |
| `orphans` | no in/out links (index, archive, tombstones excluded) | report-only |
| `stale` | frontmatter `as_of` older than `stale_days` (default 45) on a non-resolved page | report-only |
| `near_duplicates` | identical name/digit-stripped skeleton (the `detect_templated_batches` fingerprint) within a section, ≥25 words | apply opt-in (`classes=[…,"near_duplicates"]`): keep the oldest, tombstone the rest |
| `resolution_condensation` | page's ledger question is resolved/closed → fold into the lesson/postmortem and archive | **applied by default on confirm**: tombstone with `superseded_by` the lesson/postmortem page |
| `contradictions` | page frontmatter vs LEDGER TRUTH: status drift, provenance pointing at a missing ledger row | report-only |
| `oversized` | page over the byte budget (default 16 KB) → re-distillation candidate | report-only (LLM re-distill is P2) |

Plus the **section budget**: per-section page-count budgets with an
honest overflow report (`{count, budget, over_by}`) — never a silent
trim.

**Tombstones, never deletions.** `apply_prune` copies the full page into
`Forecasting/Archive/<section>/`, then rewrites the original as a
tombstone: frontmatter `status: tombstone`, `tombstoned_at`, `reason`,
`superseded_by`, `archive`, and a two-line body wikilinking both. Files
are never unlinked; `sync_wiki` never resurrects a tombstone; re-apply
is idempotent.

### WIKI_PRUNE on the jobs runtime

`forecasting/jobs/types/wiki_prune.py` registers the `wiki_prune`
JobType (spend_class `free`, no alias family, lazy plugin import inside
`execute` so the forecasting→plugins layer boundary holds at import
time). Phases `scan → propose → apply?/done`.

- **Dry-run (default):** builds the report and surfaces it as an
  `alert_events` proposal (`reason="wiki_prune_proposal"`, recommended
  action names the confirm step) — the same seam resolution proposals
  ride, so the alerts view and doctor already show it.
- **Apply (`spec.apply=true`):** authorizes through the policy matrix —
  `ctx.authorize(ActionClass.LEDGER_WRITES, "wiki prune apply …")` (vault
  tombstones + the prune alert ride the ledger-writes cell). Interactive
  runs proceed (the operator invoked it = operator confirm); a cron/cycle
  run obeys `FORECAST_POLICY_<MODE>_LEDGER_WRITES` — `ask` parks the job
  `awaiting_approval` on the standard approval seam, `auto` is the
  policy-matrix grant. `apply` must always be explicit in the spec.

### Doctor: vault health

`forecast doctor` gains a fail-safe, read-only `vault_health` section
(`plugins/obsidian/prune.py::build_vault_health`): pages by section,
orphans, broken links, stale count, tombstones, budget state, and the
manifest's pending operator-edit count — the same probe the alert
surface reads.

## Phasing

**P1 (this change — shipped):**
- vault schema + enriched `sync_wiki` (questions incl. cruxes/links,
  lessons, theses, cruxes, postmortems, entities, index), managed-marker
  preservation, tombstone-skip;
- delta manifest (`manifest.py`) + `compute_deltas`;
- triage-gated operator-note ingestion (`ingest.py`) with
  `operator-note:<page>` provenance + real mtime timestamps;
- prune pass: all seven rot classes + section budgets → proposal report;
  apply with tombstones for `resolution_condensation` (default) and
  `near_duplicates` (opt-in); `WIKI_PRUNE` job type (dry-run default,
  alert proposal, policy-gated apply);
- tools: `obsidian_wiki_sync`, `obsidian_wiki_query`,
  `obsidian_ingest_notes`; doctor `vault_health` section.

**P2 (deferred):**
- entity taxonomy beyond `thesis_entities` (races / orgs / polling
  houses as first-class pages with their own ledger backing) + decision
  records;
- LLM re-distillation apply path for `oversized` and `stale` pages (a
  paid job tier — needs the LLM_SPEND cell);
- cross-linker (suggest missing wikilinks) + agent-history mining
  (harvest session transcripts into concept pages);
- `obsidian` CLI subcommands (`wiki-sync`, `prune --dry-run/--apply`)
  and a cron preset for a weekly dry-run prune;
- contested-routing UX for operator notes the labeler and operator
  disagree on (rides the existing `triage_contested` alerts).

**P3 (deferred):**
- trust-gate-graduated AUTO ingestion at scale (only after the labeler
  clears the 80% bar on adjudicated operator notes specifically);
- @vault routing in chat surfaces (mention a page, get it injected);
- vault-side wiki-lint enforcement hooks (the forecast-hooks pattern
  applied to page schema);
- multi-vault / collab sharing of concept pages (rides the ShareClass
  policy axis).

## Test plan (all on scratch vaults + scratch ledgers — never the operator's)

`tests/plugins/test_obsidian_wiki.py`: sync round-trip with operator-edit
survival across re-syncs; frontmatter contract; manifest delta detection
(edited / created / missing / unchanged); triage-gated ingestion (fake
runner; provenance + mtime timestamps; staging rows; suggest-only skip
surfaced not imported; ingest high-water mark; dry-run inert);
wiki-query neighbourhood; prune proposals per rot class; tombstone
semantics (archive copy, never deleted, idempotent, sync never
resurrects); vault health.

`tests/test_jobs_wiki_prune_type.py`: registration; spec validation;
dry-run job proposes + alerts + mutates nothing; apply job tombstones +
logs the policy decision; a cron-mode apply under
`FORECAST_POLICY_CRON_LEDGER_WRITES=ask` parks `awaiting_approval`.
