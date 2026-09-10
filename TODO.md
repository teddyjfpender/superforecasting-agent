# Remaining work

This is the follow-up list from the September 2026 repository cleanup. Completed
work and verification are recorded in the [cleanup review](docs/plans/2026-09-10-cleanup-review.md)
and its linked work log. These items are not claims of known production failures.

## Before a production release

- [ ] Verify the pushed commit's CI results, including platform jobs and release
  gates. Keep the tested commit and release artifact provenance together.
- [ ] Run the integration and end-to-end suites excluded by the default Python
  runner with their required services and credentials. Record skips explicitly.
- [ ] Exercise the documented installation and upgrade paths on native Windows,
  Linux/container, and Android/Termux. This pass verified macOS and a wheel
  installed outside the checkout; it did not establish cross-platform readiness.
- [ ] Smoke-test configured provider authentication, source fetching, and the
  forecast lifecycle against live services in a disposable profile. Local model
  and source fixtures establish transport and parsing behavior only.
- [ ] Build and publish the release through the release workflow after the above
  checks. A pushed source commit is not a published or deployed release.

## Continue modularization

- [ ] Decompose the remaining large classic CLI, runtime CLI, and messaging
  gateway responsibilities in bounded slices. Preserve public signatures,
  injected test seams, callback behavior, and wire responses.
- [ ] Continue splitting orchestration from parsing in remaining source adapters.
  Keep missing values distinct from zero and preserve provider outcome indices.
- [ ] Audit remaining repeated configuration/provider selection logic before
  consolidating it; similar-looking flows can have different persistence rules.
- [ ] Keep the ownership map and generated reference current as modules move.

## Identity and compatibility

- [ ] Review remaining inherited names by purpose: upstream attribution,
  external protocol/model identifiers, persisted data, or compatibility aliases.
  Migrate removable internal names; document any eventual alias removal before
  breaking existing installations. Do not rewrite third-party attribution.
- [ ] Reconcile older website guides and optional migration skills with the native
  runtime layout, without changing supported legacy-home migration behavior.
- [ ] Review the separate experimental terminal's product role and documentation;
  the Ink Forecast Desk remains the primary transcript and composer.

## Preserve the TUI and forecasting guarantees

- [ ] Include an installed-artifact TUI interaction in future release checks,
  alongside component tests, types, lint, and builds.
- [ ] Expand real-terminal coverage for resize, reconnect, Unicode, cancellation,
  session resume, and the dashboard PTY on supported platforms.
- [ ] Keep scheduled monitoring limited to evidence, alerts, scores, and learning
  records; probability changes must remain explicit forecast updates.
- [ ] Evaluate forecasting accuracy and calibration with scored resolved questions;
  passing software tests does not establish forecasting skill.
