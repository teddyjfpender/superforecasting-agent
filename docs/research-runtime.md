# Research runtime

Use these capabilities from the forecasting conversation in the TUI or CLI.
The agent owns tool invocation; the forecast ledger remains the authority for
questions, evidence, probabilities and scored outcomes.

## Find optional tools without loading every schema

Progressive discovery is enabled by default. Forecast and clarification tools
remain directly available. The agent searches selected optional tools, inspects
their schemas and invokes them through the normal permission checks. Discovery
does not install tools or grant access to disabled tools.

To keep an additional selected tool directly visible, configure the active profile:

```yaml
tool_discovery:
  enabled: true
  direct_tools: []
  listing_chars: 8000
```

Restart the agent after changing these settings. See the
[tooling guide](../superforecasting_agent/tooling/README.md#progressive-discovery)
for limits and batch behavior.

## Keep a calculation alive across research steps

Persistent Python is opt-in:

```yaml
code_execution:
  kernel_mode: session
```

Ask the agent to load observations once, then reuse them for sensitivity analyses
or alternative distributions. Successive `execute_code` calls retain variables.
An explicit `reset: true` starts a new interpreter; changing tool authority,
interpreter or working directory also requires reset.

Cells must finish their threads and subprocesses. Cancellation, deadlines and
unfinished cell work retire the interpreter. Agent shutdown closes it; restarting
the application does not restore Python variables.

Each calculation records code, runtime metadata, inputs and results under the
active profile's `calculations/` directory. Inspect an archive without executing it:

```sh
python -m tools.code_calculations verify /path/to/kernel-directory
```

The [calculation guide](../tools/README.md#persistent-analysis)
explains explicit replay. Replay executes trusted Python: recorded tool responses
are frozen, but direct file/network access and randomness are not.

## Receive independent findings while research continues

The agent can call `delegate_task` with `background: true` and a `tasks` array.
Tasks without `delivery_group` return independently. Tasks with the same group
name produce a combined result after all members finish; a failed member is
reported early. This is useful when independent source checks can inform the
parent before a slower comparison finishes.

The batch, results and receiving turns are durable. Delivery remains bound to the
originating profile and session. `/background` shows owned work; cancellation and
cleanup are distinct from successful completion. Interrupted receiving turns need
review before resubmission because tools may already have run. CLI resume displays
the saved request and partial response; the TUI uses durable recovery state.

Linux owner identity uses the boot and PID namespace, independent of network
interfaces. Records from an earlier boot, another namespace, or the previous
identity format remain unconfirmed; they never authorize automatic reexecution.
When local identity cannot be established, new durable work fails closed.

## Start saved research when a source publishes

Configure an authenticated webhook route under
`platforms.webhook.extra.routes`. Set `cron_job` to an existing exact job ID and,
optionally, `profile` to its owning profile. Send a signed request with a stable
`X-Request-ID` or `X-GitHub-Delivery` value. The target profile needs an active
scheduler: HTTP 202 means durably queued, not completed.

The saved job supplies the prompt and execution policy. Repeating a delivery is
idempotent; changing its body or target conflicts. Disabled, deleted or paused
jobs are refused before execution. Unattended work can add evidence and proposed
updates but cannot silently commit active forecast probabilities. See the
[scheduler guide](../cron/README.md#event-triggered-research) for recovery semantics.

## Understand continuity and authentication

- Context usage uses a persisted provider measurement plus estimates for newer
  material. Exact forecast identifiers, source references and unresolved assumptions
  survive compaction within a bounded index. The ledger and original transcript
  remain authoritative; the index can explicitly omit records when full.
- Repeated successful tool results can refer to a retained original. The tool still
  executes, and changed or failed observations remain explicit.
- MCP refresh tokens are bound to their issuer and token endpoint. Legacy unbound
  grants and changed issuers require reauthorization instead of sending a refresh
  token to a newly discovered destination.

The [agent guide](../agent/README.md#context-continuity) includes the runnable recall
comparison. Its synthetic regression results do not establish improved forecasting
accuracy. Implementation acceptance and platform evidence are recorded in the
[research runtime plan](plans/2026-09-14-research-runtime.md).
