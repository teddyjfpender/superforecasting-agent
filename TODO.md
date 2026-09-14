# Engineering backlog

Completed work and verification receipts live in the
[implementation history](docs/plans/2026-09-13-todo-history.md).
The [ownership map](docs/architecture/ownership-map.md) defines current boundaries;
the [beta scope](website/docs/getting-started/beta-scope.md) defines supported products.

## Actionable maintenance

- [ ] Extend strict typing through remaining classic CLI and messaging shells
  when correcting concrete behavior. Shared owners are checked; the entire
  inherited orchestration modules are not yet strictly typed.
- [ ] Refresh Nix fixed-output hashes and qualify its package before proposing
  supported status or required merge checks. Nix is experimental and non-blocking.

## Qualification requiring external evidence

- [ ] Qualify a real Android/Termux device with installation, upgrade and recovery
  receipts. Desktop Linux or a Hetzner VPS cannot establish Android compatibility.
- [ ] Run Daytona/Modal integration checks with dedicated service credentials.
- [ ] Attribute the historical native SSL crash if original runtime/certificate
  artifacts or a credible reproducer become available. Existing native evidence
  did not reproduce it; original binary and CA hashes are absent.

## Maintenance rules

Prefer behavioral fixes over cosmetic file moves. New files in configuration,
storage, hosting, application, credentials and tooling receive strict checks
through `scripts/dev.py`. Run the canonical full suite before pushing.
Preserve forecast provenance and fail closed on unsupported source semantics.
Pending cancellation retains resource ownership until execution exits.

Live forecasting cohorts, settlements and learning evaluation belong in the
ledger and operational archive, not this engineering backlog.
