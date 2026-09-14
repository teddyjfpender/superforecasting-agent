# Shared interfaces and research controls

The five requested improvements are implemented on `feat/typed-research-interfaces`,
based on `b74bc62a3b`. The current reference is
[research runtime controls](../architecture/research-runtime-controls.md).

## Delivered behavior

- Python-owned method, parameter and result declarations generate the TypeScript
  client contract. Bundled-method completeness and negative compiler examples
  prevent arbitrary method names and caller-selected result types. Successful
  contract disagreements fail tests and return an internal error in production.
  Existing shared application errors retain their public diagnostics.
- Clarification, secrets, sudo and approval share correlated server requests.
  Transport ownership, cancellation, duplicate rejection and outstanding-request
  restoration support reconnects, with adapters for older clients.
- Background memory/skill review has separate provider, model, reasoning,
  iteration and output budgets, without changing cancellation ownership or
  treating maintenance as scored calibration lessons.
- MCP finite bodies and individual SSE events are capped at 10 MiB before SDK
  parsing. The HTTP client retains TLS, proxy, authentication and cleanup ownership.
- Manual model selection shares a measured-context cache-cost notice across
  CLI, TUI and messaging. Automatic failure recovery remains unobstructed.

## Qualification

Implementation preceded the consolidated verification pass. Strict validation
exposed and corrected timestamp/count declarations, reforecast payloads, completion
text serialization, and old tests that supplied incomplete wire fixtures.

Final qualification on macOS:

- Canonical Python suite at `645948a655`: **32,432 passed, 150 skipped**
  (519.51 seconds).
- Full TUI suite after the Ctrl+C prompt-action consolidation: **2,100 passed,
  one skipped**, across 192 files.
- Actual local terminal/gateway/dashboard recovery after that consolidation:
  **25 passed**, including cancellation, process interruption, handoff and reconnect.
- Blocking lint, formatting, typing, generated-contract drift and 76 architecture
  contracts passed.

The push-time run also exposed inherited Git hook environment leaking into
fixture repositories. The canonical runner now clears repository-local Git
variables and selects this checkout's interpreter/import paths. Regression fixtures
cover that isolation; accidental fixture metadata was removed from the worktree.

The final follow-up changes only TUI code and this receipt. Its push reuses the full
Python receipt above, with the repeated frontend and native recovery checks, instead
of repeating the unchanged Python suite. Native Windows/Linux qualification remains
separate from this macOS receipt.

## Explicit limits

Outstanding prompt restoration requires the existing backend session to remain
alive; secrets and unanswered prompts are not persisted through backend death.
An old approval client that supplies no request ID retains its historical FIFO
semantics. Review cost savings require real provider usage measurements; no savings
are claimed by configuration or mock tests alone.
