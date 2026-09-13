# Current ownership map

This is the current implementation reference. Earlier extraction notes are retained
in [the architecture history](../plans/2026-09-13-ownership-history.md), not current
instructions. Contracts in `pyproject.toml` and `scripts/dev.py` enforce these boundaries.

| Capability | Owner | Consumer responsibilities |
| --- | --- | --- |
| Forecast models and settlement/scoring invariants | `forecasting/models.py`, `forecasting/ledger/` | Supply typed requests; never bypass ledger admission |
| Review, resolution, model building, triage | `forecasting/application/` | CLI and TUI render the same operation results |
| Source acquisition and watched-source dispatch | `forecasting/sources/` | Fetch separately from pure parsing and binding |
| Economic measurement parsing | `forecasting/economic_measurements.py` | Reject malformed numeric values and duplicate revisions |
| Source semantics and provenance | `forecasting/source_bindings.py`, `economic_bindings.py`, `settlement_binding.py`, `source_transfer.py` | Imported claims do not become locally verified by hashing alone |
| Shared command catalog and operations | `superforecasting_agent/application/` | Adapters provide session context, output and interactive prompts |
| Pure configuration/defaults/provider identity | `superforecasting_agent/configuration/` | Never persist an expanded runtime snapshot as raw configuration |
| Atomic configuration, auth and session storage | `superforecasting_agent/storage/` | Use the shared locked updater; preserve revisions and borrowed-secret policy |
| Credential discovery, refresh and token persistence | `superforecasting_agent/credentials/` | Interactive login remains in `runtime/auth.py`; credential services cannot import presentation/runtime |
| Host admission, workers, sessions and shutdown | `superforecasting_agent/hosting/` | Transports deliver events; host retains resources until durable finalization and disposal succeed |
| Snapshot restore and backup admission | `storage/snapshots.py`, `storage/profile_lease.py` | Offline restoration requires exclusive profile admission |
| Browser endpoint lifetime | `hosting/browser_sessions.py`, `browser_connection.py` | Drain active operations before replacement |
| Browser daemon identity and confirmed exit | `hosting/browser_processes.py` | Record identity at acquisition; never signal an unverified legacy PID |
| SDK and HTTP resource lifetime | `agent/openai_clients.py`, `agent/http_cleanup.py` | Dispose exact allocations; never sweep raw SDK sockets |
| Conversation batch lifetime and deadlines | `agent/conversation_lifecycle.py` | Cancel cooperatively, reject late results and retain running ownership |
| Shared tool support and cancellable hub HTTP | `superforecasting_agent/tooling/` | Carry cancellation context into source workers and check before publication |
| Agent construction and execution | `agent/agent_factory.py`, `agent/runtime.py` | `run_agent.py` is compatibility infrastructure |
| Versioned RPC contract | `protocol/` | Generate consumers; negotiate versions and required capabilities |
| TUI RPC transport | `tui_gateway/` | Consume shared operations; classic CLI imports and slash-worker fallback are forbidden |
| Terminal presentation | `ui-tui/` | Own transcript, composer, prompts and presentation state |
| Dashboard presentation | `superforecasting_agent/runtime/web_server.py`, `web/` | Embed the real TUI through PTY; supporting panels are separate consumers |
| Product entrypoints and distributions | `superforecasting_agent/`, `products/tui/` | Backend/CLI works without Node; terminal is independently installable |

Paths beginning `storage/` or `hosting/` in the table are relative to
`superforecasting_agent/`. Compatibility aliases remain supported, but new visible
copy uses Superforecasting Agent and the active forecast home. The
[compatibility reference](compatibility.md) identifies retained aliases and owners.

## Adding or changing a capability

1. Put validation and behavior in its domain/application owner before adding an
   interface handler. Reuse the existing command catalog and alias resolution.
2. Give each allocation a specific owner and release condition. On failure retain
   the exact handle and pending state; retries must not target replacements.
3. Keep fetching, parsing, semantic admission and ledger writes independently
   testable. A successful HTTP request is not proof of measurement meaning.
4. Change RPC declarations in `protocol/`, regenerate consumers and preserve
   negotiated capability behavior. Extend Ink for primary desk interactions.
5. Add a regression that exercises the violated invariant, including durable state
   and displayed state where a user-visible recovery path is affected.

## Contributor workflow

`python3 scripts/dev.py bootstrap` installs the environment and hooks and runs the
shared checks. `python3 scripts/dev.py check` runs lint, scoped formatting/types,
import contracts, generated protocol checks and TUI lint/types. Use
`scripts/run_tests.sh` for Python tests. Every push requires the full Python suite.

The direct forecasting-to-tool/runtime exception lists are empty. Transitive
application and credential contracts prohibit presentation imports. Strict coverage
is intentionally scoped for inherited code; these gates are not a claim that every
legacy module is fully typed or every platform is qualified.
