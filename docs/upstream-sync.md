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

- **Classify** — profile `git log <merge-base>..origin/main` by conventional-commit
  type, scope, and diff size; keep only the fork-relevant scopes (`gateway`, `cli`,
  `tui`, `agent`, `codex`, `mcp`, `skills`, `security`, `file-safety`, `prompt`,
  `patch`). Drop web/kanban/docker/dashboard-auth/Nous-portal/chat-adapter/xAI/
  image-gen — ~70% of churn, zero forecasting payoff.
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

`merge-base = edb2d910` · last audit: 2026-05-30.

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

### Already-have (subsumed; do not port)

- **#00bd24e2** (expand memory threat patterns) — ancestor of #32269, which
  consolidated every pattern + all 17 invisible chars into `threat_patterns.py`.
- **#43a3f119** (recover codex streams with null output) — our hand-patch in
  `agent/codex_runtime.py` (`except TypeError` fallback) already handles this; it
  is *superseded* by #33042's rewrite (see deferred).

### Deferred (valuable; needs a focused pass or a prerequisite)

| Upstream | Why deferred |
|---|---|
| #33042 | 613-line rewrite of `codex_runtime.py` (drops `responses.stream()`, consumes events directly) + 5 test files. Retires our hand-patch and the now-dead #43a3f119 fallback. The codex companions (#8601c4d4 TTFB watchdog, #283bb810 prefill, #2d422720 timeouts) sit on this same new event-consumption architecture, so they can't be cleanly applied onto our old `responses.stream()` path — they come *with* the rewrite. Our hand-patch works, so deferring is safe. **Do as its own wave.** |
| c6a992e3 | Host-derived `<VENDOR>_API_KEY` fallback. Now unblocked for the `_resolve_openrouter_runtime` path by #28660; but its full value also needs the `_resolve_named_custom_runtime` chains gated (still ungated — separate upstream PRs). |

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

- The `_resolve_named_custom_runtime` host-gating PRs (close the remaining
  credential-leak chains, pairs with #28660 / c6a992e3).
- TUI fixes verified net-new earlier: mouse-residue suppression (#912e6e22),
  wayland clipboard (#c42edd80), transcript-tail across resizes, unified model
  picker + disk cache (#3a9bc9d8 — rebrand cache path).
