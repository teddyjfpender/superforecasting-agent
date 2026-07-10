# Modularization Program — the second carve, plus the formalities

**Date:** 2026-07-10 · **Branch:** `superforecasting-agent-snapshot`
**Successor to:** `docs/plans/2026-07-03-architecture-delivery-plan.md` (Arc D and its coda are
the precedent this program extends; nothing here contradicts that plan — it finishes it and
adds the formality layer it deferred).

**The operator's ask (verbatim intent):** "there's a lot of code here and you could modularise
it far better to improve maintainability, formalities, and the ability to integrate new
features more easily."

**The method:** research first (live probes, real numbers), then phased **moves-only** waves
under the CONTRIBUTING laws that already govern this repo — the Moves-only refactor slices law,
the size rules, the 1,200-line `MOVES-ONLY` gate in `.githooks/lib/checks.sh`, the difflib
"0 unexpected added lines" verification, full suite green before AND after every slice, the
~0.1s import-time budget held. Arc D proved this method on an 18,562-line megafile with zero
caller changes; this program applies it to what Arc D staged and what it never targeted, and
adds the missing formalities (layer contracts in CI, blame preservation, extension-point
checklists, an ownership map).

**Git rule for the planning/execution agents:** never `git add` / `git mv` / `git commit` —
staging is a human decision (the CONTRIBUTING "No staging by agents or scripts" law).

---

# PART I — THE HONEST MAP (live-probed 2026-07-10)

## 1. Size census

Every non-test, non-generated source file ≥ ~2,800 lines, with fork-era traffic
(non-merge commits touching the file since the 2026-05-20 fork point; pre-carve history
attributed to the file's successor). "Upstream-shared" = a file the value-harvesting fork
ports upstream PRs into (`docs/upstream-sync.md`); carving those raises the cost of every
future harvest.

### Python

| File | Lines | Fork-era edits | Ownership | Status |
|---|---:|---:|---|---|
| `gateway/run.py` | 18,452 | 35 (mostly ports) | upstream-shared | **cold — do not carve** |
| `forecasting/cli/core.py` | 17,056 | 157 (as `cli.py`) + 18 | fork-owned | **Arc D staged 8 domains — unfinished** |
| `cli.py` | 14,956 | 49 | upstream-shared | cold in fork terms — do not carve |
| `hermes_cli/main.py` | 13,784 | 49 | upstream-shared | do not carve |
| `forecasting/ledger/core.py` | 12,647 | 137 (as `ledger.py`) + 22 | fork-owned | **Arc D named the next leaves; core has re-grown +784 since the coda's 11,863** |
| `forecasting/source_adapters.py` | 10,193 | 35 | fork-owned | never carved; natural per-source seam |
| `tui_gateway/server.py` | 9,618 | **88** | fork-owned | 83 `@rpc_validated` handlers in one module; `jobs_rpc`/`pm_rpc`/`market_rpc` siblings prove the seam |
| `hermes_cli/auth.py` | 7,163 | 20 | upstream-shared | do not carve |
| `hermes_cli/kanban_db.py` | 6,300 | ~0 | upstream-shared, surface the fork doesn't run | do not touch |
| `hermes_cli/config.py` | 6,006 | 57 | upstream-shared but fork-hot | **exception case — see Wave 4 note; default: leave** |
| `gateway/platforms/*` (discord 5,699 · telegram 5,656 · feishu 5,058 · yuanbao 4,872 · base 3,812) | — | low | upstream-shared, mostly unused by the fork | do not touch |
| `hermes_cli/gateway.py` | 5,605 | 24 | upstream-shared | leave |
| `agent/auxiliary_client.py` | 5,461 | low fork-era | upstream-shared | leave |
| `run_agent.py` | 4,444 (`AIAgent` = **191 methods**, lines 346–4,228) | 14 fork-era (521 total since Apr, mostly ports) | upstream-shared | Wave 4, cost-gated |
| `agent/conversation_loop.py` | 4,256 | 14 | upstream-shared | Wave 4, cost-gated |
| `tools/browser_tool.py` / `tools/mcp_tool.py` | 3,867 / 3,777 | low | upstream-shared | leave |
| `hermes_cli/setup.py` | 3,622 | low | upstream-shared | leave |
| `forecasting/quorum.py` | 3,131 | 18 + the entire BLF/Delphi/blind-reconcile arc landed here | fork-owned | **hottest feature area; never carved** |
| `tools/forecasting_tool.py` | 2,897 | 98 | fork-owned | already a façade (Arc D); stable |
| `forecasting/dashboard.py` | 2,877 | 52 | fork-owned | never carved |

Test megafiles exist too (`tests/forecasting/test_cli.py` 15,963; `test_ledger.py` 6,617;
`test_tui_gateway_server.py` 6,107) — they mirror the source megafiles and split naturally
*after* each source carve (test moves are cheap and monkeypatch-safe once the façade exists);
they are not first-class slices here.

### TypeScript (ui-tui / superforecaster-terminal)

| File | Lines | Fork-era edits | Status |
|---|---:|---:|---|
| `ui-tui/src/components/deskView.tsx` | 3,579 | 40 | **owned by the in-progress desk-redesign arc — this program stays out** |
| `ui-tui/src/components/forecastsWorkspace.tsx` | 3,522 | 35 | Wave 3 candidate |
| `ui-tui/src/protocol/generated.ts` | 3,172 | generated | exempt by definition |
| `ui-tui/src/app/forecastPanel.ts` | 2,071 | **75** | Wave 3 — hottest TS file per line |
| `superforecaster-terminal/src/providers.tsx` etc. | 3,317 | low | separate web surface; out of scope |
| `ui-tui/src/app/slash/commands/core.ts` | 1,590 | 40 | Wave 3 |
| `ui-tui/src/components/appLayout.tsx` | 1,163 | 61 | hot but small; watch, don't carve |
| `ui-tui/src/gatewayTypes.ts` | **326 (residual)** | 51 | **Arc A residue — still imported by 10+ files; finish the migration, delete it** |

## 2. Traffic, and the pain × traffic ranking

Fork-era edit frequency (non-merge, since 2026-05-20, tests excluded) — the top of the list
IS the forecasting desk: `forecasting/cli` lineage 175, `forecasting/ledger` lineage 159,
`tools/forecasting_tool.py` 98, `tui_gateway/server.py` 88, `forecastPanel.ts` 75,
`appLayout.tsx` 61, `hermes_cli/config.py` 57, `dashboard.py` 52, `gatewayTypes.ts` 51,
`forecasting/protocol.py` 43, `slash/commands/core.ts` 40, `source_adapters.py` 35.

**Priority = pain (lines, mixed concerns) × traffic (fork-era edits), fork-owned first:**

1. **`forecasting/cli/core.py`** — biggest fork-owned file AND highest fork-era churn; the
   seam is proven and Arc D explicitly staged the remaining 8 domains. Zero design risk.
2. **`tui_gateway/server.py`** — 9.6k × 88 edits; the registry (`@rpc_validated`, protocol
   models) and three carved siblings already exist; this is a family-per-module move.
3. **`forecasting/ledger/core.py`** — 12.6k and re-growing; Arc D named the exact next leaves.
4. **`forecasting/quorum.py`** — smaller (3.1k) but the single hottest *feature* surface
   (Delphi, BLF, blind-reconcile, connected panels all landed here in three weeks).
5. **`forecasting/dashboard.py`** — 2.9k × 52 edits.
6. **ui-tui forecast layer** — `forecastPanel.ts` (75 edits), `gatewayTypes.ts` deletion
   (Arc A's declared done-state), `slash/commands/core.ts`.
7. **`forecasting/source_adapters.py`** — 10.2k but moderate traffic; registry-shaped.
8. **`run_agent.py` `AIAgent` / `agent/conversation_loop.py`** — big, but upstream-shared and
   fork-cold (14 edits each); carving them taxes every future upstream harvest. Cost-gated.

## 3. The Arc-D precedent — what worked, what's left

**What worked (the reusable method, verbatim from the delivery-plan findings ledger):**
- Package-with-façade replaces the module; `__init__` installs a monkeypatch-forwarding
  `ModuleType` subclass (`__setattr__`/`__delattr__` → core; the CLI also needed
  `__getattr__` read-forwarding). **No test or caller ever changed across D1–D9 + 2 layer-out
  carves.**
- AST `end_lineno` extents (decorator-aware) + tokenize NAME-pass rewrites (never regex) +
  a difflib categorizer asserting every added façade line is a delegate/import — **0
  unexpected lines on every slice**.
- Membership = caller-exclusivity, never adjacency; module-object monkeypatch grep (both
  string and `import … as` forms) before every slice; constants-to-the-leaf rules; the
  `_core.`/`_ledger`/`_ft` call-time-hop discipline for patched names.
- Gates every slice: full domain suite green before/after, `--collect-only` 0 import errors,
  import-time ≤ ~0.1s, ruff PLW1514/F821, ≤1,200 moved lines.

**What Arc D left undone (its own words, plus what the probes show today):**
- **CLI:** 8 staged domains never carved — questions/show/update · refresh/rerun/cycle ·
  reviews/schedule · quorum/panel · markets/pm · triage/calibration/lessons ·
  doctor/backup/config · benchmarks/backtest. Since the coda three *new* domains landed the
  right way (`curate`, `slack_admin`, `connect_admin` — the register-hook works for new
  code), but core still holds **155 `_cmd_*` handlers** and a ~3k-line `register_cli`, and
  has **grown** 15,992 → 17,056.
- **Ledger:** the scoring-adjacent leaves D9 deliberately deferred — resolutions,
  corrections, postmortems, error-profiles, calibration-lesson CRUD,
  baseline/backtest/model scoring, autopilot, market-models, ingest, forecast-links,
  reference-classes, assumptions, cruxes, desk-state, analyst-notes. Core target was <2k;
  it sits at 12,647 and re-grew +784 since the coda.
- **Arc A residue:** `ui-tui/src/gatewayTypes.ts` (326 lines) still exists and is imported by
  10+ files; Arc A's declared done-state was its deletion.
- **The carve tooling itself is not in the repo.** The AST-extent/tokenize/difflib scripts
  that made D1–D9 mechanical lived in session scratch ("the carve tooling ports verbatim" —
  but there is nothing to port from except transcripts). That is a program risk.

## 4. Coupling hotspots (measured)

**Function-level (lazy) imports:** **2,100** across `forecasting/`, `tools/`, `tui_gateway/`,
`agent/` alone. Some are deliberate (the import-time budget; the documented lazy
`ACTIONS` edge in `tools/forecast_actions/__init__.py`), but the count is also the census of
cycle workarounds — every one is an edge invisible to a reader of the import block.

**Cross-package edges (AST-counted, both directions shown where bidirectional):**

| Edge | Count | Reverse | Verdict |
|---|---:|---:|---|
| `hermes_cli → agent` | 134 | 105 | fully bidirectional — no layer exists |
| `gateway → hermes_cli` | 110 | 42 | bidirectional |
| `gateway → tools` | 95 | 61 | bidirectional |
| `tools → hermes_cli` | 84 | 83 | perfectly symmetric — the worst signal in the graph |
| `tools → forecasting` | 75 | 23 | bidirectional; `forecasting → tools` should be ~0 |
| `tui_gateway → forecasting` | 90 | **0** | correct direction, already clean — **enforceable today** |
| `forecasting → hermes_cli` | 39 | 4 | mostly config/auth reads; a ratchet target |
| `agent → run_agent` | 11 | — | **inverted: the library imports the entry script** (plus gateway 6, forecasting 4, tui_gateway 2, tools 1, hermes_cli 1 — 25 total) |
| `* → protocol` | 12 (tui_gateway 8, forecasting 4) | **0** | `protocol/` imports nothing above itself (AST-verified) — the one perfect layer; enforce it before it decays |

**Most-imported modules** (the de-facto kernel): `hermes_cli.config` **318**,
`hermes_cli.auth` 135, `forecasting.ledger` 93, `tools.registry` 66,
`forecasting.source_adapters` 63, `forecasting.models` 60, `agent.auxiliary_client` 45.
`hermes_cli.config` at 318 importers and 6,006 lines is the single highest-leverage
formality target in the repo — but it is upstream-shared (see Wave 4 note).

**Where a new feature touches too many files today (the seam audit):**

| Extension point | Files touched today | Why |
|---|---|---|
| New gate rule | **1** (`forecasting/hooks/builtins.py`: rule + remediation text) + tests | `BUILTIN_RULES` registry — **the model to copy** |
| New CLI verb, carved domain | **1** module (+1 hook-call line first time) | register-hook proven (`jobs approve`, `curate`, `slack_admin`) |
| New CLI verb, uncarved domain | **1 edit inside a 17,056-line file** (handler + registration ~14k lines apart) | the Wave-1 pain |
| New tool action | **2** (`tools/forecast_actions/<domain>.py` HANDLERS + the static `FORECAST_LEDGER_SCHEMA` dict in the 2,897-line façade) | schema not composed from registrations |
| New TUI-visible RPC | **4–5** (`protocol/rpc/<family>.py` → regen → handler *inside 9,618-line server.py* → ui-tui call site → sometimes `gatewayTypes.ts` residue) | server not family-split; Arc A residue |
| New quorum behavior | 2–4, all inside `quorum.py`'s mixed concerns (prompts + parsing + panel-resolution + cost-estimation in one module) + `quorum_jobs.py` + CLI + tool | no leaves |
| New ledger table/domain | edit inside 12,647-line `core.py` (migrations + methods) + gate list | core carve unfinished |

## 5. Formality gaps

- **No layer contracts anywhere.** Nothing in `pyproject.toml` or CI names an allowed import
  direction; the bidirectional table above is the consequence.
- **`__all__` on 143 of 420 py files (34%)** in the runtime packages; public-vs-private is
  ambiguous everywhere a façade doesn't exist. (The façades themselves are disciplined —
  `forecasting/ledger/__init__`, `forecasting/cli/__init__`, `tools/forecast_actions/__init__`.)
- **No `.git-blame-ignore-revs`** — for a repo whose refactor law is moves-only slices, this
  is the missing half of the bargain: every carve currently costs `git blame` archaeology.
- **Registries that work** (copy these): hooks `BUILTIN_RULES` (+ DSL user rules via
  `loader.py`), `tools/forecast_actions.ACTIONS` (HANDLERS-per-domain), `protocol/rpc/*`
  pydantic families + codegen staleness gate, `@rpc_validated` (83 handlers / 30 families),
  the CLI `register(forecast_sub)` hook, `forecasting/jobs` types.
- **Still hand-wired:** the 83 validated handlers all *live in one module* despite the
  registry; `FORECAST_LEDGER_SCHEMA` is a static dict in the tool façade; the CLI's
  `register_cli` is still a ~3k-line monolith calling 5 domain hooks and inlining the rest;
  `gatewayTypes.ts` hand-written residue.
- **The carve tooling is unversioned** (see §3).

---

# PART II — THE PROGRAM

Five waves. Waves 1–3 are pure moves-only continuations of the proven method on fork-owned
hot surfaces. Wave 0 is the formality layer (no moves — it makes every later wave cheaper
and every future feature safer). Wave 4 is the honest, cost-gated treatment of the
upstream-shared monoliths. Cadence: **one slice per work session, alongside feature work**
(the Arc-D cadence that demonstrably worked); a wave is a bookkeeping unit, not a freeze.

## The per-slice template (every slice in every wave fills this in)

- **Target map (before → after):** exact file/module list with expected line counts.
- **Façade contract:** every name that stays importable at its current path, verbatim; the
  monkeypatch surface (string-form AND module-object-form greps run and recorded).
- **Mechanical verification:** full domain suite green before AND after · difflib categorizer
  0 unexpected added façade lines · `--collect-only` 0 import errors · import-time held
  (≤ ~0.1s for `import forecasting.cli`) · ruff PLW1514/F821 · ≤1,200 moved lines or split ·
  commit body carries `MOVES-ONLY` when the hook demands it · byte-identical output gates
  where they exist (CLI `--help` tree, tool schema dump, wire JSON).
- **New-feature story:** "adding an X today touches N files/megafiles; after, M."
- **Findings note:** appended to this doc (the Arc-D findings-ledger discipline — the
  coupling patterns discovered become the next slice's advice).

---

## WAVE 0 — Formalities (1–2 sessions, no code moves)

**W0.1 — Layer contracts in CI: `import-linter`.**
*Tooling choice:* **import-linter** (grimp-based). Rationale over `tach`: contract types
(`layers`, `forbidden`, `independence`) map 1:1 onto the rules below; config lives in
`pyproject.toml`; it is exit-code gated (the repo's exit-code law); grimp's AST scan sees
**function-level imports too**, so the 2,100 lazy edges are visible to contracts rather than
laundered — which is exactly the honesty this repo wants. `tach` is faster but younger, and
its module-boundary model would fight the deliberate lazy-import seams (the
`forecast_actions` cycle-breaker is a *feature* here, to be allowlisted by name, not hidden).

Contracts, in enforcement order:
1. **Enforce now (already true):** `protocol` imports only `protocol` (12 cross-package
   inbound, 0 outbound above itself — AST-verified). `forecasting → tui_gateway` forbidden (0 today). `forecasting.ledger →
   forecasting.cli` forbidden. Independence of `forecasting/ledger/` leaves and of
   `tools/forecast_actions/` domain modules (leaf↔leaf edges only via façade/core).
2. **Ratchet (true-ish; freeze the current violation list as `ignore_imports`, no new ones):**
   `* → run_agent` forbidden (25 frozen violations — the inverted edge; each removal is a
   one-line "hoist to `agent/`" fix, burn down opportunistically). `forecasting →
   hermes_cli` (39 frozen — mostly config/auth reads; the burn-down is W0.5's kernel seam).
   `forecasting → tools` (23 frozen).
3. **Aspirational (documented, not enforced):** the full layer stack
   `entry (run_agent, cli) → surfaces (gateway, tui_gateway, hermes_cli-cli) → tools → agent
   → forecasting → protocol/kernel`. The hermes_cli↔agent↔tools↔gateway tangle
   (134/105, 84/83, 95/61) is upstream-shared code; enforcing there means diverging from
   upstream for formality's sake — record it, don't fight it.
CI wiring: a `lint-architecture` step in `.github/workflows/lint.yml`, plus
`scripts/install-hooks.sh` mention. Start in observe mode for one week of sessions, then flip
to fail. **Deliverable includes the contract file and the frozen-allowlist counts in this doc.**

**W0.2 — `.git-blame-ignore-revs`.** Create it; backfill the Arc-D slice commits
(`7c4dac300`, `6be447523`, `51adb4161`, `4302d016b`, `1ecfcc6a8`, `00922498b`, `d6dc66021`,
`8ce9630d9` — verify each is moves-only before listing); every future `MOVES-ONLY` commit
appends its hash in the same PR. `scripts/install-hooks.sh` sets
`git config blame.ignoreRevsFile .git-blame-ignore-revs`. This is the blame-preservation
strategy for the whole program: **moves-only + ignore-revs ≈ blame flows through the carve.**

**W0.3 — Version the carve tooling.** Recreate the Arc-D scripts as
`scripts/carve/` (`extract.py` — AST `end_lineno` decorator-aware extents + tokenize
NAME-pass receiver rewrite; `verify.py` — the difflib added-line categorizer + monkeypatch
grep in both forms + import-time probe; `README.md` — the findings-ledger rules from §3).
Without this, every wave re-derives the tooling from transcripts. ~300 lines total, tested
against a synthetic module.

**W0.4 — The ownership map + extension checklists.** Extend `docs/architecture.md` with:
(a) the module ownership table (each top-level package: layer, owner-arc, public façade,
"do-not-import" list); (b) a **new-feature checklist per extension point** — gate rule, tool
action, CLI verb, RPC+event, TUI lens, ledger domain, quorum behavior, source adapter — each
naming the ONE module to touch and the registry it registers into. CONTRIBUTING gets a
one-line pointer. (The checklists are written from the "after" column of §4's table and
updated as waves land.)

**W0.5 — `__all__` discipline, scoped.** Rule (CONTRIBUTING + ruff config): every package
`__init__.py` and every *new* module declares `__all__`; existing leaf modules are ratcheted
as waves touch them — **no mass retro-fit** (churn without review value). Enable ruff's
`PLC0414`/`F401` only on `forecasting/`, `tools/forecast_actions/`, `protocol/`,
`tui_gateway/` (the fork-owned packages), preserving Arc D's deliberate
"surface-parity-by-non-pruning" re-exports via per-file ignores where the façades need them.

## WAVE 1 — Finish the CLI assembler (the staged 8, ~6–8 sessions)

The highest pain × traffic item, with the seam already proven on 5 domains. One domain per
slice, in blast-radius order (smallest/freshest tests first):

| Slice | Domain module (new) | Moves | Notes |
|---|---|---|---|
| 1.1 | `forecasting/cli/doctor_admin.py` | doctor/backup/config handlers + registration | smallest; re-proves the pattern post-coda |
| 1.2 | `forecasting/cli/reviews.py` | reviews/schedule (6 `_cmd_schedule*` + review handlers) | |
| 1.3 | `forecasting/cli/quorum_panel.py` | quorum/panel (5 `_cmd_panel*` + quorum verbs) | coordinates with Wave-3 quorum carve — CLI side first |
| 1.4 | `forecasting/cli/markets_pm.py` | markets/pm (5 `_cmd_market*` + pm verbs) | |
| 1.5 | `forecasting/cli/triage_calibration.py` | triage/calibration/lessons (6+5 handlers) | |
| 1.6 | `forecasting/cli/benchmarks.py` | benchmarks/backtest | **the `load_*`/`_load_backtest_cases` monkeypatch cluster lives here — the coda explicitly flagged the `_core.`-hop; run the module-object grep** |
| 1.7 | `forecasting/cli/questions_admin.py` | questions/show/update | large; split if >1,200 |
| 1.8 | `forecasting/cli/refresh_cycle.py` | refresh/rerun/cycle (autopilot-adjacent, 8 `_cmd_autopilot*`) | touches the `_ledger` patch surface heavily |

**Façade contract (all slices):** `forecasting/cli/__init__`'s `_CliPackage`
`__getattr__`/`__setattr__` forwarding unchanged; every carved `_cmd_*` re-bound at core's
bottom (the thesis-slice rule); `_ledger` reached via the 1-line local call-time hop;
`--help` tree byte-identical (all ~254 nodes, re-baselined only when a slice intentionally
adds none). **Done-state:** `core.py` ≤ ~4,000 lines = the assembler (`register_cli` reduced
to ordered `register()` calls), the shared helper web, and the patched-name kernel.
**New-feature story:** a new forecast CLI verb goes from "edit inside 17k lines, handler and
registration 14k lines apart" to "one ≤400-line domain module."

## WAVE 2 — The server family-split + the ledger's second carve (~7–9 sessions)

**W2.a — `tui_gateway/server.py` → family modules (3–4 slices).**
The pattern already exists three times (`jobs_rpc.py`, `pm_rpc.py`, `market_rpc.py`). Carve
the 83 `@rpc_validated` handlers by protocol family, largest-cohesive first:
`forecast_rpc.py` (the forecast.* family — the biggest and hottest), `session_rpc.py`,
`config_theme_rpc.py`, `agents_subagent_rpc.py`, leaving `server.py` = transport + dispatch
+ `_SlashWorker` + the validated-decorator machinery (~3–4k lines).
*Façade contract:* RPC names and wire JSON byte-identical (the `rpc_validated` validate-only
semantics make this checkable: capture a request/response corpus per family before/after);
`tests/test_tui_gateway_server.py` (6,107 lines) untouched per slice — module-object
monkeypatch grep against `tui_gateway.server` attrs is **mandatory** (same trap as the tool
carve). *New-feature story:* a new RPC = protocol model + a handler in a ≤1k family module
(+ regen), never a 9.6k-line edit.

**W2.b — `forecasting/ledger/core.py`: the named leaves (4–5 slices).**
Exactly the clusters Arc D staged, grouped to ≤1,200 lines each:
(1) `resolutions.py` (resolutions + corrections + postmortems);
(2) `lessons.py` (calibration-lesson CRUD + error-profiles);
(3) `model_scoring.py` (baseline/backtest/model scoring);
(4) `market_models.py` (market-models + ingest);
(5) `question_meta.py` (forecast-links + reference-classes + assumptions + cruxes +
desk-state + analyst-notes).
All D1–D9 rules apply verbatim (monkeypatch-forwarding façade already installed; the gate
leaf exists; membership by caller-exclusivity with the decoy-grep). *Done-state:* core ≤ ~5k
= connection, migrations, `initialize_schema`, the numeric primitives, `_score_forecast_payload`
— the permanent substrate the coda defined. (<2k was the plan's aspiration; ~5k is the honest
target after measuring the substrate.) *New-feature story:* a new ledger domain = one leaf +
one migration entry, reviewed in isolation.

## WAVE 3 — The hot domain engines + the TUI forecast layer (~6–8 sessions)

**W3.a — `forecasting/quorum.py` → `forecasting/quorum/` package (2–3 slices).**
The 3,131-line module has four separable concerns visible in its symbol map:
`prompts.py` (build_panelist/reconcile/judge/delphi prompt builders, ~600 ln),
`parsing.py` (parse_panelist/judge + the `_opt_*`/`_coerce_*`/belief-trajectory cluster,
~700 ln), `panels.py` (resolve_models/connected/configured panel + provider reachability,
~800 ln), `estimation.py` (call-count/cost estimation + preset caps), with
`quorum/__init__.py` the D1-style monkeypatch-forwarding façade re-exporting
`ModelForecast`/`JudgeSynthesis`/`QuorumResult` and every name `quorum_jobs.py`, the CLI,
and the tool import today. This is the slice that most directly serves "integrate new
features more easily" — the next Delphi/BLF iteration lands in one leaf.

**W3.b — `forecasting/dashboard.py`** → section modules behind a `build_dashboard` façade
(1–2 slices; carve by dashboard section, the same caller-exclusivity test).

**W3.c — `forecasting/source_adapters.py`** (10,193 ln) → `forecasting/sources/` package:
one module per source family + an `ADAPTERS` registry dict (the `forecast_actions` pattern);
the ~40 `load_*` names stay importable at `forecasting.source_adapters.<name>` via the
monkeypatch-forwarding façade — **this is the single largest patched surface in the test
suite; the both-forms grep is the gate.** *New-feature story:* a new data source = one module
registering into `ADAPTERS`, not an append to a 10k-line file.

**W3.d — ui-tui forecast layer (2 slices, coordinated with the desk-redesign arc):**
(1) Finish Arc A: migrate the 10+ residual `gatewayTypes.ts` importers to
`src/protocol/generated.ts` types and **delete `gatewayTypes.ts`** (326 lines; the wire-drift
gate already guards the direction). (2) Split `forecastPanel.ts` (2,071 ln, 127 fns, 75
edits) into `app/forecast/` (panel-section builders per lens; pure functions, already
test-covered by `forecastPanel.test.ts`). **Explicitly out of scope: `deskView.tsx` /
`forecastsWorkspace.tsx`** — owned by the in-progress desk-redesign arc; this program does
not open a second front on the same files. `slash/commands/core.ts` (1,590 ln, 40 edits)
splits by command family into the existing `slash/commands/` directory if and when the
desk-redesign arc doesn't claim it first.

## WAVE 4 — The upstream-shared monoliths (cost-gated; default = DON'T)

The honest analysis: `run_agent.py` (`AIAgent`, 191 methods), `agent/conversation_loop.py`,
`hermes_cli/config.py`, `gateway/run.py`, `cli.py`, `hermes_cli/main.py` are where upstream
PRs land. The fork ports *logic, not diffs* (`docs/upstream-sync.md`), so a carve doesn't
break ports mechanically — but it does make every future agent-scope port slower: the porter
must map upstream's one-file diff onto our N-file layout, forever. Fork-era traffic says the
pain isn't here (14 edits each vs 157/88 on the forecasting side).

**The gate:** carve an upstream-shared file only when BOTH (a) its fork-era non-port edit
count over the trailing month exceeds ~15, and (b) a named feature is blocked by its shape.
Until then:
- **`run_agent.py`:** one *bounded* slice only, if the gate trips — extract the fork-owned
  integration clusters (forecasting/identity/quorum touchpoints) into `agent/forecast_bridge.py`
  via delegate methods, leaving the upstream-shaped body intact. Fix the 25 inverted
  `* → run_agent` imports regardless (W0.1 ratchet — hoist the imported names into `agent/`;
  that is a tiny, port-neutral move).
- **`hermes_cli/config.py`** (318 importers, fork-hot at 57 edits): the exception candidate.
  If the gate trips, the move is *interface-first, not carve-first*: introduce
  `forecasting/appconfig.py` (already exists) as the only config surface `forecasting/` may
  import (an import-linter contract), so upstream's file keeps its shape while the fork stops
  coupling to it. 
- **Everything else in the upstream-shared list: leave.** Cold + shared = the worst possible
  carve ROI, and the megafile pain is amortized by never reading them.

---

# COST / RISK — the honest ledger

- **Moves-only churn is real cost:** each slice is a large diff a human must stage and a
  reviewer must trust. The mitigations are exactly Arc D's: the difflib gate makes "trust"
  mechanical (0 unexpected lines is checkable, not vibes), `MOVES-ONLY` markers make intent
  auditable, W0.2 makes blame survive, W0.3 makes each slice ~1 session not ~3. Review cost
  per slice observed in Arc D: minutes, not hours, *because* of the gate.
- **The monkeypatch surface is the recurring trap** (both string and module-object forms —
  it bit D1 and the tool carve). Every slice's grep is non-negotiable; W3.c
  (`source_adapters`, the largest patched surface) is sequenced after 10+ slices of practice.
- **Import-time is a measured asset (~0.083–0.1s):** every slice probes it; the lazy-import
  seams that protect it are named in the import-linter allowlist, not "cleaned up."
- **Collision risk:** the desk-redesign arc owns `deskView.tsx`/`forecastsWorkspace.tsx`;
  Wave 3.d defers to it. Wave 1.3 (CLI quorum verbs) lands before W3.a (quorum package) so
  the CLI carve never chases a moving façade.
- **Upstream-harvest interference is the reason Wave 4 defaults to no-touch.** The
  counterfactual cost of carving `run_agent.py` is paid on every monthly audit forever.
- **What could invalidate priorities:** if the multiplayer/Slack arc shifts traffic toward
  `gateway/` or the desk-redesign arc rewrites `forecastPanel.ts` wholesale, re-run the
  frequency probe (one command, recorded in §2) and re-rank — the method survives re-ranking.

# DONE-STATE (the program's definition of finished)

- No fork-owned source file over ~5k lines except by documented exception; `cli/core.py` ≤4k,
  `ledger/core.py` ≤5k, `server.py` ≤4k, `quorum/` + `sources/` + `dashboard/` packaged.
- `gatewayTypes.ts` deleted (Arc A closed).
- import-linter green in CI with the §W0.1 contracts; frozen allowlists only ever shrink.
- `.git-blame-ignore-revs` current; `scripts/carve/` versioned; ownership map + per-extension
  checklists live in `docs/architecture.md`; every extension point in §4's table at its
  "after" number — gate rule 1 file, tool action 1–2, CLI verb 1, RPC 2 small + regen,
  source adapter 1, ledger domain 1 leaf.
- Every slice's findings note appended below (the findings ledger starts empty on purpose).

---

# FINDINGS LEDGER (append per slice, Arc-D style)

*(empty — first slice appends here)*
