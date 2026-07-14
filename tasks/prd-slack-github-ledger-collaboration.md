[PRD]
# PRD: Slack + GitHub Multiplayer Ledger Collaboration

## 1. Overview

Build a multiplayer change-control layer for the Superforecasting Agent in
which a Slack thread is a collaborative forecasting workspace, a GitHub pull
request is the review and coordination record, and the forecast ledger remains
the authoritative state.

Each active Slack thread owns one durable changeset, one isolated Kubernetes
sandbox, one Git branch, and at most one open pull request. Multiple people and
their agents may contribute commits, evidence, reviews, and discussion to that
changeset. A changeset may update several related forecasts. Low-risk changes
can promote automatically after required checks; medium- and high-risk changes
wait for policy-defined human approval.

The system must preserve four identities without conflating them:

1. the human owner;
2. the owner's Slack user;
3. the owner's Slack agent persona, which has its own name and picture; and
4. the owner's GitHub account.

The Slack persona may vary, but GitHub contributions made by that persona must
use a GitHub App user-to-server token delegated by its owner. Every commit,
comment, review, and attestation must record both the GitHub owner and the agent
persona that performed the work. An autonomous agent action does not count as a
human approval merely because it used the owner's GitHub identity.

Every changeset also receives a provenance bundle. The bundle contains a
private, encrypted archive of the full trace available to the system and a
review-safe, scoped transcript derived from it. Raw trace archives never enter
Git. Sanitized transcripts, explicit decision records, evidence lineage, test
results, and cryptographic digests may enter the ledger and the pull request.
The design adopts the safety boundaries of OpenClaw's
[agent-transcript skill](https://github.com/openclaw/openclaw/blob/main/.agents/skills/agent-transcript/SKILL.md):
scope to relevant work, remove secrets and internal prompts, summarize tool
activity, fail closed on unresolved sensitive material, and obtain owner
consent before publishing transcript content to GitHub.

This feature extends the existing multiplayer Slack harness and hosted Slack
execution architecture. It does not combine Centaur, OpenClaw, or another
runtime with Superforecasting Agent.

### Confirmed product decisions

- One canonical GitHub repository per forecasting workspace.
- The runtime ledger is authoritative; GitHub is the proposal, review,
  attestation, backup, and collaboration plane.
- The repository stores a portable ledger representation, documents, policies,
  safe transcripts, and changesets, but not live databases, secrets, caches, or
  raw traces.
- One Slack thread corresponds to one changeset/branch/PR and may update
  multiple forecasts.
- Promotion uses three policy tiers: automatic, one-human, and two-human.
- Private raw traces are encrypted and retained for 90 days by default.
- Full project quality gates are required.

## 2. Goals

- Make every material forecast mutation reviewable as a deterministic,
  content-addressed changeset before it enters the authoritative ledger.
- Let people and their agents collaborate from Slack and GitHub without losing
  authorship, provenance, system visibility, or liveness.
- Give every Slack thread a visible lifecycle from research through ledger
  application, including progress, blocked state, required reviewers, and an
  estimated next system action.
- Permit at least 80% of eligible low-risk changes to promote without human
  intervention while never bypassing ledger hooks or required checks.
- Guarantee that medium-risk promotion records at least one qualifying human
  approval and high-risk promotion records at least two, including a forecast
  owner or domain steward.
- Allow a new installation to bootstrap a workspace from its canonical GitHub
  repository and reproduce the same portable ledger revision and content hash.
- Preserve enough provenance to reconstruct what evidence, tools, models,
  people, and agents produced a ledger change without publishing secrets,
  hidden chain-of-thought, raw tool output, or private system instructions.
- Recover safely from duplicate Slack/GitHub webhooks, process restarts,
  concurrent changesets, stale branches, partial GitHub outages, and a Git merge
  whose ledger application is delayed or fails.

## 3. Quality Gates

These gates apply to every user story:

- Run focused tests for the changed domain during development.
- `scripts/run_tests.sh` — complete hermetic Python test suite.
- `ruff check .` — blocking lint rules.
- `uv run lint-imports` — package-boundary contracts.
- `python scripts/check-windows-footguns.py` — cross-platform static guardrail.
- `python -m compileall -q forecasting gateway agent superforecasting_agent`
  — Python compilation.
- `git diff --check` — whitespace and patch-integrity check.

Additional gates by affected surface:

- Changes to migrations or changeset application must pass migration tests from
  a pre-feature database, a fresh database, and an interrupted-apply fixture.
- Changes to GitHub or Slack integration must pass contract tests for signature
  verification, redelivery, idempotency, authorization, and token isolation.
- Changes to transcript handling must pass the secret corpus, malicious-log,
  consent, retention, and fail-closed test suites.
- Changes to `website/` must also pass `cd website && npm run build`.
- A release candidate must pass a stubbed end-to-end test covering Slack thread
  creation through GitHub merge and authoritative ledger application.

No quality gate may use live Slack, GitHub, model, or secret credentials in the
default test suite.

## 4. User Stories

### Phase A — Domain contracts and authoritative application

### US-001: Add collaboration configuration

**Description:** As a workspace administrator, I want typed GitHub, review,
transcript, and repository configuration so that collaboration behavior is
explicit and profile-aware.

**Acceptance Criteria:**

- [ ] Add defaults under `collaboration.github`, `collaboration.repository`,
      `collaboration.review`, and `collaboration.transcripts` in
      `hermes_cli/config.py` without bumping `_config_version` for additive keys.
- [ ] Secrets are registered in `OPTIONAL_ENV_VARS`; non-secret policy remains
      in `config.yaml`.
- [ ] The gateway and classic CLI resolve the same effective values despite
      their different config loaders.
- [ ] Defaults keep GitHub promotion disabled until a workspace is linked.
- [ ] Validation rejects unknown risk tiers, negative retention periods,
      non-HTTPS GitHub API URLs, and an invalid repository slug.

### US-002: Introduce ledger revisions and generalized changesets

**Description:** As a ledger operator, I want every proposed mutation to be
grouped under a durable revision-aware changeset so that it can be reviewed and
applied exactly once.

**Acceptance Criteria:**

- [ ] Add additive tables for ledger revisions, changesets, operations,
      artifact links, and apply attempts.
- [ ] A changeset records workspace, base ledger revision, status, source
      thread, author identities, content digest, risk tier, timestamps, and
      GitHub coordinates.
- [ ] A changeset may reference multiple forecast question IDs.
- [ ] Database constraints prevent two successful applications of the same
      changeset digest.
- [ ] Existing `forecast_update_proposals` remain readable and are not silently
      migrated or deleted.

### US-003: Define versioned ledger operation schemas

**Description:** As an integration author, I want a stable operation envelope
so that Git, Slack, and the ledger apply the same unambiguous mutation.

**Acceptance Criteria:**

- [ ] Add a versioned operation envelope with operation ID, kind, target,
      preconditions, payload, provenance references, and author attestation.
- [ ] Initial kinds cover forecast creation/update, evidence attachment,
      assumption/reference-class changes, resolution-criteria changes,
      resolution, thesis/document updates, and lesson activation.
- [ ] Unknown versions and operation kinds fail closed without ledger writes.
- [ ] Operation serialization is canonical and produces the same SHA-256 digest
      regardless of dictionary insertion order.
- [ ] JSON schemas are generated or checked into a documented stable location.

### US-004: Build deterministic changeset preview

**Description:** As a reviewer, I want a projected before/after view so that I
can understand a proposal without applying it.

**Acceptance Criteria:**

- [ ] Preview runs against an isolated database transaction or disposable
      ledger copy and leaves the live ledger byte-for-byte unchanged.
- [ ] Output includes changed questions, probability deltas, criteria changes,
      new evidence, hook results, and portable file diffs.
- [ ] Preview reports all failed preconditions and hooks, not only the first.
- [ ] Repeating a preview at the same base revision yields the same projection
      digest.
- [ ] Preview can render both machine JSON and reviewer-facing Markdown.

### US-005: Add idempotent transactional apply service

**Description:** As the authoritative ledger, I want approved changesets applied
transactionally so that partial or duplicate promotions cannot corrupt state.

**Acceptance Criteria:**

- [ ] Application obtains a workspace promotion lock and rechecks base revision,
      changeset digest, approvals, checks, and ledger hooks.
- [ ] All operations apply inside one database transaction through the existing
      ledger write gate.
- [ ] Success increments the monotonic ledger revision and records the resulting
      object IDs and ledger digest.
- [ ] A duplicate webhook or retry returns the prior successful result without
      writing new snapshots.
- [ ] Any failed operation rolls back the complete changeset and records a
      non-secret apply diagnostic.

### US-006: Classify changeset risk deterministically

**Description:** As a workspace administrator, I want material changes to
receive stricter review automatically so that autonomous promotion stays safe.

**Acceptance Criteria:**

- [ ] The default classifier assigns low, medium, or high risk from operation
      kinds, maximum probability delta, forecast protection metadata, and hook
      results.
- [ ] Low risk includes documentation and non-material evidence metadata changes
      that do not alter active probability or resolution meaning.
- [ ] Medium risk includes ordinary active-probability changes below the
      configurable materiality threshold.
- [ ] High risk includes resolution criteria, resolutions, protected forecasts,
      lesson activation, and material probability changes.
- [ ] A multi-forecast changeset receives the highest tier of any contained
      operation.
- [ ] Workspace policy may raise but may not lower the built-in minimum tier for
      protected operation kinds.

### US-007: Implement quorum and approval binding

**Description:** As a reviewer, I want approvals bound to the exact proposal I
saw so that later agent edits cannot inherit stale consent.

**Acceptance Criteria:**

- [ ] Low risk requires passing checks and no human approval by default.
- [ ] Medium risk requires one eligible human approval.
- [ ] High risk requires two distinct eligible humans, one of whom is a forecast
      owner or domain steward.
- [ ] Proposal authors cannot satisfy their own required human approval.
- [ ] Agent-authored reviews are recorded but never satisfy a human quorum.
- [ ] Every approval binds to the changeset digest and Git head SHA and becomes
      stale after a reviewable change.
- [ ] Rejection, request-changes, hold, and administrative break-glass decisions
      are explicit audited states.

### US-008: Bridge legacy forecast proposals

**Description:** As an existing user, I want current autopilot proposals to
continue working while new collaboration flows use generalized changesets.

**Acceptance Criteria:**

- [ ] Existing autopilot CLI and ledger methods retain their current behavior
      when GitHub collaboration is disabled.
- [ ] A compatibility adapter can wrap a pending forecast update proposal in a
      generalized changeset without mutating the legacy row.
- [ ] Approval/rejection synchronizes status through one documented adapter and
      cannot create two forecast snapshots.
- [ ] Tests cover old databases and mixed legacy/new proposal queues.

### Phase B — Provenance, transcripts, and retention

### US-009: Add provenance bundle records

**Description:** As a forecast reviewer, I want each ledger change linked to its
source sessions and artifacts so that I can audit how it was produced.

**Acceptance Criteria:**

- [ ] Add records for provenance bundles, session/run links, decision records,
      transcript artifacts, raw trace archives, consents, and access events.
- [ ] A bundle can link multiple SessionDB sessions and ExecutionStore runs to
      one changeset.
- [ ] Decision records capture conclusions, alternatives, evidence references,
      assumptions, probability changes, unresolved uncertainty, model, prompt
      version, tools, and tests.
- [ ] Ledger objects created by an applied changeset link back to the bundle and
      changeset digest.
- [ ] Missing optional provider reasoning never makes the provenance record
      invalid.

### US-010: Capture encrypted private trace archives

**Description:** As an authorized investigator, I want the full trace available
to the system retained privately so that difficult decisions can be audited
without publishing sensitive execution data.

**Acceptance Criteria:**

- [ ] Archive input can include SessionDB messages, available provider reasoning
      fields, ExecutionStore events, tool-call envelopes, and test results.
- [ ] Content is envelope-encrypted with a workspace key before object storage.
- [ ] The ledger stores only object locator, ciphertext digest, byte size,
      retention deadline, key version, and authorization metadata.
- [ ] Raw traces, tokens, and decryption keys never appear in Git, Slack blocks,
      pod manifests, or tool results.
- [ ] Access requires an authorized control-plane endpoint and creates an
      immutable access event.
- [ ] The implementation does not claim to capture or expose hidden model
      chain-of-thought that the provider did not return.

### US-011: Render review-safe scoped transcripts

**Description:** As a collaborator, I want a readable transcript of relevant
work so that I can review reasoning and evidence without reading unsafe logs.

**Acceptance Criteria:**

- [ ] Scope selection uses changeset goal, branch, changed ledger objects,
      SessionDB IDs, and explicit run links rather than broad time windows alone.
- [ ] The renderer keeps user requests, visible assistant conclusions, explicit
      decision records, terse tool summaries, evidence references, and tests.
- [ ] It removes system/developer prompts, raw tool output, environment values,
      cookies, tokens, authentication URLs, unrelated sessions, and provider raw
      reasoning fields.
- [ ] Secret/private-key/session-cookie detection fails closed and reports only
      secret class and location, never the secret value.
- [ ] Output contains stable section markers so an existing PR body can be
      updated idempotently.
- [ ] The renderer can produce local Markdown and HTML preview without network
      access.

### US-012: Require transcript publication consent

**Description:** As the human owner of an agent, I want to approve what transcript
content enters GitHub so that private work is not published silently.

**Acceptance Criteria:**

- [ ] Before the first transcript publication for a changeset, Slack presents a
      preview and asks the initiating owner to include, omit, or regenerate it.
- [ ] Consent binds to transcript digest, destination repository, owner identity,
      and changeset ID.
- [ ] A changed transcript requires renewed consent.
- [ ] Declining publication keeps the private provenance bundle and publishes a
      manifest stating `transcript_withheld_by_owner` without blocking the PR.
- [ ] Unsafe rendering publishes no transcript content and records
      `transcript_unavailable_safety_failure`.
- [ ] Automatic low-risk promotion may proceed with mandatory decision records
      and private provenance when transcript content is withheld.

### US-013: Enforce 90-day trace retention

**Description:** As a workspace administrator, I want private traces deleted on
schedule so that auditability does not become indefinite sensitive retention.

**Acceptance Criteria:**

- [ ] Raw trace archives default to a 90-day expiry from capture time.
- [ ] Authorized reviewers may pin an archive with reason and expiry or legal
      hold; indefinite pins require administrator permission.
- [ ] A scheduled sweeper deletes ciphertext, records a tombstone, and never
      deletes sanitized transcripts or attestations.
- [ ] Missing objects and repeated sweep attempts are idempotent.
- [ ] Retention status is visible in admin CLI and never exposes trace content.

### Phase C — Portable repository and bootstrap

### US-014: Define the canonical repository manifest and layout

**Description:** As a workspace owner, I want a documented portable repository
format so that GitHub is a durable, reviewable backup and collaboration plane.

**Acceptance Criteria:**

- [ ] Add a versioned `forecast-workspace.yaml` manifest with workspace ID,
      format version, default branch, ledger revision, and content digest.
- [ ] Define directories for portable ledger state, changesets, documents,
      policies, sanitized transcripts, attestations, and extension locks.
- [ ] Provide JSON schemas and canonical serialization rules for every generated
      file type.
- [ ] `.gitignore` and validation reject databases, `.env`, tokens, raw traces,
      caches, Git credential files, and unapproved source payloads.
- [ ] A repository validator reports missing, unexpected, oversized, and
      digest-mismatched files.

### US-015: Export a deterministic portable ledger projection

**Description:** As a workspace owner, I want the authoritative ledger rendered
into diffable files so that collaborators can inspect and recover its state.

**Acceptance Criteria:**

- [ ] Export includes questions, snapshots, evidence metadata, assumptions,
      reference classes, theses, resolutions, scores, lessons, policies, and
      document references supported by the current schema.
- [ ] Export excludes live SQLite files, secrets, private raw trace content, and
      non-redistributable full source bodies by default.
- [ ] Stable ordering and normalized timestamps make two exports of the same
      ledger revision byte-identical.
- [ ] The manifest content digest covers every portable state file.
- [ ] Export runs through a read-consistent ledger snapshot and does not block
      normal reads for the duration of Git upload.

### US-016: Bootstrap a workspace from GitHub

**Description:** As a new or recovering operator, I want to clone a canonical
repository and reconstruct local state so that collaboration can resume on a
fresh machine.

**Acceptance Criteria:**

- [ ] `superforecasting-agent workspace clone OWNER/REPO` creates a profile-aware
      managed workspace directory without writing secrets into the checkout.
- [ ] Bootstrap verifies repository identity, manifest schema, content digest,
      signatures/attestations, and supported format version before import.
- [ ] Reconstruction writes a new ledger database through public ledger APIs and
      the write gate, not by accepting a committed SQLite file.
- [ ] Reconstructed portable state has the same revision and content digest as
      the repository.
- [ ] Failure leaves the previous active workspace unchanged and reports a
      resumable staging path.

### US-017: Add managed checkout and sync service

**Description:** As an operator, I want safe pull/status/reconcile behavior so
that the system can stay aligned with its canonical repository.

**Acceptance Criteria:**

- [ ] Managed checkouts live under a profile-aware workspace directory and never
      reuse the extension overlay checkout.
- [ ] Git commands use argv-only subprocess calls, timeouts, isolated config,
      and credential callbacks that do not expose tokens in arguments.
- [ ] Pulling never mutates the authoritative ledger directly; merged changesets
      enter only through the apply service.
- [ ] Dirty generated files, unexpected local commits, divergence, and rewritten
      remote history stop automatic sync with an actionable status.
- [ ] `workspace reconcile` can regenerate portable state from the ledger or
      replay an unapplied merged changeset after explicit validation.

### US-018: Create one branch per Slack changeset

**Description:** As a Slack collaborator, I want thread work committed to a
stable branch so that participants share one reviewable history.

**Acceptance Criteria:**

- [ ] The control plane maps `(workspace, team, channel, thread_ts,
      generation)` to one changeset ID and branch.
- [ ] Branch names use the changeset ID and do not reveal message text or user
      secrets.
- [ ] Multiple related forecast operations can be committed to the same branch.
- [ ] After promotion or abandonment, the next mutation in the same Slack thread
      starts a new generation and branch.
- [ ] Concurrent commit attempts serialize and preserve each contributing human
      owner and agent persona in attestations.

### Phase D — GitHub App, identities, and pull requests

### US-019: Add GitHub App installation and OAuth onboarding

**Description:** As a user, I want to link my GitHub account to my Slack agent so
that the agent contributes using my permissions and identity.

**Acceptance Criteria:**

- [ ] Provide installation and per-user OAuth flows for a GitHub App using
      state, PKCE where supported, short expiry, and callback validation.
- [ ] After OAuth, call GitHub's authenticated-user endpoint and bind immutable
      GitHub user/node IDs rather than trusting a submitted login string.
- [ ] Access is limited by both the user's permissions and the App installation
      permissions for the workspace repository.
- [ ] Tokens are encrypted at rest, refreshable/revocable, and never returned to
      a sandbox or Slack client.
- [ ] Onboarding reports SSO/installation authorization failures without leaking
      token material.

### US-020: Model owner, Slack, agent persona, and GitHub identity

**Description:** As an auditor, I want actions attributed across all identity
layers so that a custom bot name never obscures who authorized GitHub access.

**Acceptance Criteria:**

- [ ] Add a durable identity binding among internal owner ID, Slack team/user,
      agent instance/persona/bot user, and GitHub user/node ID.
- [ ] Agent name and avatar may change without changing owner or GitHub identity.
- [ ] One owner may bind multiple agent personas; no persona may silently switch
      owners.
- [ ] Every Git operation, PR action, review, and comment records
      `human_owner`, `github_actor`, `agent_instance`, `agent_persona`, and
      `actor_kind` (`human` or `agent`).
- [ ] Conflicting or revoked mappings block writes and leave read-only status
      available.

### US-021: Broker GitHub credentials from the control plane

**Description:** As a security administrator, I want agents to use delegated
GitHub access without receiving raw credentials so that sandbox compromise does
not expose user accounts.

**Acceptance Criteria:**

- [ ] Extend the credential broker with exact GitHub API/upload hosts, path and
      method allowlists, repository binding, and per-action scopes.
- [ ] Sandboxes submit signed capability requests containing changeset, actor,
      operation, and expiry; the control plane performs the GitHub request.
- [ ] Capabilities cannot be replayed for another repository, owner, changeset,
      HTTP method, or path.
- [ ] Protected headers and token values are redacted from logs, exceptions,
      traces, and tool results.
- [ ] Revocation takes effect before the next outbound action.

### US-022: Implement signed, durable GitHub webhook ingress

**Description:** As the control plane, I want GitHub events persisted before
processing so that reviews and merges survive retries and restarts.

**Acceptance Criteria:**

- [ ] Verify GitHub webhook signatures against the configured secret before
      parsing or persistence.
- [ ] Persist delivery ID, installation, repository, event type, action, and
      sanitized payload before acknowledging success.
- [ ] Duplicate delivery IDs do not produce duplicate reviews, comments, or
      ledger apply attempts.
- [ ] Handle pull request, review, review comment, issue comment, check suite/run,
      push, merge-group, installation, and authorization-revocation events used
      by the feature.
- [ ] Unsupported or unauthorized repositories are acknowledged and quarantined
      without agent execution.

### US-023: Publish a draft pull request from a changeset

**Description:** As a collaborator, I want the current branch represented by a
draft PR so that humans and agents can review it in GitHub.

**Acceptance Criteria:**

- [ ] Publishing writes manifest, operations, projected state, decision records,
      attestations, and any consented safe transcript to the branch.
- [ ] The PR body contains changeset summary, affected forecasts, before/after
      probabilities, risk tier, required quorum, hook/check status, Slack thread
      link, and provenance digest.
- [ ] Re-publishing updates the existing branch and PR idempotently.
- [ ] PR creation, comments, and branch writes use the contributing owner's
      user-to-server token when initiated by that owner or their agent.
- [ ] Agent-authored actions carry a visible agent attestation even though GitHub
      attributes the API actor to the owner.

### US-024: Support canonical-repository and owner-fork branches

**Description:** As a contributor without upstream write permission, I want my
agent to work through my fork so that I can still propose ledger updates.

**Acceptance Criteria:**

- [ ] Contributors with branch permission use the canonical repository.
- [ ] Otherwise the service discovers or creates an owner-controlled fork using
      delegated user authorization and opens a cross-repository PR.
- [ ] The canonical changeset ID and digest remain identical across fork and
      upstream PR coordinates.
- [ ] Fork synchronization never force-pushes unrelated owner branches.
- [ ] Loss of fork permission leaves the changeset recoverable and visible in
      Slack.

### US-025: Publish authoritative policy checks to GitHub

**Description:** As a repository administrator, I want GitHub to show whether a
changeset is promotable so that branch rules and human review reflect ledger
policy.

**Acceptance Criteria:**

- [ ] The GitHub App publishes a `ledger/promotion` check run for the exact head
      SHA.
- [ ] The check reports schema validation, base revision freshness, ledger hooks,
      transcript safety state, risk tier, quorum, and projection digest.
- [ ] Only the configured GitHub App can satisfy the repository's expected
      `ledger/promotion` check.
- [ ] New commits invalidate the prior check and approval binding.
- [ ] Documentation supplies a ruleset template requiring PRs, the App-sourced
      check, resolved conversations, blocked force pushes, and optionally the
      merge queue.

### US-026: Reconcile GitHub merge with ledger application

**Description:** As an operator, I want a merged PR to reach an explicit applied
or failed state so that Git history is never mistaken for ledger truth.

**Acceptance Criteria:**

- [ ] A merge webhook moves the changeset to `merged_apply_pending`; it does not
      claim that the ledger changed.
- [ ] The apply worker revalidates merge SHA, changeset digest, base revision,
      policy check source, and quorum before transactional apply.
- [ ] Success records ledger revision and posts `applied` to GitHub and Slack.
- [ ] Failure records `apply_failed`, creates a blocking GitHub check/conclusion,
      posts remediation guidance, and never partially mutates the ledger.
- [ ] A reconciler retries transient failures and requires a new superseding
      changeset for semantic conflicts.
- [ ] Direct pushes or manually merged invalid content never enter the ledger.

### Phase E — Slack multiplayer interaction and liveness

### US-027: Render a persistent Slack changeset status card

**Description:** As a Slack participant, I want one live status card in the
thread so that I know what the agents are doing and what happens next.

**Acceptance Criteria:**

- [ ] The card displays changeset, affected forecasts, active actor/agent,
      current phase, last progress time, GitHub PR, risk, checks, approvals, and
      next expected action.
- [ ] States include researching, editing, transcript preview, checks running,
      draft PR, review required, held, merge queued, merged/apply pending,
      applied, conflicted, failed, cancelled, and abandoned.
- [ ] Tool progress and heartbeat update the existing card or progress message
      rather than flooding the thread.
- [ ] The final ledger result is a separate durable message with revision and
      links.
- [ ] A stale heartbeat visibly changes the card to delayed/reconnecting without
      falsely marking the run failed.

### US-028: Add Slack review actions

**Description:** As a human reviewer, I want to approve, reject, hold, request
changes, or inspect a proposal from Slack so that governance stays in the
collaboration channel.

**Acceptance Criteria:**

- [ ] Block actions include View diff, Preview transcript, Include/withhold
      transcript, Approve, Request changes, Reject, Hold/resume, Open PR, and
      Cancel where authorized.
- [ ] Every action verifies Slack team/user/channel, changeset digest, action
      nonce, authorization role, and expiry.
- [ ] A Slack approval records explicit human intent and posts a GitHub review
      using that human's delegated token.
- [ ] An agent cannot invoke the human-approval action or satisfy human quorum.
- [ ] Duplicate action deliveries return the prior result and do not create a
      second vote.
- [ ] Updated state is visible to every participant in the thread.

### US-029: Preserve Socket Mode and signed-webhook parity

**Description:** As a deployer, I want review interactions to work identically
over both Slack transports so that hosting choice does not change semantics.

**Acceptance Criteria:**

- [ ] Socket Mode and signed HTTP normalize events, interactivity, and commands
      into one internal envelope and idempotency key.
- [ ] Socket Mode acknowledges `envelope_id` promptly and persists the event
      before asynchronous work.
- [ ] HTTP ingress verifies Slack signatures, persists before acknowledgement,
      and returns retryable failure when durable persistence fails.
- [ ] Reconnect, retry, and duplicate tests produce one changeset action.
- [ ] Both paths render identical status transitions and final output.

### US-030: Coordinate multiple owners and agents in one thread

**Description:** As a forecasting team, I want several people and their agents
to contribute to one branch so that a forecast thesis can be developed jointly.

**Acceptance Criteria:**

- [ ] Each inbound contribution resolves its own human owner, Slack persona, and
      GitHub binding before changing the branch.
- [ ] The thread sandbox and branch are shared, but one active write execution is
      serialized through the durable thread queue.
- [ ] Commits from different agents use their respective owners' delegated
      GitHub identities and distinct agent attestations.
- [ ] Participants can request reviews from another person's agent without
      granting that agent the initiator's credentials.
- [ ] Presence/activity shows who or which agent is currently working, queued,
      reviewing, waiting, or disconnected.

### US-031: Synchronize GitHub discussion back to Slack

**Description:** As a Slack collaborator, I want material PR activity summarized
in the thread so that I do not need to poll GitHub for liveness.

**Acceptance Criteria:**

- [ ] New reviews, requests for changes, resolved conversations, check results,
      merge-queue state, merge, and apply result update the Slack card.
- [ ] Human comments receive concise threaded summaries with author and GitHub
      link; full comment bodies are not duplicated when sensitive or oversized.
- [ ] Slack-originated actions and mirrored GitHub webhooks share correlation IDs
      and cannot loop.
- [ ] Rate limiting coalesces bursts without losing the terminal state.
- [ ] A disconnected Slack transport catches up from durable events on restart.

### US-032: Bound autonomous agent discussion on pull requests

**Description:** As a workspace owner, I want agents to discuss and review PRs
without creating infinite conversations or unauthorized changes.

**Acceptance Criteria:**

- [ ] Agents respond only when assigned, mentioned, requested by policy, or
      responsible for a failed check.
- [ ] Per-changeset limits bound agent comments, review rounds, tokens, elapsed
      time, and concurrent tasks.
- [ ] Agent comments identify persona, owner, model/run, and changeset digest.
- [ ] Agents may suggest or commit fixes within their owner's permissions but
      cannot dismiss human change requests, alter review policy, or self-credit
      human approval.
- [ ] Agent-to-agent loop detection pauses the changeset and asks for human
      direction in both Slack and GitHub.

### Phase F — Operations, recovery, and release

### US-033: Add workspace and collaboration CLI commands

**Description:** As an operator, I want local administration commands so that I
can bootstrap, inspect, recover, and audit collaboration without editing files.

**Acceptance Criteria:**

- [ ] Commands cover workspace init/clone/link/status/pull/export/reconcile,
      GitHub auth/status/revoke, changeset list/show/preview/apply/retry/abandon,
      review policy/status, and transcript retention/access audit.
- [ ] New product-facing commands lead with `superforecasting-agent` and active
      forecast-home paths.
- [ ] Mutating commands support `--dry-run` where meaningful and require explicit
      confirmation for destructive recovery actions.
- [ ] Output distinguishes Git merge status from authoritative ledger apply
      status.
- [ ] Commands never print tokens, private trace bodies, or unredacted webhook
      payloads.

### US-034: Add observability and reconciliation jobs

**Description:** As a hosted operator, I want metrics and repair jobs so that
stuck collaboration is detected before users lose confidence.

**Acceptance Criteria:**

- [ ] Metrics cover webhook lag/redelivery, branch/PR latency, check duration,
      approval wait, merge-to-apply lag, apply failures, stale sandboxes,
      transcript safety failures, and retention deletion.
- [ ] Structured logs carry workspace, changeset, run, thread hash, delivery ID,
      and state transition but no secrets or transcript content.
- [ ] Reconcilers detect orphan branches/PRs, merged-unapplied changesets,
      ledger/repository digest drift, expired tokens, stale status cards, and
      overdue trace deletion.
- [ ] Alerts include a safe operator action and never auto-resolve a semantic
      conflict.
- [ ] Admin status remains usable during GitHub or Slack outages.

### US-035: Harden the collaboration threat boundary

**Description:** As a security reviewer, I want adversarial controls tested so
that GitHub content, Slack events, or transcripts cannot escape their authority.

**Acceptance Criteria:**

- [ ] Tests cover forged signatures, webhook replay, repository confusion,
      identity swapping, stale approvals, malicious branch names, path traversal,
      symlinks, oversized files, Git filters/hooks, prompt injection, secret
      exfiltration, and compromised sandbox requests.
- [ ] Managed Git operations disable repository hooks, unsafe filters, global Git
      config, submodule execution, and credential prompts.
- [ ] Repository import treats all text as data and never executes workflows,
      extensions, or scripts during bootstrap.
- [ ] Network policy permits sandboxes to reach only approved control-plane
      endpoints; GitHub credentials remain inaccessible from pods.
- [ ] Security failures stop publication or application and produce redacted
      diagnostics.

### US-036: Deliver an end-to-end multiplayer acceptance harness

**Description:** As a release manager, I want a deterministic simulated workflow
so that the entire Slack/GitHub/ledger contract can be verified without live
services.

**Acceptance Criteria:**

- [ ] The harness simulates three humans, three differently named Slack agents,
      three linked GitHub users, one Slack thread, one sandbox, and one PR.
- [ ] Contributors make distinct commits to a multi-forecast changeset and the
      audit record preserves all identity layers.
- [ ] Low-risk changes auto-promote; medium and high fixtures wait for the exact
      required human quorum.
- [ ] The harness exercises transcript consent, stale approval invalidation,
      duplicate Socket/HTTP/GitHub deliveries, merge queue, restart, and
      successful ledger apply.
- [ ] Failure fixtures prove that unsafe transcript content and a merged stale
      changeset do not mutate the ledger.
- [ ] A bootstrap from the resulting repository reproduces the applied portable
      revision and digest.

### US-037: Publish deployment, governance, and recovery documentation

**Description:** As an administrator, I want an operating guide so that I can
deploy the GitHub App, configure Slack, and recover safely.

**Acceptance Criteria:**

- [ ] Document local, single-control-plane, and Kubernetes-hosted deployment.
- [ ] Document GitHub App permissions, OAuth, webhook setup, repository ruleset,
      merge queue, fork behavior, token revocation, and owner/agent attribution.
- [ ] Document Slack Socket Mode and signed HTTP configuration, interactivity,
      status-card semantics, reconnect behavior, and required scopes.
- [ ] Document transcript privacy, consent, raw trace access, 90-day retention,
      legal hold, and incident response.
- [ ] Document bootstrap, backup, drift, merged-unapplied recovery, disaster
      recovery, and feature rollback.
- [ ] Include an upgrade guide from the existing multiplayer Slack harness and
      legacy autopilot proposals.

## 5. Functional Requirements

### Changesets and ledger authority

- **FR-1:** The ledger must be the sole authority for whether a forecast update
  is applied.
- **FR-2:** A GitHub merge must mean "review record accepted," not "ledger write
  completed."
- **FR-3:** Every changeset must declare a base ledger revision and canonical
  content digest.
- **FR-4:** Every operation must carry explicit preconditions and provenance
  references.
- **FR-5:** Changeset application must be transactional, serialized per
  workspace, hook-gated, and idempotent.
- **FR-6:** A semantic conflict must produce a superseding changeset rather than
  rewriting an already merged proposal.
- **FR-7:** The system must preserve existing direct/local behavior when the
  feature is disabled.
- **FR-8:** Scheduled jobs may propose changesets but must not silently bypass
  promotion policy or mutate active probabilities.

### Identity and authorization

- **FR-9:** Slack agent display name and avatar must be independent of GitHub
  identity.
- **FR-10:** Every GitHub action initiated by a user or their agent must use that
  user's delegated GitHub App authorization when a user-attributed action is
  required.
- **FR-11:** Automated workspace maintenance that has no human initiator may use
  an installation token but must be attributed to the App, never a user.
- **FR-12:** The system must store immutable provider IDs in addition to mutable
  logins/display names.
- **FR-13:** OAuth tokens and refresh tokens must remain encrypted in the control
  plane and must never enter a sandbox.
- **FR-14:** Human and agent intent must be distinct fields even when GitHub shows
  the same account as API actor.
- **FR-15:** An agent-authored approval must never satisfy a human quorum.
- **FR-16:** Slack approval must be accepted only from a linked, authorized human
  user and bound to an unexpired digest/nonce.
- **FR-17:** Revocation of Slack membership, GitHub authorization, repository
  access, or steward role must affect subsequent authorization decisions.

### Git and GitHub

- **FR-18:** Each workspace must have one canonical repository and default
  branch.
- **FR-19:** Each Slack-thread generation must map to at most one open PR.
- **FR-20:** Contributors without upstream branch permission must use their
  owner-controlled fork.
- **FR-21:** Generated repository files must be deterministic and validated
  against a versioned manifest.
- **FR-22:** Live databases, secrets, credentials, raw traces, caches, and Git
  metadata from other checkouts must not be exportable artifacts.
- **FR-23:** GitHub webhook deliveries must be signed, durable, idempotent, and
  repository-bound.
- **FR-24:** The custom `ledger/promotion` check must be evaluated for the exact
  reviewable head SHA.
- **FR-25:** GitHub native rulesets and CODEOWNERS must be defense in depth; the
  ledger policy engine remains the semantic authority.
- **FR-26:** GitHub comments and Slack updates must carry correlation IDs to
  prevent reflection loops.
- **FR-27:** GitHub outage must leave work locally recoverable and visibly
  pending, never silently applied.
- **FR-28:** Bootstrap must reconstruct state through ledger APIs and validate
  the final portable digest.

### Review policy

- **FR-29:** Default low-risk changes may auto-promote only after all required
  checks pass.
- **FR-30:** Default medium-risk changes require one eligible human approval.
- **FR-31:** Default high-risk changes require two distinct eligible human
  approvals including an owner or domain steward.
- **FR-32:** An author must not satisfy their own required human-review slot.
- **FR-33:** New reviewable commits must stale approvals and rerun checks.
- **FR-34:** The highest-risk operation must determine a multi-operation
  changeset's minimum policy.
- **FR-35:** Admin policy may make review stricter but may not weaken protected
  built-in minimums.
- **FR-36:** Break-glass application must require an authorized administrator,
  a reason, a time-bounded incident reference, and an audit event; it must not
  bypass ledger schema or transaction safety.

### Provenance and transcripts

- **FR-37:** Every applied changeset must have a provenance bundle even when no
  transcript is published.
- **FR-38:** The private trace archive must capture the full trace available to
  the application, not claim unavailable hidden reasoning.
- **FR-39:** Raw trace archives must be encrypted before leaving the control
  process and expire after 90 days by default.
- **FR-40:** Review transcripts must be scoped to changeset-relevant sessions and
  runs.
- **FR-41:** GitHub-safe transcripts must omit system/developer prompts, raw tool
  output, credentials, cookies, auth URLs, environment data, and raw provider
  reasoning.
- **FR-42:** Sanitization must fail closed on unresolved sensitive material.
- **FR-43:** Transcript content must not be published to GitHub without consent
  bound to the exact artifact and repository.
- **FR-44:** Withholding or failing transcript publication must not erase private
  provenance or decision records.
- **FR-45:** Every private archive read, pin, legal hold, expiry, and deletion
  must create an access/retention event.

### Slack multiplayer experience

- **FR-46:** Slack Socket Mode and signed HTTP ingress must normalize into one
  execution and review model.
- **FR-47:** Both transports must acknowledge quickly after durable receipt and
  perform model/GitHub work asynchronously.
- **FR-48:** Thread key must remain the sandbox and changeset isolation boundary.
- **FR-49:** One durable public status card must communicate phase, liveness,
  checks, quorum, actor, and next action.
- **FR-50:** A separate durable final message must communicate ledger application
  result.
- **FR-51:** Multiple owners and agent personas may collaborate in one thread,
  but write executions must serialize.
- **FR-52:** Each contribution must use the contributing owner's identity and
  credentials; credentials must never cross owners.
- **FR-53:** Slack review actions must be idempotent and authorization checked at
  action time.
- **FR-54:** GitHub review/check/merge/apply changes must update Slack from
  durable events after reconnect.
- **FR-55:** Autonomous PR discussion must have explicit triggers, budgets, and
  loop detection.

### Availability, audit, and operations

- **FR-56:** Execution, delivery, GitHub webhook, apply, and Slack render state
  must survive control-plane restart.
- **FR-57:** Postgres and an object store must be the production horizontal-scale
  targets; SQLite/filesystem implementations may support local single-process
  mode behind the same interfaces.
- **FR-58:** Logs and metrics must use opaque IDs/hashes and exclude message,
  transcript, token, and evidence bodies by default.
- **FR-59:** Reconcilers must be safe to repeat and must never auto-resolve a
  semantic conflict.
- **FR-60:** The system must expose Git-merged, ledger-apply-pending, applied,
  and apply-failed as distinct observable states.
- **FR-61:** Repository format and operation schema upgrades must be versioned,
  backward readable for at least one prior version, and migrated explicitly.
- **FR-62:** No production path may depend on a live model call to validate,
  classify, approve, or apply an already-authored changeset.

## 6. Non-Goals

- Replacing the forecast ledger with Git files or treating a committed SQLite
  database as portable state.
- Combining Centaur or OpenClaw runtimes with Superforecasting Agent.
- Replacing the existing `sfp/1` Slack protocol for peer forecast/evidence
  sharing. Peer world views remain non-authoritative imports; changesets govern
  promotion into a shared authoritative workspace.
- Publishing raw traces, raw provider reasoning, system prompts, secrets, or
  hidden chain-of-thought to GitHub or Slack.
- Claiming access to model reasoning that an inference provider does not return.
- Giving Kubernetes sandboxes GitHub, Slack, encryption, or object-store
  credentials.
- Allowing agents to impersonate human approval, dismiss human change requests,
  or modify their own review requirements.
- Supporting arbitrary bidirectional edits to generated portable files without
  a valid operation manifest and apply preview.
- Executing repository Actions, hooks, filters, submodules, skills, extensions,
  or scripts during bootstrap.
- Building a general-purpose source-code collaboration product unrelated to
  forecast questions, evidence, theses, calibration, and ledger learning.
- Storing full copyrighted source documents in Git by default.
- Guaranteeing atomicity across GitHub's repository transaction and the local
  ledger transaction. The explicit merged/apply-pending state and reconciler
  handle this unavoidable distributed boundary.

## 7. Technical Considerations

### 7.1 Existing seams to extend

| Existing surface | Role in this feature |
| --- | --- |
| `forecasting/ledger/core.py` and `forecasting/ledger/gate.py` | Additive changeset/revision records and the final transactional write boundary. |
| `forecasting/ledger/autopilot.py` | Compatibility source for current `forecast_update_proposals`; do not expand it into the whole GitHub domain. |
| `hermes_state.py` | Source-session/message linkage and private available reasoning fields. |
| `gateway/execution_store.py` | Durable Slack thread/run/event/delivery state; extend by interface or adjacent collaboration store. |
| `gateway/sandbox_runtime.py` | One pod per Slack conversation/thread; the pod never receives GitHub secrets. |
| `gateway/credential_broker.py` | Control-plane GitHub capability enforcement and outbound credential injection. |
| `gateway/platforms/slack.py` and `slack_app.py` | Normalized Socket/HTTP events, interactive actions, progress, and final rendering. |
| `forecasting/identity.py` | Agent persona/instance identity; extend through a separate owner/provider binding rather than putting OAuth tokens here. |
| `forecasting/collab/*` and `protocol/collab.py` | Existing federated peer-sharing protocol; changeset coordination must coexist without making peer imports authoritative. |
| `agent/extension_sources.py` | Separate organization overlay checkout; do not reuse it as the ledger workspace repository. |
| `plugins/obsidian/*` | Reference for human-editable projections and sync, not an authority or Git transport. |
| `tools/checkpoint_manager.py` | Reference for isolated Git configuration and argv-only operations; its shadow checkpoint store is not the canonical workspace repo. |

### 7.2 Proposed package boundaries

```text
forecasting/change_control/
  models.py          # versioned operations, changesets, reviews, attestations
  store.py           # SQLite/Postgres-facing persistence contract
  preview.py         # deterministic dry-run and portable projection diff
  policy.py          # risk classification and quorum
  apply.py           # promotion lock, revalidation, transaction, revision
  compatibility.py   # legacy forecast_update_proposals adapter
  provenance.py      # bundles, decision records, ledger links
  transcripts.py     # scope, sanitize, render, consent metadata
  retention.py       # encrypted archive lifecycle

forecasting/workspaces/
  manifest.py        # portable repo schema and digest
  export.py          # deterministic ledger projection
  bootstrap.py       # verified reconstruction
  checkout.py        # safe managed Git client
  reconcile.py       # drift and merged-unapplied repair

gateway/github/
  app.py             # App JWT/installation plumbing
  oauth.py           # user authorization and refresh/revoke
  client.py          # narrow REST/GraphQL calls behind credential broker
  webhooks.py        # signed durable ingress
  publisher.py       # branch, commit, PR, check, review, comment
  sync.py            # GitHub events -> changeset/Slack events

gateway/collaboration/
  identities.py      # owner/Slack/persona/GitHub binding
  coordinator.py     # thread generation, shared branch, serialized work
  renderer.py        # Slack status card and actions
  reconciler.py      # durable repair jobs

protocol/change_control/
  schemas/           # checked-in JSON schemas and examples
```

The GitHub integration may use the general plugin surface for optional CLI/tool
registration, but ledger authority, identity enforcement, and gateway webhook
contracts are generic framework capabilities. No plugin-specific conditional
belongs in `run_agent.py` or other core loops.

### 7.3 State ownership

```text
Slack / GitHub transports
          |
          v
durable control-plane events -----> Slack renderer
          |
          v
changeset coordinator -----> managed Git branch / PR
          |                         |
          |                         v
          |                   reviews + checks
          |                         |
          +---- promotion lock <----+
                    |
                    v
          authoritative ledger transaction
                    |
                    +----> portable projection + applied attestation
```

- The ledger owns applied forecast truth and monotonic revision.
- The changeset store owns proposal/review/apply state.
- GitHub owns collaborative branch/PR history but not applied truth.
- Slack owns the human-facing conversation, not execution state.
- The encrypted object store owns private trace ciphertext.
- Git owns sanitized, portable, reconstructable review artifacts.

For local mode these contracts may share SQLite and filesystem storage. Hosted
multi-replica mode must use Postgres for coordination and an encrypted object
store for raw traces.

### 7.4 Suggested additive data model

Core ledger/change-control records:

- `ledger_revisions(revision, parent_revision, changeset_id, digest, applied_at)`
- `ledger_changesets(id, workspace_id, base_revision, status, digest,
  risk_tier, slack_thread_key, branch, pr_number, head_sha, created_by, ...)`
- `ledger_change_operations(id, changeset_id, sequence, kind, target_ref,
  preconditions_json, payload_json, digest)`
- `ledger_reviews(id, changeset_id, digest, head_sha, decision, actor_kind,
  owner_id, provider_ids, role, source, created_at, stale_at)`
- `ledger_apply_attempts(id, changeset_id, merge_sha, state, diagnostic,
  started_at, finished_at)`
- `ledger_artifact_links(changeset_id, artifact_type, artifact_ref, digest)`
- `provenance_bundles(id, changeset_id, digest, created_at)`
- `decision_records(id, bundle_id, author_identity_json, body_json, digest)`
- `transcript_artifacts(id, bundle_id, kind, digest, safety_state,
  consent_state, locator, created_at)`
- `trace_archives(id, bundle_id, ciphertext_digest, key_version, locator,
  expires_at, hold_state, deleted_at)`
- `trace_access_events(id, archive_id, actor, action, reason, created_at)`

Control-plane-only records:

- `collaboration_owners`
- `slack_identity_bindings`
- `agent_persona_bindings`
- `github_user_bindings`
- `github_app_installations`
- encrypted OAuth credential references
- durable GitHub deliveries and outbound obligations
- thread-generation/branch/PR mappings

OAuth secrets must not be stored in the forecast ledger or portable export.

### 7.5 Repository layout

```text
forecast-workspace.yaml
.gitattributes
.gitignore
.github/
  CODEOWNERS
  pull_request_template.md
  workflows/validate-forecast-workspace.yml
ledger/
  revision.json
  questions/<question-id>.json
  snapshots/<question-id>/<forecast-id>.json
  evidence/<evidence-id>.json
  assumptions/<assumption-id>.json
  reference-classes/<reference-class-id>.json
  theses/<thesis-id>.json
  resolutions/<question-id>.json
  scores/<question-id>.json
  lessons/<lesson-id>.json
changesets/<changeset-id>/
  manifest.json
  operations.jsonl
  projection.json
  decision-records.json
  attestations.json
  transcript.md              # only after explicit consent
documents/
policies/
extensions.lock.json         # resolved overlay refs, never credentials
```

Generated state files are projections of the authoritative ledger. A proposed
PR includes the operation log and the projected files that would result. On
application, the system verifies that the PR projection digest matches a fresh
preview at the current base revision.

### 7.6 Changeset lifecycle

```text
draft
  -> preview_failed | ready
ready
  -> publishing -> review_open
review_open
  -> changes_requested | held | checks_running | abandoned
checks_running
  -> blocked | review_required | merge_ready
review_required
  -> changes_requested | held | merge_ready
merge_ready
  -> merge_queued -> merged_apply_pending
merged_apply_pending
  -> applying -> applied
               -> apply_failed -> superseded/retried
```

Terminal states are `applied`, `rejected`, `cancelled`, `abandoned`, and
`superseded`. `apply_failed` is deliberately non-terminal until reconciled or
superseded. Every transition is compare-and-set, append-only in the event log,
and mirrored to Slack/GitHub through delivery obligations.

### 7.7 Identity and approval semantics

GitHub documents that user-to-server requests by a GitHub App are attributed to
the authorizing user and are constrained by both the user's access and the
App's permissions. Use that mechanism for owner-attributed PRs, reviews,
comments, and branch operations. Use installation authentication only for
unattended App-owned maintenance.

Because GitHub sees the API actor but cannot know whether an owner clicked a
Slack approval button or their agent autonomously submitted a review, the
custom ledger review record is the source of quorum truth:

```text
GitHub actor: octocat
Programmatic access: Forecasting GitHub App
Human owner: owner_123
Agent persona: "Mira Markets" / custom Slack avatar
Agent instance: instance_abc
Actor kind: agent
Intent source: slack-agent-run run_456
Quorum credit: none
```

A human Slack button action for the same owner has `actor_kind=human`, a signed
interaction receipt, and may receive quorum credit if the owner is eligible.
This record binds to the digest and head SHA and is mirrored as a GitHub review.

### 7.8 Default risk policy

| Tier | Default examples | Promotion rule |
| --- | --- | --- |
| Low | prose/doc changes, safe transcript attachment, evidence metadata that does not change probability or criteria | Required checks; automatic merge/apply allowed |
| Medium | ordinary active forecast update below the default 10 percentage-point materiality threshold; assumption/reference-class edits | Checks + one eligible non-author human |
| High | criteria, resolution, protected forecast, lesson activation, >=10pp move, policy change, mixed changeset containing any high-risk operation | Checks + two eligible non-author humans, including owner/steward |

The 10pp threshold is an initial configurable default, not a claim of universal
materiality. Existing forecast hooks may raise risk or block a proposal. A
workspace cannot configure protected operation kinds below their built-in tier.

### 7.9 Transcript policy

Private raw archive and GitHub-safe transcript are different artifacts:

| Property | Private archive | Review-safe transcript |
| --- | --- | --- |
| Location | encrypted object store | ledger artifact and optionally Git |
| Contents | full trace available to the system | scoped requests, visible conclusions, decision records, terse tool/test summaries |
| Raw provider reasoning | may be retained if returned | excluded |
| System/developer prompts | encrypted private only | excluded |
| Consent to GitHub | not applicable; private retention policy | explicit per digest/repository |
| Default retention | 90 days | durable |
| Secret failure | remains encrypted/private | fail closed; publish nothing |

The review-safe artifact should copy the OpenClaw skill's operational qualities
without copying its runtime: local discovery, deterministic rendering, safe
preview, marker-based PR updates, secret failure, and graceful absence. Decision
records provide detailed reviewable rationale; they are not hidden
chain-of-thought.

### 7.10 Slack visibility and liveness

The thread status card is a projection of durable control-plane state. Suggested
fields:

```text
Changeset C-1042 · 3 forecasts · Medium risk
Working: Mira (agent for @Theodore) — checking evidence freshness
Branch: forecast/C-1042 · PR #88 (draft)
Checks: 6/8 passed · transcript safe · ledger preview current
Review: 0/1 human approvals
Last activity: 18s ago · next update expected within 45s
[View diff] [Preview transcript] [Approve] [Request changes] [Hold]
```

Progress events should be semantic and rate-limited: phase start/finish, active
tool category, heartbeat, wait reason, queue position, and expected next action.
Do not expose raw reasoning or tool arguments in liveness updates.

Socket Mode must acknowledge envelope IDs and tolerate refresh/reconnect. Signed
HTTP must validate signatures and return quickly after durable receipt. Both
transports feed identical event and action handlers.

### 7.11 GitHub review controls

Recommended repository ruleset:

- require a pull request for the default branch;
- block force pushes and branch deletion;
- require the App-sourced `ledger/promotion` check;
- require conversations resolved;
- dismiss stale approvals or require approval of the latest reviewable push;
- require CODEOWNER/team review for protected policy paths;
- use a merge queue for high-concurrency hosted workspaces;
- restrict bypass to a break-glass administrator role.

GitHub's ruleset is defense in depth. The apply service independently verifies
the exact head/merge SHA and its own quorum record.

### 7.12 Failure and recovery rules

- **GitHub unavailable:** continue local Slack research and changeset creation;
  show `publication delayed`; do not promote.
- **Slack unavailable:** continue already authorized GitHub checks/apply; persist
  Slack delivery obligations and replay status on reconnect.
- **Control-plane restart:** restore active runs/events, reacquire leases, and
  reconcile branches/PRs before accepting promotion.
- **Stale base revision:** block merge-ready state, rebase by creating a fresh
  preview/commit, and stale approvals.
- **Merge succeeded, apply failed:** keep `merged_apply_pending/apply_failed`,
  block later conflicting application, retry transient failure, and create a
  superseding changeset for semantic conflict.
- **Repository drift:** regenerate from ledger into a repair branch; never make
  the ledger match an unverified direct push.
- **Token revoked:** stop owner-attributed writes immediately; retain read-only
  status and request relink.
- **Unsafe transcript:** withhold transcript, retain private bundle, and permit
  policy evaluation using decision records.
- **Sandbox deleted:** recreate from the branch and durable changeset metadata;
  no credential recovery is necessary inside the pod.

### 7.13 Rollout sequence

1. **Foundation:** US-001 through US-008 behind a disabled feature flag.
2. **Provenance:** US-009 through US-013 with local encrypted filesystem object
   storage and no GitHub publication.
3. **Portable workspace:** US-014 through US-018, including round-trip bootstrap.
4. **GitHub beta:** US-019 through US-026 for one canonical private repository,
   no automatic merge initially.
5. **Slack multiplayer beta:** US-027 through US-032 with Socket/HTTP parity and
   human-only promotion.
6. **Policy automation:** enable low-risk auto-promotion after shadow-mode data
   shows no false-low classifications or hook bypasses.
7. **Hosted general availability:** US-033 through US-037, Postgres/object-store
   adapters, reconciliation, threat review, and operating documentation.

Risk classification must run in shadow mode before it is permitted to
auto-promote. During shadow mode the system records what it would have promoted
and compares that decision with actual human review outcomes.

### 7.14 External platform contracts

- [GitHub App user-to-server authentication](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-with-a-github-app-on-behalf-of-a-user)
- [GitHub repository ruleset controls](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
- [GitHub merge queues](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)
- [Slack message metadata](https://docs.slack.dev/messaging/message-metadata/)
- [Slack Socket Mode](https://docs.slack.dev/apis/events-api/using-socket-mode/)
- [Slack Events API acknowledgement and retries](https://docs.slack.dev/apis/events-api/)
- [OpenClaw agent-transcript skill](https://github.com/openclaw/openclaw/blob/main/.agents/skills/agent-transcript/SKILL.md)

## 8. Success Metrics

### Correctness and safety

- Zero duplicate ledger snapshots from webhook or apply retries in acceptance and
  production telemetry.
- Zero ledger writes from a merged changeset that fails digest, base revision,
  hook, or quorum validation.
- 100% of applied changesets link to a provenance bundle and immutable digest.
- 100% of human-quorum votes bind to a current digest/head SHA and linked human
  identity.
- Zero raw traces, secrets, OAuth tokens, system prompts, or raw provider
  reasoning detected in repository fixtures and release scans.
- A fresh bootstrap reproduces the same portable revision and digest in all
  round-trip fixtures.

### Collaboration and liveness

- 95% of accepted Slack/GitHub events appear in the durable event store within
  one second under normal load.
- Status-card heartbeat or explicit wait state remains newer than 60 seconds for
  99% of active executions.
- GitHub-to-Slack terminal-state propagation p95 is under 10 seconds, excluding
  upstream outage.
- At least 90% of review actions can be completed from Slack without opening a
  terminal.
- Fewer than 1% of changesets require manual state repair after process restart.

### Governance and automation

- Low-risk classifier runs in shadow mode for at least 200 changesets or 30 days
  before automatic promotion is enabled.
- Shadow-mode false-low rate is zero for protected operation kinds and below the
  administrator-agreed threshold for all other operations.
- After activation, at least 80% of eligible low-risk changesets promote without
  human interaction.
- Median medium-risk time from review request to human decision is measurable by
  workspace and visible to administrators.
- Every high-risk promotion includes two distinct qualifying human approvals,
  including the required owner/steward.

### Retention and operations

- 99.9% of unpinned raw traces are deleted within 24 hours after their 90-day
  deadline.
- 100% of raw-trace reads and holds have an access event.
- Merged-to-ledger-apply p95 is under 30 seconds when the ledger and GitHub are
  healthy.
- Every `apply_failed` state creates an alert and safe remediation path within
  one reconciliation interval.

## 9. Open Questions

No product decision is blocking implementation. The following are deployment or
tuning decisions with safe defaults:

- Use 10 percentage points as the initial medium/high probability materiality
  boundary, configurable per workspace and forecast protection policy.
- Use encrypted local filesystem blobs for development and an S3-compatible
  object store with KMS envelope encryption for hosted production.
- Support GitHub.com first; keep API/upload base URLs configurable for a later
  GitHub Enterprise Server compatibility pass.
- Begin with one canonical private repository per workspace. Public repositories
  require an additional evidence-licensing and privacy review before enablement.
- Store portable evidence metadata and bounded excerpts by default; full source
  archives require a separate licensed artifact-store policy.
- Require per-artifact transcript consent initially. A future workspace-wide
  preauthorization policy may be considered only after a privacy review and must
  remain revocable.

[/PRD]
