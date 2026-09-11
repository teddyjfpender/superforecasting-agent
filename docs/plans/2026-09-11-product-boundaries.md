# Product boundaries and repository hygiene delivery

Scope: all five deliverables in the user's attached objective. This is an active
implementation plan, not a claim that the existing layout satisfies them.

## Acceptance and authoritative evidence

- [ ] Domain, application, infrastructure, transport and product ownership is
  documented and enforced by import checks, including tests that introduce a
  forbidden edge and verify rejection.
- [ ] The real TUI and CLI consume shared review/resolution services, with typed
  inputs, consistent validation/defaults/errors and durable lifecycle behavior.
- [ ] Configuration and session operations have shared owners; TUI behavior does
  not depend on importing the classic CLI or constructing through run_agent.py.
- [ ] One documented fresh-checkout bootstrap/check workflow installs hooks and
  runs the same pinned quality gates locally and in CI. Gates include Python
  linting/formatting, scoped type checks, TypeScript checks, import boundaries and
  generated-contract checks. Legacy exceptions are explicit and may only shrink.
- [ ] Hosting owns profile configuration, credentials, sessions, workers and
  shutdown independently of presentation. Local and headless serving use the same
  operations with version/capability negotiation and tested incompatibility errors.
- [ ] Backend/CLI, TUI and optional integration distributions have explicit
  dependencies, clean-environment installation tests and compatibility checks.
  A minimal backend install needs no Node/TUI dependencies or bundled UI assets.
- [ ] Full behavior/regression qualification and end-to-end product checks pass;
  ownership docs and TODO are reconciled with actual current evidence.

## Implementation order

1. Extract the complete review/resolution workflow into `forecasting/application`;
   keep terminal output and argument parsing in product adapters, and consume the
   shared operations directly from structured TUI RPC.
2. Move configuration/session/agent construction ownership out of entrypoints and
   bind hosting to explicit shared services. Tighten import contracts as consumers
   migrate; compatibility facades must not own behavior.
3. Establish one quality command and bootstrap, reuse it from hooks and CI, and
   verify failure behavior. Enable useful lint/type/format coverage incrementally
   without silently treating tool failures as successful reports.
4. Version the host/client boundary and negotiate required capabilities for local
   and remote transports. Exercise isolation, reconnect and shutdown.
5. Separate distribution profiles and prove installation/use outside the checkout.

The monorepo is retained. Directory moves follow ownership changes. Existing
forecast settlement/scoring safety, ledger provenance, profile compatibility and
TUI-first presentation remain required throughout. Live forecasting, release
publication and historical SSL attribution are separate workstreams.

## Progress

Baseline: `c3c352325`. Existing six import contracts include legacy exceptions;
Ruff enforces only encoding; tracked hooks are not installed in this checkout.
No work in this plan is marked complete until its acceptance evidence exists.

First extraction in progress:

- `forecasting/application/reviews.py` owns selection and learned-error merging;
  the CLI calls it and retains only presentation.
- `forecasting/application/resolution.py` owns typed request admission and
  resolution/score/optional retrospective orchestration; the ledger remains the
  authority for settlement semantics, writes and durable finalization.
- Direct `forecast.review` / `forecast.resolve` RPCs return structured results
  without calling the classic CLI or redirecting process-wide stdout. The actual
  Ink command routing still needs migration to these endpoints.
- Cross-interface testing exposed binary retry identity differences (`"true"`
  versus `true`). The ledger now compares their meaning without rewriting the
  original stored outcome/provenance.
- Seven import contracts pass. Broader Ruff rules, formatting and ty pass on the
  application package. Those extra checks still need wiring into unified gates.
- Existing tracked hooks are installed (`core.hooksPath=.githooks`).
- Verification: 257 existing review/CLI tests passed after the first extraction;
  15 application/settlement/lifecycle tests passed after the retry fix. Full
  qualification is pending further integration, not claimed by these checks.

Hygiene audit finding: `ui-tui/eslint.config.mjs` defines five custom rules as
no-ops. Determine their intended enforcement and replace or remove misleading
rule declarations as part of the gate work; do not describe them as protection.

Shared quality workflow (`d5469e48c`):

- `python3 scripts/dev.py bootstrap` completed with exit 0 in a fresh local clone
  at `/tmp/forecast-product-bootstrap-20260911`, using its own `.venv` and
  `ui-tui/node_modules`. It built Ink, installed hooks, and passed all quality
  commands. The verification clone is clean afterward.
- Pre-commit/pre-push and `.github/workflows/product-quality.yml` call the same
  implementation. CI execution and native Windows bootstrap remain to verify.
- Missing-tool and failed-linter subprocess regressions pass; the pipeline fails
  closed. Six tests passed across those checks and application RPC parity.
- Injecting `import forecasting.cli` into the actual application package in the
  verification clone made the new import contract fail. The probe was restored.
- TUI lint passes after six existing gateway-client formatting findings were
  fixed. Five unused no-op custom rule declarations were removed; they were not
  active protections and should not have been advertised as such.

Still outstanding: actual Ink command migration, shared config/session and agent
construction ownership, fuller dependency-boundary cleanup, host/capability
negotiation, minimal independent package profiles, and full final qualification.
The two implementation commits are local pending the required full-suite push
qualification; this does not mark any of the five deliverables complete.
