# Nix packaging

This directory builds the backend, terminal UI and dashboard as one immutable
package. Nix remains experimental and its CI jobs are informational; it is not
the supported beta installation route. See the
[beta scope](../website/docs/getting-started/beta-scope.md).

Linux x86-64 build and installation receipts are recorded in the
[qualification report](../docs/verification/2026-09-14-nix-qualification/README.md).
This does not promote Nix into the supported beta channel.

## Build and install

From a checkout, with flakes and the `nix-command` feature enabled:

```sh
nix run .#fix-lockfiles -- --check
nix build --print-build-logs
nix flake check --print-build-logs
nix profile install .#superforecasting-agent
superforecasting-agent version
superforecasting-agent tui
```

The profile contains immutable application files. User configuration and the
forecast ledger remain in the active Superforecasting Agent home. Configure a
provider through the normal setup flow; never bake credentials into a derivation.
For NixOS-managed configuration, use the module rather than editing generated files.

## Ownership

| File | Responsibility |
| --- | --- |
| `packages.nix` | Public packages and runnable application entrypoints |
| `superforecasting-agent.nix` | Runtime wrappers, bundled assets and package overrides |
| `python.nix` | Locked Python environment and platform-specific dependency overrides |
| `tui.nix`, `web.nix` | Frontend builds and fixed-output npm dependency hashes |
| `lib.nix` | Shared npm hash-maintenance integration |
| `checks.nix` | Package contents, configuration, extension and synthetic lifecycle checks |
| `nixosModules.nix`, `configMergeScript.nix` | Declarative service and configuration integration |
| `overlays.nix`, `devShell.nix` | Overlay exports and development environment |
| `hermes-agent.nix` | Compatibility adapter for the inherited package name |

## Updating dependencies

After changing an npm lockfile, run `nix run .#fix-lockfiles`, inspect the two
frontend hash changes, and rebuild. A successful hash refresh only proves the
fetched dependency input matches; it does not qualify the application build.
Keep `flake.lock` and `uv.lock` changes deliberate and reviewable.

The Linux checks exercise the installed CLI through create, research, update,
resolve, scoring and postmortem without provider credentials. The fixture is
marked calibration-ineligible and never measures forecasting skill.
Cross-platform evaluation is distinct from installation evidence: do not infer
macOS or ARM installation support from successful evaluation alone.
