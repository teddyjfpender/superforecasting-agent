---
title: Hosted Slack execution architecture
description: Durable Slack runs, isolated sandboxes, and extensions.
---

# Hosted Slack execution architecture

Superforecasting Agent keeps the forecast ledger and execution state in the
control plane while treating chat transports and execution sandboxes as
replaceable adapters. This borrows Centaur's useful boundaries without making
Centaur a runtime dependency.

```text
Slack Socket Mode ─┐
                   ├─ verified ingress ─ durable run/event store ─ agent runtime
Slack signed HTTP ─┘                           │                    ├─ local
                                               │                    └─ Kubernetes pod / thread
                                               └─ Slack renderer (progress + final)
```

## Slack transport and liveness

Set exactly one transport for a workspace:

```yaml
slack:
  transport: socket  # socket | webhook
```

`socket` uses Slack Socket Mode and requires the app-level token. `webhook`
accepts Slack-signed requests at `/api/webhooks/slack` (the compatibility path
`/slack/events` also works) and requires `SLACK_SIGNING_SECRET`. Both ingress
paths normalize into the same Slack adapter, authorization rules, thread
identity, commands, approvals, and renderer.

The webhook verifies and durably records a delivery before acknowledging it,
then runs the agent asynchronously. A persistence failure returns `503` so
Slack retries instead of losing the turn. The
Slack event or trigger ID is persisted as the client message ID, so Slack
redelivery cannot create a second turn. Do not put API-key middleware in front
of the Slack webhook; Slack's timestamped signature is its authentication.

Slack defaults to `display.platforms.slack.tool_progress: new`: one editable
progress message changes when the active tool changes. Long-run heartbeat text
updates that same message instead of adding permanent thread noise. The final
answer remains a separate durable Slack message.

## Durable execution state

`gateway.execution_store.ExecutionStore` owns threads, inbound messages, runs,
append-only events, and delivery obligations. SQLite/WAL is the default for a
single local control-plane process. The `/v1/runs` status and SSE event APIs
read this store, so reconnecting clients replay events by `event_id` after a
process restart. Live queues only wake connected clients; they are not the
source of truth.

The schema enforces one active execution per thread and unique idempotency keys.
Terminal runs can be pruned without deleting active work. A multi-replica
deployment should implement the same store contract on Postgres before scaling
the API horizontally.

## Conversation sandboxes

`gateway.sandbox_runtime.KubernetesSandboxRuntime` maps the durable conversation
key to a deterministic pod name. For Slack that key includes workspace,
channel, and thread timestamp, so separate threads never share a workspace.

The generated pod:

- runs non-root with the runtime-default seccomp profile;
- drops every Linux capability and forbids privilege escalation;
- uses a read-only root filesystem and bounded `emptyDir` workspace;
- disables service-account token mounting and Kubernetes service links;
- contains no raw credential environment variables or Secret mounts.

The gateway uses argv-only `kubectl` operations to ensure, execute in, or delete
the pod. Production deployments should add a namespace default-deny
NetworkPolicy, allow only the credential proxy and required control-plane
endpoints, pin the sandbox image by digest, and run a TTL reconciler using
`hosted_execution.kubernetes.idle_ttl_seconds`.

`hosted_execution.runtime` remains `local` by default. Selecting Kubernetes for
the whole agent loop requires a deployed worker image and control-plane worker
protocol; the sandbox controller is the shared lifecycle/security primitive,
not an implicit switch that creates unused pods.

## Credentials

Hosted tools declare `CredentialRequirement` entries when registering. A
binding identifies the secret's control-plane environment variable, exact
HTTPS hosts, allowed path prefixes, outbound header, and value prefix.

`gateway.credential_broker.CredentialBroker` rejects undeclared tools,
credentials, hosts, paths, ports, plaintext HTTP, userinfo, and attempts by a
worker to supply the protected header. It injects the real value only while
constructing the trusted outbound request. Tool results and pod manifests must
never contain that value.

This policy object is intentionally transport-neutral. In a cluster, expose it
behind a sandbox-authenticated proxy and combine it with egress NetworkPolicy;
the policy alone does not prevent a compromised sandbox from bypassing the
proxy when unrestricted egress is available.

## Ordered Git extensions

Organization-specific behavior belongs outside core:

```yaml
extensions:
  sources:
    - repo: your-org/forecasting-overlay
      ref: 0123456789abcdef0123456789abcdef01234567
```

Sources are resolved in order into the active forecast home. Synchronization
checks out the requested revision detached, records the resolved 40-character
commit in `extensions.lock.json`, removes Git metadata and the origin URL, and
replaces the active checkout with rollback if activation fails. Existing Git credential helpers may
authenticate private clones; tokens are never added to command arguments.

An overlay may contain:

```text
plugins/       # normal Superforecasting Agent plugin manifests and Python tools
workflows/     # ordered workflow definitions for workflow consumers
skills/        # bundled skill directories (.agents/skills is also accepted)
prompts/*.md   # ordered organization system-prompt fragments
```

Later extension plugins override earlier extension plugins; user and project
plugins retain higher precedence. Skills join normal skill discovery. Prompt
fragments are filename-sorted within each source, size-bounded, threat-scanned,
and added after the forecast-desk identity rather than replacing it. Workflow
paths are exposed through `get_extension_surface_paths("workflows")`; a workflow
runtime must consume them explicitly instead of executing arbitrary files at
discovery time.

Use commit SHAs for reproducible hosted deployments. Tracking a branch is
appropriate only when operators intentionally want new processes to pick up
the branch's latest revision.
