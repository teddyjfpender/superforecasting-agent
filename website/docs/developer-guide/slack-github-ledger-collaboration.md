---
title: Slack and GitHub ledger collaboration
description: Deploy, govern, and recover multiplayer forecast review.
---

# Slack and GitHub ledger collaboration

This mode gives one Slack thread one durable forecast changeset and one isolated
execution context. Slack owns interaction and liveness, GitHub owns branch and
review collaboration, and the forecast ledger alone decides whether a merged
proposal is applied.

```text
Slack Socket Mode or signed HTTP
              │
              ▼
durable thread/run/card state ── one sandbox per thread
              │
              ├── delegated owner GitHub branch or verified owner fork
              └── draft PR + App check + human review
                                      │
                                      ▼
                          merge recorded, then ledger apply
```

A GitHub merge means that the review record was accepted. It does not mean the
ledger changed. The control plane validates the exact changeset digest, Git head,
base revision, policy check, decision record, and human quorum in one ledger
transaction before moving to `applied`.

## Deployment shapes

For local development, use Slack Socket Mode, SQLite/WAL, local execution, and a
private test repository. No public Slack endpoint is needed. The GitHub OAuth
callback and webhook still require a public HTTPS URL; a temporary HTTPS tunnel
is suitable for testing.

For a single hosted control plane, run one gateway/API process behind TLS with a
persistent forecast home and database backup. Signed Slack and GitHub webhook
routes must bypass generic API-key middleware because their timestamped/HMAC
signatures are their authentication. The handlers persist deliveries before
returning `202`.

For Kubernetes-hosted execution, keep the gateway, ledger, OAuth tokens, webhook
secrets, and credential broker outside worker pods. Configure
`hosted_execution.runtime: kubernetes`, a digest-pinned worker image, a dedicated
namespace, default-deny egress, and allow only required control-plane endpoints.
Pods run non-root without service-account tokens, Linux capabilities, writable
root filesystems, or raw GitHub credentials. See
[Hosted Slack execution architecture](./hosted-slack-execution.md) for the pod
security contract and ordered Git overlays.

Do not horizontally scale the SQLite control plane. Implement the existing
durable store contract on Postgres/object storage before adding API replicas.

## Core configuration

Non-secret configuration belongs in `~/.superforecasting-agent/config.yaml`:

```yaml
slack:
  transport: socket # socket or webhook; exactly one per workspace

collaboration:
  enabled: true
  github:
    enabled: true
    app_id: "123456"
    app_slug: "forecast-desk"
    client_id: "Iv1.example"
    public_base_url: "https://forecast.example.com"
    installation_begin_path: /api/install/github/begin
    installation_callback_path: /api/install/github/callback
    webhook_path: /api/webhooks/github
    oauth_callback_path: /api/oauth/github/callback
  repository:
    slug: acme/forecast-ledger
    workspace_id: global-desk
    default_branch: main
  review:
    materiality_threshold: 0.10
  discussion:
    max_comments: 12
    max_rounds: 6
    max_tokens: 16000
    max_elapsed_seconds: 1800
    max_concurrent_tasks: 2
    agent_loop_threshold: 4
    max_comment_bytes: 32768
  transcripts:
    raw_retention_days: 90
    require_publish_consent: true

hosted_execution:
  runtime: kubernetes
  kubernetes:
    namespace: superforecasting-agent
    image: registry.example.com/forecast-worker@sha256:...
```

Secrets belong in `~/.superforecasting-agent/.env` or the hosting platform's
secret manager:

```dotenv
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...                 # Socket Mode only
SLACK_SIGNING_SECRET=...                 # signed HTTP and interactivity
SLACK_CHANGESET_ACTION_SIGNING_KEY=...
GITHUB_APP_PRIVATE_KEY=...
GITHUB_APP_CLIENT_SECRET=...
GITHUB_WEBHOOK_SECRET=...
GITHUB_TOKEN_ENCRYPTION_KEY=...          # independent 32-byte key
GITHUB_CAPABILITY_SIGNING_KEY=...        # independent high-entropy key
FORECAST_TRACE_ENCRYPTION_KEY=...        # independent 32-byte key
```

Never reuse these keys. Rotate a compromised action/capability key immediately;
revoke delegated GitHub bindings and reinstall the App if user or installation
tokens may have escaped.

## GitHub App and repository governance

Grant the App only the repository permissions used by the control plane:

- Metadata: read
- Contents: read/write
- Pull requests: read/write
- Checks: read/write
- Issues: read/write, for PR discussion comments

Subscribe to `pull_request`, `pull_request_review`, `check_run`, `issue_comment`,
`merge_group`, `installation`, `installation_repositories`, and authorization
changes. Point the webhook
at `/api/webhooks/github` and the callback at
`/api/oauth/github/callback`. User-to-server OAuth uses PKCE; encrypted access and
refresh tokens remain in the control plane and are never returned to Slack or a
sandbox.

Set the GitHub App Setup URL to the public
`/api/install/github/callback` endpoint. Run
`superforecasting-agent github install` to open the App installation page,
select the exact canonical workspace repository, and then verify
`superforecasting-agent github status --json`. Signed installation webhooks bind
the immutable installation/App/account/repository IDs, repository selection,
and granted permission levels. Owner capabilities are issued only while both
the delegated user binding and this App-side repository grant are active.
Removing the repository, suspending/deleting the installation, or reducing a
required permission blocks new calls and is rechecked before an already-issued
capability can use the owner's token.
The installation URL carries a short-lived, single-use state value; the setup
callback succeeds only after the signed webhook has recorded that the returned
installation ID grants the exact configured repository.

Use a repository ruleset that:

- requires pull requests and resolved conversations;
- requires the exact `ledger/promotion` check produced by the configured App;
- blocks force pushes and branch deletion on the default branch;
- dismisses or invalidates approval after a new commit;
- optionally requires the merge queue and its `merge_group` check.

The App check is bound to the exact head SHA. A similarly named status from a
user, workflow, or different App does not satisfy ledger policy.

### Owner forks

If an owner can write a branch upstream, publication uses the canonical
repository. If GitHub denies the write, the control plane discovers or creates
`OWNER/REPOSITORY` with that owner's delegated token. It verifies the returned
immutable GitHub user ID, login, exact repository name, and upstream
parent/source before writing. The PR head becomes `OWNER:forecast/changesets/...`.

Fork writes use deterministic changeset branches and `force: false`; unrelated
owner branches are never rewritten. The canonical changeset ID and digest do not
change. Lost fork access moves publication to a recoverable blocked state on the
Slack card. Relink the owner's GitHub identity, restore access, and use a fresh
Open PR action.

## Slack setup and interaction contract

Socket Mode requires an app-level token with `connections:write`. The bot needs
the normal messaging scopes described in [Slack setup](../user-guide/messaging/slack.md),
including `chat:write`, channel/history access for the channels in scope,
`app_mentions:read`, `commands`, and `users:read`. Enable interactivity for both
transports.

Socket Mode and signed HTTP normalize into the same identity, authorization,
idempotency, card, and execution path. Duplicate deliveries from either route do
not create duplicate turns or ledger changes. After reconnect, the renderer
replays durable run/card state rather than trusting in-memory queues.

Each thread has one editable status card showing phase, active persona,
collaborator presence, heartbeat, affected forecasts, checks, quorum, next
action, and PR link. Tool progress edits that card; the final result is a
separate message. A stale heartbeat says `delayed / reconnecting`, not failed.
Publication failures render a safe recoverable action instead of exposing a
GitHub response body.

People appear in four separate identity layers: human owner, Slack user, Slack
agent persona/avatar, and immutable GitHub user. An owner's agent may commit and
comment through that owner's delegated GitHub token, but the attestation remains
`actor_kind: agent`; it never becomes human approval. Contributing owners cannot
self-approve their changes.

Autonomous PR discussion is control-plane governed. An agent can comment only
after assignment, mention, a policy request, or a failed check attributed to
its work. Every comment names the persona, human owner, model/run, and exact
changeset digest; the raw body is secret-scanned before publication and only its
digest is retained locally. Comment, round, token, elapsed-time, and concurrent
task budgets are enforced transactionally per changeset. When consecutive agent
turns reach `agent_loop_threshold`, the final comment asks for human direction,
the changeset moves to `held`, and the Slack card shows the same pause. A human
GitHub comment or review resets loop detection but does not replenish the other
per-changeset budgets. This comment-only coordinator cannot dismiss a human
change request, edit policy, or manufacture a human approval; fixes use the
existing owner-scoped branch capability.

## Transcript privacy and retention

Private raw traces and review-safe transcripts are different artifacts. Raw
traces are envelope-encrypted, never enter Git, and expire after 90 days by
default. Access requires an authorization decision, actor, and reason; allowed
and denied attempts are audited. A time-bounded pin needs a reason. An indefinite
pin requires an administrator legal hold.

Review-safe Markdown is scoped to explicitly linked sessions/runs and changed
objects. It omits system/developer prompts, provider reasoning, raw tool data,
environment values, credentials, auth URLs, broad local paths, and unrelated
turns. Secret detection fails closed and records only class/location.

Publishing safe content requires the initiating owner's consent bound to the
exact changeset, transcript digest, owner, and canonical destination repository.
A changed transcript requires new consent. Omission produces
`transcript_withheld_by_owner`; a safety or digest failure produces
`transcript_unavailable_safety_failure`. Neither erases private provenance or
blocks an otherwise valid low-risk proposal.

## Operator commands

```bash
superforecasting-agent workspace status --json
superforecasting-agent workspace pull --dry-run
superforecasting-agent workspace reconcile --apply-merged CHANGESET --dry-run
superforecasting-agent workspace reconcile --apply-merged CHANGESET --yes

superforecasting-agent github status --json
superforecasting-agent github install --json
superforecasting-agent github revoke BINDING --yes

superforecasting-agent changeset review-policy --json
superforecasting-agent changeset review-status [CHANGESET] --json
superforecasting-agent changeset preview CHANGESET --json
superforecasting-agent changeset retry CHANGESET --dry-run
superforecasting-agent changeset retry CHANGESET --yes
superforecasting-agent changeset transcript-retention --json
superforecasting-agent changeset transcript-retention --sweep --dry-run --json
superforecasting-agent changeset transcript-retention --sweep --yes --json
superforecasting-agent changeset transcript-access-audit --changeset-id CHANGESET --json
```

Status output distinguishes Git merge state from authoritative ledger apply
state. GitHub status never prints token ciphertext. Retention output excludes
object paths and trace bodies; access reasons are represented by a digest.

## Backup, recovery, and drift

Back up the active forecast database, private encrypted trace object directory,
`config.yaml`, secret-manager definitions, and the canonical Git repository.
Test restoration into staging. Never bootstrap directly over an existing ledger.
`workspace clone` validates every declared file, rejects symlinks, databases,
secrets, unsafe Git configuration, hooks, filters, submodules, and oversized
content, then reconstructs a new ledger and activates it atomically.

Common recovery paths:

| Condition | Safe action |
| --- | --- |
| Merged, apply pending | Restart the gateway or run `changeset retry ... --yes`; startup reconciliation is idempotent. |
| Transient apply failure | Retry up to the configured bound after repairing the dependency. |
| Semantic/stale-base failure | Do not force apply; create a superseding changeset against the current revision. |
| Repository projection drift | Inspect `workspace status`, then export authoritative ledger state with explicit confirmation. |
| Revoked/expired owner token | Reauthorize that owner; do not substitute another person's identity. |
| Lost fork permission | Restore/relink owner access and republish the same changeset digest. |
| Stale Slack card | Verify gateway health and durable state, then replay/update the card; do not create a second changeset. |
| Unsafe transcript | Withhold content, inspect the private safety finding, regenerate, and request fresh consent. |

The gateway retries only failures classified as transient and never
auto-resolves semantic conflicts. Webhook delivery IDs, action nonces, GitHub
origin markers, exact SHAs, and ledger apply-attempt records make restarts and
redelivery idempotent.

## Rollback and upgrade

Disable `collaboration.enabled` to stop new multiplayer changesets while keeping
the ledger and audit records readable. Switch `slack.transport` back to `socket`
to remove public Slack ingress, or `hosted_execution.runtime` to `local` to stop
creating Kubernetes sandboxes. Do not delete merged-but-unapplied records during
rollback.

When upgrading from the older multiplayer Slack/autopilot proposal flow:

1. Back up the database and forecast home.
2. Link/export the portable workspace and validate a clean bootstrap in staging.
3. Install the GitHub App and configure the App-sourced ruleset check.
4. Link each human owner through OAuth; do not map a shared bot token to owners.
5. Enable durable Slack cards for a test channel and exercise duplicate delivery,
   transcript omission, approval invalidation, merge, and apply.
6. Disable legacy silent proposal promotion only after the new ledger path is
   observed end to end.

During an incident, disable new ingress, preserve the database and signed
delivery/audit metadata, rotate affected keys, revoke tokens, inspect redacted
logs, and reconcile merged-but-unapplied changesets individually. Raw trace
access remains audited even during incident response.
