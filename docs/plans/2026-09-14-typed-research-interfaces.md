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

The actual local terminal/gateway/dashboard recovery group passed all 25 tests,
including cancellation, process interruption, handoff and reconnect. Focused
contract/application/market tests passed; the final whole-repository receipt is
reported with the publishing commit, rather than retaining intermediate logs here.

The final gate is `PATH="$PWD/.venv/bin:$PATH" PYTHONPATH="$PWD:$PWD/scripts" git push`, whose
pre-push hook runs canonical quality checks, the full Python suite and affected TUI
tests against the committed tree. Native Windows/Linux qualification is separate
from this macOS receipt.

## Explicit limits

Outstanding prompt restoration requires the existing backend session to remain
alive; secrets and unanswered prompts are not persisted through backend death.
An old approval client that supplies no request ID retains its historical FIFO
semantics. Review cost savings require real provider usage measurements; no savings
are claimed by configuration or mock tests alone.
