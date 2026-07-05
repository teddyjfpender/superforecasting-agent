# The Multiplayer Harness — Named Agents Collaborating in Slack

The target, stated as the operator gave it: ten people, each running their own
instance of this system, gather in Slack with their agents — 20+ entities
(humans and agents) working one forecasting thesis together. Every agent has
its **own name and its own @-taggable Slack identity** (Claude-Tag
equivalence). Agents share evidence, forecasts, documents, and lessons with
each other **publicly** — threads, reactions, file uploads, never DMs for
substance — and each import lands in the receiving ledger with full
provenance, subject to the same honesty gates as everything else.

This is a HARNESS plan, not a chat-bot plan: the unit of collaboration is the
scoreable forecast, and every Slack interaction must either read from or
honestly write into a ledger.

## What already exists (verified against the tree)

| Seam | Where | State |
| --- | --- | --- |
| Slack platform adapter + Events API app | `gateway/platforms/slack.py`, `slack_app.py` | Shipped (the #159 arc: OAuth install writer + HTTP transport) |
| Agent-facing Slack tool (post/react/thread_ts) | `tools/slack_tool.py` | Shipped; needs blocks/files/metadata verbs |
| Session routing by session_key | gateway session machinery | Shipped (#154) |
| Per-tenant credentials + runtime contextvars | `#156/#157` arcs | Shipped |
| External-estimate panels | `forecasting/ledger/panels.py::record_panel_run(estimates=...)` | Shipped — the cross-instance Delphi substrate |
| Delphi revision rounds | `forecasting/quorum.py` | Shipped |
| Cross-pollination (flag-don't-merge, world-views) | `forecasting/forecast_links.py` | Shipped — the import philosophy |
| Provenance + honesty gates + `calibration_eligible` | ledger/gate + scoring | Shipped — peer imports must ride these |
| Policy matrix (action classes × decisions, JobRecord audit) | `forecasting/jobs/policy.py` | Shipped — extends to sharing |
| Typed config (`appconfig`) | `forecasting/appconfig.py` | Shipped — carries the agent's name |
| Thesis exports, analyst notes, chart rendering | thesis/writeup machinery | Shipped — the shareable artifacts |

The plan is therefore mostly **composition**, which is why it can be deeply
specified rather than hand-waved.

---

## Design pillars (the non-negotiables)

1. **One agent, one Slack identity.** Each instance provisions its OWN Slack
   app (its own bot user) so `@Ada` and `@Bernard` are genuinely distinct,
   taggable, DM-able entities with presence — not one app puppeting display
   names (`chat:write.customize` fakes the name but not the @-mention, the
   member list, or DMs; rejected). A manifest template + provisioning command
   makes "create Ada" a five-minute operator flow, and the existing OAuth
   install writer stores the resulting tokens per-instance.
2. **Public by default, threads by law.** Substantive agent-to-agent exchange
   happens in channels, one thread per question or thesis round. DMs are for
   operator-private control only. The soul gains this stance; the sharing
   policy refuses `share` actions targeted at DMs.
3. **Every message that carries data carries machine truth.** Human-readable
   Block Kit on the surface, a versioned JSON payload underneath via Slack
   **message metadata** (`event_type` + `event_payload` on `chat.postMessage`)
   — agents parse metadata, never regex each other's prose. The payload
   schemas live in `protocol/` (pydantic → generated docs), because this IS a
   wire.
4. **Imports are guests, not citizens.** A peer's forecast lands as a linked
   world-view (the cross-pollination flag-don't-merge doctrine), a peer's
   evidence lands with `origin=peer:<agent>@<team>` provenance, a peer's
   lesson lands **inactive pending triage** — and anything imported is
   `calibration_eligible=False` for the receiver's own scoring. Your Brier is
   yours; the honesty doctrine extends across the org boundary.
5. **Sharing is a governed action class.** The policy matrix grows a `share`
   class ({evidence, forecast, lesson, document} × {auto, ask, never}) plus a
   counterparty allowlist — "authorised agents" is a config surface, not a
   vibe. Every share/import decision logs to the JobRecord/event-log exactly
   like spend does.
6. **The market analogy holds.** A peer's forecast is treated like a market
   price: signal to weigh, never truth to copy. The Delphi machinery — not
   averaging — is how group numbers form.

---

## The protocol: `sfp/1` (superforecast protocol over Slack metadata)

All payloads: `{v: 1, kind, sender: {agent, instance_id, team}, ts, body}`,
pydantic-modeled in `protocol/collab.py`, size-capped (Slack metadata ≤ 8KB;
larger bodies go as file uploads with the metadata carrying the pointer +
sha256).

| kind | body | Block Kit surface |
| --- | --- | --- |
| `forecast.card` | question ref (title + resolution criteria hash), p or distribution, as_of, horizon, top-3 rationale bullets, evidence refs (ids + titles), uncertainty band | The forecast card: headline %, band, rationale, "as of", provenance footer |
| `evidence.share` | source url/type, captured_at, triage label, key excerpt, sha256; full text as file attachment | Quote block + file |
| `lesson.share` | lesson text, scope (domain/type), origin stats (n, effect size), compiled-rule preview | Callout block, explicitly marked "pending your triage" |
| `thesis.round` | round #, question set, deadline, participants | The facilitator's round-open card |
| `thesis.aggregate` | per-agent cards digest, spread, disagreement map, the Delphi aggregate + method | Aggregate card + chart image |
| `ack` / `request` | correlation id; request kind (e.g. "share your evidence for Q") | Emoji reaction (📥 imported, 👀 read, ✅ ack) + threaded reply |

Emoji are **protocol signals with fixed meanings** (📥 = imported into my
ledger, 🔁 = revised my forecast in response, ⚠️ = provenance/leak concern),
documented in the ops guide so humans read the same channel state agents do.

## Identity & provisioning

- `appconfig`: `AGENT_NAME` (e.g. "Ada"), `AGENT_INSTANCE_ID` (stable uuid,
  generated once), optional persona notes. The name flows into the soul
  ("You are Ada, …" — the existing identity-injection seam), the TUI header,
  and all `sfp/1` payloads.
- `forecast slack provision`: emits a Slack **app manifest** (name, scopes:
  `app_mentions:read, chat:write, reactions:read/write, files:read/write,
  channels:history, im:history, metadata.message:read`) → operator creates the
  app (Slack has no full app-creation API without an org admin manifest
  token; where a manifest token exists, automate end-to-end) → the existing
  OAuth install flow captures tokens → `forecast slack join #channel`.
- The **directory**: each agent posts a `directory.hello` metadata message to
  a well-known channel (#forecast-agents) on join; every instance maintains
  `{home}/collab/directory.json` (agent → bot user id, instance id, last
  seen). This is how "authorised counterparties" get resolved and how a
  facilitator discovers participants.

## Routing & sessions (single instance in Slack)

- Mention `@Ada …` in a channel → a gateway session keyed
  `slack:<team>:<channel>:<thread_ts>` — **thread = session** (context
  contiguity + Slack hygiene in one move). DMs key per conversation.
- The session context prompt already carries platform notes; it gains the
  collab stance (post cards not walls of text; thread discipline; when
  another agent's metadata message arrives, parse it — don't chat about it).
- Peer metadata messages arrive as events; a `collab_router` (new,
  `forecasting/collab/router.py`) classifies: card → import pipeline;
  request → policy-checked handler; round → Delphi participant flow. Humans'
  plain-text mentions route to the normal agent loop.

## The import pipeline (receiving side)

`forecasting/collab/imports.py`, every step gated:
1. Verify sender against the directory + allowlist (policy `share.accept`).
2. `forecast.card` → resolve-or-create the local question by resolution-
   criteria hash (never title fuzzy-match alone; on hash mismatch, flag a
   criteria-divergence warning — two agents "on the same question" with
   different criteria is THE classic group-forecasting failure and we make it
   visible instead of silent) → store as a **peer snapshot** linked via
   forecast_links (world-view; flag-don't-merge), `calibration_eligible=False`,
   provenance `peer:Ada@T012ABC`, alert the operator ("Ada is at 34%, you are
   at 48% — 14pp divergence").
3. `evidence.share` → `import_source_evidence` with peer provenance + the
   sha256 check + the time-travel/leak-domain gates (shared evidence must not
   smuggle foreknowledge into backtests — pin captured_at).
4. `lesson.share` → stored INACTIVE with origin stats; surfaces in the triage
   queue; the operator (or the trust-gated triage) decides adoption. Peer
   lessons never auto-compile to enforced rules.
5. Everything appends to the event log (`collab.import` events) — the whole
   exchange is forensically replayable.

## Group work: Delphi-in-Slack (the crown jewel)

Maps the EXISTING quorum/Delphi machinery onto a channel, cross-instance:
- Any agent (or human) opens a round: `@Ada run a round on <question>` →
  Ada posts `thesis.round` (round 1, deadline) in a fresh thread.
- Each participating agent runs its OWN forecast locally (its own evidence,
  its own panel, its own gates — independence is the value) and posts its
  `forecast.card` in-thread.
- Discussion happens (humans + agents, threaded). Revision: the facilitator
  posts round 2; agents may revise (🔁), citing what changed their minds —
  the Delphi revision-round machinery already models this.
- Close: the facilitator ingests all cards via
  `record_panel_run(estimates=[…])` — each peer agent IS a panelist with a
  track record (the S7.5 weighting machinery extends to peer panelists as
  resolutions accumulate) — and posts `thesis.aggregate` with the spread,
  the disagreement map, and a rendered chart image.
- Each participant's ledger stores the aggregate as a linked artifact, NOT as
  its own forecast. Members keep their own numbers; the group product is the
  panel artifact. Scoring stays individual (your Brier is yours), and the
  aggregate gets scored as its own panelist — over time the org learns
  whether the group beats its best member (the ensemble-size machinery
  answers this with real data).

## Trust, safety, and org hygiene

- **Authorization**: allowlist by instance_id (not display name — names are
  spoofable); optional shared-secret HMAC on payloads for high-trust pairs
  (v2). Policy defaults: share.evidence auto within allowlist; share.forecast
  auto; share.lesson ask; accept.* mirror. All logged.
- **Spend**: mention-triggered work runs under run_mode `interactive`;
  round participation under `cycle` caps (a malicious channel can't drain a
  wallet via mentions — rate limits per channel/hour in the router).
- **The honesty doctrine, extended**: never repost another agent's numbers as
  your own; cards carry sender provenance immutably; divergence is surfaced,
  not averaged away; imported data can never fabricate freshness (peer
  evidence keeps ITS captured_at, not arrival time).
- **Slack hygiene enforcement**: the router refuses substantive shares in
  DMs; long content auto-becomes file uploads; every multi-message exchange
  stays in its thread; charts upload as images with alt text.

## Delivery plan (slices, each independently shippable)

- **M1 — Identity & voice** (small): AGENT_NAME/INSTANCE_ID in appconfig →
  soul/TUI/session-context injection; `forecast slack provision` manifest
  emitter; slack_tool grows `post_blocks`, `upload_file`, `post_with_metadata`,
  `read_thread` verbs. *Gate: two locally-provisioned apps with distinct
  names post cards into one test channel.*
- **M2 — The protocol + cards** (the wire): `protocol/collab.py` (sfp/1
  models, generated docs), card renderers (Block Kit from a snapshot /
  evidence item / lesson), `forecast share <question> --channel` CLI + tool
  action + `S` from the desk. *Gate: a rendered card round-trips —
  posted, re-parsed from metadata, byte-equal body.*
- **M3 — The import pipeline**: collab/router + imports, criteria-hash
  matching + divergence warnings, peer snapshots (world-view links,
  calibration_eligible=False), evidence + lesson-inactive paths, the share/
  accept policy classes, directory + allowlist. *Gate: two instances
  exchange a forecast + evidence + lesson end-to-end; the receiver's doctor
  shows the imports with provenance; scoring provably excludes them.*
- **M4 — Delphi-in-Slack**: round open/close flows, cross-instance
  record_panel_run ingestion, aggregate card + chart upload, peer-panelist
  track records. *Gate: a 3-instance round (scriptable in tests with a
  stubbed Slack) produces a scored panel artifact in all three ledgers.*
- **M5 — Org scale**: provisioning automation (manifest-token path),
  #forecast-agents directory bootstrap, per-channel rate limits, the ops
  runbook (docs/operating.md section + a deep-dive), multi-workspace
  token handling (the existing team_id-keyed token store extends).
- **M6 — Polish to Claude-Tag parity**: presence/status (bot presence set
  from the agents-chip state), slash-command shims (`/forecast next` in
  Slack), scheduled round cadences (cron job type posts the round), human
  onboarding cards ("what can I ask Ada?" — the h-help content reused).

Sequencing: M1→M2→M3 are strictly ordered (identity → wire → imports);
M4 needs M3; M5/M6 parallelize after. M1+M2 are one focused session; M3 is
the careful one (every honesty gate earns a test); M4 is mostly composition.

## Honest limits & risks (named now)

- Slack app creation cannot be fully automated without an org manifest
  token — M1 ships a guided flow, M5 automates where the token exists.
- Slack metadata is 8KB and only visible to apps — full artifacts ride file
  uploads; humans see the Block Kit surface, not the payload (by design).
- Two instances CAN diverge on question identity — the criteria-hash +
  divergence-warning design makes this visible; it cannot make it impossible.
- Peer track records start empty — early aggregates weight uniformly and say
  so; weights earn in as shared questions resolve (the same earn-it-first
  stance as the triage trust gate).
- This plan deliberately does NOT build a central server: the org harness is
  federated over Slack + per-instance ledgers, which matches the product's
  sovereignty stance (your ledger is yours). A shared org ledger is a
  possible v2, noted and not designed here.
