# Research runtime capability implementation

Scope: the six requested upstream capabilities plus MCP issuer binding. This is
an implementation checklist, not a replacement for the non-blocking platform
qualification backlog in TODO.md. Upstream reference: `5eb99eb284`.

## Acceptance

- [ ] Progressive tool discovery: selected optional tools behind scoped
  search/describe/call; core forecasts and clarification remain direct. Validate
  arguments and permissions through existing dispatch, preserve batching and
  cancellation, test dynamic selection and cross-session isolation.
- [ ] Context continuity: durable provider-usage anchors, estimate additions,
  invalidate on history/model/schema changes; preserve forecast identifiers,
  source references and unresolved assumptions at compaction; runnable recall
  evaluation with an uncompacted control and synthetic fixtures.
- [ ] Persistent Python kernels: opt-in session state with explicit reset,
  reproducible calculation records, per-cell permissions/budgets, timeout and
  cancellation teardown, parent death and profile/owner isolation. Exercise real
  execution and the supported local/remote execution boundaries.
- [ ] Background research: batch admission, independent and grouped completion,
  early failures, durable/display truthfulness, cancellation and resource cleanup
  including partial admission and interrupted parent execution.
- [ ] Event research jobs: authenticated webhook binding to existing jobs using
  shared claims/execution; delivery deduplication, no stored-prompt mutation, no
  silent active-forecast probability changes. Exercise real HTTP and fake runs.
- [ ] Repeated result references: still execute tools, compact only identical
  successful large results, retain resolvable originals and fresh observations;
  preserve transcript replay, error/polling behavior and provider call ordering.
- [ ] MCP issuer binding: pin refresh grants, reject issuer/endpoint changes,
  explicit legacy handling, both construction paths, concurrent writes and
  profile isolation; verify refresh requests with controlled providers.
- [ ] Directory guides, configuration/reference documentation and upstream
  provenance updated. Strict gates cover new owners. Canonical full suite passes
  before publication; merged tree matches the tested tree.

## Progress

Implementation branch: `feat/research-runtime-capabilities`. No capability is
complete until its wiring and boundary tests demonstrate the acceptance above.

### First implementation milestone

- MCP binding is enforced in the shared managed and compatibility provider.
  Legacy/mismatched grants fail closed; access tokens survive; binding includes
  the token endpoint. Storage captures its profile and stale cleanup compares
  the whole loaded record before removal. Non-rotating refreshes preserve grants.
  Focused MCP regression set: 85 passed, then 10 binding cases passed including
  replacement grants reusing the same refresh token. Full suite remains pending.
- Repeated-result references are wired into both executor paths. Every call
  executes; references require an original still present in history. Changed,
  failed, pruned, edited and multimodal results remain whole. Runtime tests
  exercise sequential/concurrent calls and closed/reopened database replay.
  Focused reference/guardrail set: 32 passed. Full suite remains pending.
- Actual agent delegation dispatch now forwards images and background mode;
  previous direct tool tests did not cover this missing dispatcher wiring.
