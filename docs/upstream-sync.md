# Upstream sync — harvesting value from `hermes-agent`

This fork (**Superforecasting Agent**) is a CLI-first forecasting desk forked from
[`NousResearch/hermes-agent`](https://github.com/NousResearch/hermes-agent) at
`edb2d910` (PR #28814, 2026-05-20). Upstream iterates fast (≈900 commits in the
first ~3 weeks after the fork). This doc is the **operating model + ledger** for
continuously pulling upstream's cross-cutting improvements into the fork without
taking on a merge burden.

## Operating model

**1. Never `git merge` upstream.** We've diverged structurally — rebrand,
`forecasting/`, the Ink forecasts workspace, the agent runtime. A merge would be
a conflict swamp and would drag in the whole Nous-account / web-dashboard /
kanban / chat-adapter surface we deliberately don't run. Stay a *value-harvesting*
fork, not a *tracking* fork.

**2. Run the audit on a cadence (monthly, or before touching a subsystem).**
Two reusable passes:

- **Classify** — profile `git log <audit-head>..origin/main` (the *incremental*
  delta since the last audit — see the Ledger's "Audit head" marker; use the
  `merge-base` only for a from-scratch re-audit) by conventional-commit type, scope,
  and diff size; keep only the fork-relevant scopes (`gateway`, `cli`, `tui`,
  `agent`, `codex`, `mcp`, `skills`, `security`, `file-safety`, `prompt`, `patch`).
  Drop web/kanban/docker/dashboard-auth/Nous-portal/chat-adapter/xAI/image-gen —
  ~70% of churn, zero forecasting payoff. **When the audit finishes, bump the audit
  head to the new `origin/main` tip.**
- **Assess against our tree** — for each candidate PR, read the *actual diff*,
  check how diverged our copy of the touched files is, and decide
  bring / adapt / skip / investigate / **already-have**. Verify claims against the
  working tree, never the commit message alone.

**3. Port PR-by-PR, logic-not-diff, one commit per PR.** `git cherry-pick` mostly
conflicts against our divergence. Instead: read the diff → understand our local
shape → port the *intent* → adapt tests → commit with the upstream `(#NNNNN)` in
the message. The trailer trail is what makes the next audit incremental.

**4. Watch prerequisite chains.** Upstream PRs build on each other. Before porting
a "bonus," run `git merge-base --is-ancestor <older> <newer>` to see if it's already
subsumed, or whether it sits on a foundation we lack. Two real examples this round:
`#00bd24e2` was already absorbed by `#32269`; `c6a992e3` turned out to depend on
`#28660`, which we were missing entirely (and which was itself a real credential
leak — see ledger).

**5. Security is "port on sight."** Security / file-safety fixes are universal,
low-conflict, and the highest-regret to miss. Make them a standing category; let
features be opportunistic.

**6. Keep this ledger current.** Every port commit names its `(#NNNNN)`. Recording
ported / deferred-why / skipped-why here turns each audit into a diff against the
last one instead of a from-scratch re-read.

## Tooling

- Curate candidates: rank `feat/perf/refactor` + core-scope `fix` PRs by churn and
  scope (see the session's `rank_prs.py` / `rank_fixes.py` approach — profile by
  type/scope/size, filter to fork-relevant scopes).
- Assess in parallel: a multi-agent workflow where each agent reads real diffs for
  a themed batch and returns structured `{verdict, value, effort, conflict_risk,
  rationale}`, then a synthesis pass produces the prioritized plan. (Run via the
  `Workflow` tool; inline the batch list in the script — `args` binding proved
  unreliable for large payloads.)

## Ledger

`merge-base = edb2d910` (fork point, PR #28814, 2026-05-20)
· **audit head = `d62979a6f` (reviewed-through; origin/main tip at 2026-06-12)**
· last audit: 2026-06-12 (delta `ea6eaabd8..d62979a6f`: 1,409 commits — ~230
fork-relevant, ~1,100 desktop/chat-adapter/Nous-deprecation/image-gen churn,
~79 chore/metadata; 9 ported, 1 deferred chain, 1 skipped-absent).

### Audit head — the incremental-review high-water mark

`audit head` is the upstream commit we have **scanned through** (classify + assess
over the fork-relevant scopes). It is NOT the merge-base and NOT a commit we merged —
it's a bookmark so the *next* audit only looks at what's new. Advance it every audit.

Remotes in this checkout: `origin` = upstream `NousResearch/hermes-agent`,
`fork` = `teddyjfpender/superforecasting-agent` (where we push the snapshot branch).

**Next audit starts here — review only commits after the audit head:**

```sh
git fetch origin
git log --oneline d62979a6f..origin/main          # everything new since this audit
git log --oneline d62979a6f..origin/main | wc -l  # how many new commits
```

Then re-run the classify → assess passes on that delta only (not the full
`edb2d910..origin/main`, which is 986 commits as of this audit), make
bring/adapt/skip decisions, port, and **bump the audit head to the new
`origin/main` tip** in this line when done. The merge-base never changes; only the
audit head moves.

> **Useful fact for agent-runtime ports:** our fork *retained* upstream's
> `run_agent.py` (the `AIAgent` class) and the `tests/run_agent/` harness
> (`object.__new__(AIAgent)` bare-construction, used by ~90 tests) alongside the
> `superforecasting_agent.cli → forecasting.cli` entry. So upstream `agent/*` and
> `tests/run_agent/*` changes mostly port *faithfully* (not just in spirit) — the
> Wave-3 error-recovery PRs landed their integration tests verbatim. `run_agent.py`
> forwards `run_conversation` to `agent.conversation_loop.run_conversation`.

### Ported (committed on `superforecasting-agent-snapshot`)

| Upstream | What | Commit |
|---|---|---|
| #97e975ed | Widen read-deny: `.env`/`mcp-tokens/`/webhook secrets/root (home+profile root) + `read_file_tool` relative-path bypass fix | `45b2b669` |
| #ba3c4509 | Block project-local `.env*` reads by basename | `16f47442` |
| #32269 | Promptware defense: `tools/threat_patterns.py` + memory load-time snapshot scan + `<untrusted_tool_result>` delimiters; context-file scanner routed through it | `58a9a5bf` |
| #2e509422 | Hash gateway pairing codes (salted SHA-256 + constant-time compare) | `b76baf43` |
| #7ab16773 | `security audit` — on-demand OSV.dev supply-chain scan (venv + plugins + MCP) | `e4f3181f` |
| #28660 | Gate `OPENAI_API_KEY`/`OPENROUTER_API_KEY` to authoritative hosts (was leaking to any custom endpoint) — found via the c6a992e3 investigation | `1b844400` |
| #32273 | Patch reliability: indentation preservation (`fuzzy_match.py` re-indent), CRLF preservation (`file_operations.py` detect + normalize), per-file failure escalation after 3 retries (`file_tools.py`) | `a1b834aa` |
| #33733 | Region-gated `\t`/`\r` unescape on `new_string` across all match strategies (complements, not replaces, our `\'`/`\"` escape-drift guard) | `80bd20b7` |
| #30259 | Recover from providers rejecting list-type tool content: `multimodal_tool_content_unsupported` failover reason + strip-image-parts retry + per-session no-list cache | `9e3897ac` |
| #33883 | Classify provider content-policy/safety blocks as non-retryable `content_policy_blocked` → fall back immediately instead of burning retries; provider-safety guidance + clear `final_response` | `89593786` |
| #33816 | Buffer retry/fallback/compression status chatter; surface only on terminal failure (silent on transient recovery). 4 buffer helpers + ~43 call-site conversions across loop/chat/stream | `cb9af80d` |
| #33816 (fix-beyond-upstream) | Close a status-buffer leak **upstream still has**: the lone clear sat only on the final-text success path, so a hiccup recovered via a tool-call iteration (intra-turn) or a non-flushing break exit (cross-turn, long-lived session) leaked stale chatter onto a later unrelated terminal flush. Added a turn-start backstop clear + a tool-call-success clear; regression guards in `test_status_buffer_clear_invariants.py`. Found by an adversarial buffering-invariant audit. | _this wave_ |
| #33042 | **Codex rewrite (Wave 2 centerpiece).** Drop the SDK `responses.stream()` helper; consume `responses.create(stream=True)` events directly via a shared `_consume_codex_event_stream` — structurally immune to chatgpt.com `output=null` backend drift. Retires our `except TypeError` hand-patch + the prelude/postlude fallbacks; collapses `run_codex_create_stream_fallback` to a thin alias; subsumes #43a3f119. A behavior-preservation audit confirmed 0 lost behaviors. codex_runtime ported verbatim (2 comment rebrands) + auxiliary_client + 4 test files migrated | `dfe7b1ce` |
| #2d422720 | Payload-shape-aware context estimator (`estimate_request_context_tokens`) so Codex turns trip the stale tiers; forward `request_timeout_seconds` through the Codex path (transport + adapter); lower non-stream stale defaults (base 300→90, tiers 600→240/450→150) | `c55e2c0b` |
| #8601c4d4 / #283bb810 | TTFB + stream-idle watchdogs for stalled Codex streams in `interruptible_api_call` (kill+reconnect on no-first-byte / first-byte-then-silence); large-request prefill tolerance (disable-above-tokens, cap, scaled idle floors). All knobs via `*_CODEX_*` aliases | `6705d2a9` |
| #fc47b7285 | Omit `tools` key from Codex Responses kwargs when no tools registered (was sending `tools=None` → SDK `_make_tools` `TypeError` before any HTTP request) | `716bd485` |
| #9514ddbee + c6a992e3 | **Closed a LIVE credential leak** — `_resolve_named_custom_runtime` forwarded OPENAI/OPENROUTER keys to ANY custom host (e.g. DeepSeek) ungated in both candidate lists; gated to authoritative hosts + added lookalike-resistant `_host_derived_api_key` vendor fallback. Found via scouting. | `098b45c1` |
| #aa283d1e4 + #40fcb9658 | Credential isolation: re-key model picker custom-provider grouping by (api_url, credential_identity, api_mode) so same-host env-keyed providers don't collapse/misroute; `set_runtime_main` records base_url/api_key/api_mode for aux routing | `4926dda6` |
| #912e6e227 | TUI: suppress mouse-residue scrollback leaks during launcher startup (env-guard honors `*_TUI`/`*_TUI_NO_EARLY_DISABLE` alias triples) | `72cfcacf` |
| #c42edd805 | TUI: fix linux/wayland clipboard copy (`resolveOnExit` in `execFileNoThrow` so daemonizing wl-copy/xclip/xsel settle on child exit, not stdio drain); kept our rebranded debug branches; `StdioOptions` annotation for newer node types | `cc4fee8e` |
| #3a9bc9d88 | Model picker: unify /model + CLI lists, add credential-fingerprinted disk cache (cache path auto-rebrands via `get_hermes_home`; only the digest is persisted) + `--refresh` | `e98c91e0` |
| **Security batch (14 commits, triaged 2026-05-30 → ported)** | | |
| #b7b8bec80 | Block `/proc/*/{environ,cmdline,maps}` from `read_file` (was leaking the agent's own provider keys) | `76c50c84` |
| #4694524de | Write-deny `.anthropic_oauth.json` (home+root) — read-deny already had it; closes the write-clobber half | `5c4849a5` |
| #95b5b7240+#6bebab476 | Block AWS Bedrock bearer token from subprocess env (narrow end-state; general AWS chain stays inheritable) | `9494cf52` |
| #dcc163ee2 | Redact credentials before session-log persistence (content, tool args, system_prompt; multimodal-aware) | `c7f890cb` |
| #2e181602a | Isolate credential pool on provider fallback (no cross-provider corruption / base_url leak) | `55d9deb0` |
| #d7c5d5dee | Don't persist borrowed credential secrets to auth.json (new `credential_persistence.py`; owned-source allowlist verified, `hermes_pkce` kept) | `671913da` |
| #1a9ef8314 | Require `API_SERVER_KEY` for every API-server bind (incl. loopback) | `0497`…→`api_server` commit |
| #43abc51f6 | Require source-CIDR allowlisting for public msgraph webhook binds; close fail-open | `267a01ef` |
| #243ebc7a6 | Atomic private (0600) writes for dashboard OAuth credentials | (web_server commit) |
| #30928f945 | Dashboard plugin-asset suffix allowlist + loader-hijack env denylist (alias-aware rebrand) | `0cd98da6` |
| #44df52005 | Guard `Path.home()` PermissionError in `has_direct_modal_credentials` | `6c9b96ce` |
| #79fc92e9c | `.env` 0600 perms at doctor/profiles/setup creation sites | `0497e401` |
| #ec4d6f182+#9c77a0c3c | Masked typing feedback for CLI + plugin secret prompts (`secret_prompt.py`) | `d2337199` |
| **2026-06-12 wave (audit `ea6eaabd8..d62979a6f`)** | | |
| #621bf3a87 | **Security:** strip backslash-escapes (`r\m`) and empty-quote splits (`r''m`) in the shell-denylist normalizer; fail-closed (not silent-pass) when `tools.approval` can't import in the TUI gateway | `5895ca3d8` |
| #9b78f411c / #35684 | **Security:** neutralize bare file paths in the mutation-verifier footer (backtick-wrap + `_neutralize_footer_paths`) so gateway `extract_local_files()` can't auto-attach denied-write credential paths to messaging channels | `df0a91aa9` |
| #434c684bf | Focus automatic context compression on recent user turns (prevents stale-task drift) | `9223825c1` |
| #286ecd26d / #14665 | Strip MEDIA directives from compressor summarizer input | `35b37f33e` |
| #b2d151abe | Strip `default` from `$ref` nodes in tool schemas (unblocks Fireworks-hosted Kimi) | `0ec877881` |
| #e7ae145ac | Gateway: guide the agent to extract PDF/DOCX text instead of punting on binary attachments | `c2fe2277f` |
| #9f95f72b9 | Strip `api_messages` in thinking-signature recovery so the retry actually omits thinking blocks (our shallow `msg.copy()` made the bug live) | `81fdcfb84` |
| #86e10dd87 | Route "thinking blocks cannot be modified" 400s to recovery | `428cc4f27` |
| #f456f302d / #44267 | Refuse to write service definitions with a temp-dir agent home (regex matches all 3 home-alias env names) | `481ef8529` |
| #782681f90 | Atomic private (0600) writes for google_chat OAuth credentials | `302500df` |

### Already-have (subsumed; do not port)

- **#00bd24e2** (expand memory threat patterns) — ancestor of #32269, which
  consolidated every pattern + all 17 invisible chars into `threat_patterns.py`.
- **#43a3f119** (recover codex streams with null output) — now *subsumed* by the
  ported #33042 rewrite (`dfe7b1ce`): the event-driven consumer never reads the
  terminal frame's `output`, so null-output recovery is structural. Our old
  `except TypeError` hand-patch was retired with the rewrite. Do not port
  separately.

### Deferred (valuable; needs a focused pass or a prerequisite)

- **Compressor SUMMARY_PREFIX modernization chain** — port as ONE unit,
  oldest-first: `020601d41` → `42bbd221e` (#35344, `_HISTORICAL_SUMMARY_PREFIXES`
  + renormalization) → `d5e2fbf24` (frame compaction handoff as historical
  context) → `8f8cad7ec` (strengthen compression preamble) → `acb2954d8` (freeze
  carveout-era prefix). Together they replace our fork-point-era "resume exactly"
  SUMMARY_PREFIX — a known stale-task-hijack vector upstream — with
  latest-message-wins framing. Attempted 2026-06-12; the two tail commits are
  unportable without the #35344 foundation, so take the whole chain in a focused
  pass.

### Skip (off-target for a forecasting CLI/TUI fork)

- **Nous-deprecation refactors** (#41ff6e59 disable legacy session key, a22c2500
  remove `min_key_ttl`, 95cf8f98 drop JWT-shape fallback): the Nous stack is woven
  through ~18 files but **inert without a Nous account**. Upstream is deleting it;
  excising it from our fork is high-risk / low-value. Leave it.
- **Termux startup-perf PRs** (#a3beee47 etc.): they reorganize the 15k-line root
  `cli.py` / `hermes_cli.main`; our `forecast`/`superforecast` entry uses a
  separate shim (`superforecasting_agent.cli` → `forecasting.cli`), so the diffs
  don't apply. The *principle* (lazy-load OpenAI SDK / toolsets behind the paths
  that need them; a `--version` fast-path — `forecast --version` still costs ~1s of
  eager imports) is worth a **fork-native** optimization task, not a port.
- Whole categories: web dashboard, kanban, docker/s6 supervision, dashboard-auth /
  Nous OAuth / portal / "Nous-approved" entitlement catalogs, chat-platform adapter
  migrations (Discord/Mattermost/Telegram/Feishu/QQ/Matrix/ntfy/honcho), xAI
  OAuth/migration (deadline passed), Bitwarden secret-source system, image-gen.

### Next-audit candidates worth a look (not yet assessed in depth)

- **~16 other in-range `fix(security)` commits — TRIAGED + PORTED 2026-05-30.**
  14 ported (see the security-batch rows in Ported above). Only one skipped:
  **#4126da65a** (bws_cache.json read-deny) — the Bitwarden Secrets-Manager
  cache file is never written in our fork, so the deny entry would guard a
  nonexistent file. The two originally-"skip" dashboard/chat items (#44df52005
  Path.home guard, #782681f90 google_chat) were ported at the user's request.
  Historical triage detail (now ported): **Port-now first batch** (high value, trivial/small, confirmed
  present + unpatched): `b7b8bec80` block `/proc/*/{environ,cmdline,maps}` from
  read_file (leaks the agent's own provider keys); `dcc163ee2` redact creds
  before session-log persistence; `95b5b7240`+`6bebab476` block AWS bedrock
  bearer token from subprocess env (port the narrowed end-state); `4694524de`
  write-deny `.anthropic_oauth.json`. Also bring/adapt: `1a9ef8314`
  API_SERVER_KEY-required bind, `30928f945` dashboard asset/env denylist,
  `d7c5d5dee` don't-persist-borrowed-creds (LARGE — reconcile provider-source
  table first), `2e181602a` pool isolation on fallback, `ec4d6f182`→`9c77a0c3c`
  masked secret prompts, `43abc51f6` msgraph CIDR, `243ebc7a6` atomic OAuth
  writes, `79fc92e9c` .env 0600. Skip: `4126da65a` (BWS absent), `44df52005`
  (dashboard/docker crash), `782681f90` (google_chat plugin). Details in the
  `security-triage-2026-05-30` memory.
- `transcript-tail across resizes` (TUI) — flagged earlier, never SHA-pinned.
- From the 2026-06-12 triage, assessed-but-not-ported medium-value candidates:
  `5affecb44` (capability-gate `tools/list` for prompt-only MCP servers, +215
  LOC), `73dd58499` (propagate HERMES_HOME onto MCP event loop), `ee1a744ac`
  (demote non-coding skills to names-only), `e71d74682` (avoid false MCP
  failed-startup status), `dca11b665` (preserve MCP stdio argv passthrough),
  `a942bfd9c` (reset `_last_flushed_db_idx` on agent reuse), `13650ab7f`
  (audio attachment note clarification).
- `a4f179c50` (GPT/Codex patch-mode steering) — **skipped-absent 2026-06-12**:
  no `agent/coding_context.py` / `_EDIT_FORMAT_GUIDANCE` in the fork.
- Rebrand-drift cleanup (pre-existing, not upstream ports): `test_model_catalog`
  docs URL (`build_catalog()` emits `nousresearch.com`, committed json uses
  `teddyjfpender.github.io`); `test_auxiliary_client_azure_foundry` expects
  `"hermes doctor"` vs the emitted `"superforecasting-agent doctor"`.
  (The `test_steer.py` args_hint drift from `ac3ab85b7` was fixed 2026-06-12.)
