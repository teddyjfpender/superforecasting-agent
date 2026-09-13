# Installed upgrade and migration qualification

The [local receipt](macos-arm64.json) records a successful macOS ARM64 run using
Python 3.13.12. Artifact hashes identify the tested 0.22.1 backend and 0.1.1
terminal; this receipt does not claim those pre-existing wheels contain later
command-dispatch changes.

## Inputs and checks

The backend baseline is the published 0.19.0 wheel, verified against its pinned
SHA-256. The terminal baseline is built from the historical source revision in
[baseline provenance](baselines.json), including that revision's Ink source.
It is a historical build of 0.1.0, not a claimed published terminal release.

The installed old backend creates the question, evidence, probability history,
session and configuration. It also synchronizes the actual bundled skills and
loads an explicitly enabled user plugin using its legacy token-storage import.
After customization and deletion of selected skills, the candidate upgrade must:

- Preserve forecast, evidence, session and configuration records.
- Move an unchanged bundled skill to its canonical path.
- Preserve the customized skill without creating a competing canonical copy.
- Respect deletion intent and keep repeated synchronization idempotent.
- Preserve the legacy profile context and user plugin files, and execute the plugin.
- Complete the forecast lifecycle and installed worker checks without Node.
- Exercise the old and upgraded local terminals, authenticated host reconnects,
  the upgraded remote terminal, and shutdown.

## Repeatable native matrix

[Product quality](../../../.github/workflows/product-quality.yml) runs fresh
installation and upgrade verification separately on Linux x86-64, Windows AMD64
and macOS ARM64 with Node 20 and 22. Each job uploads both reports and baseline
provenance, including failures. Workflow configuration alone is not a qualification
receipt; successful native runs must be inspected before claiming their coverage.

From a contributor environment, build current products and prepare baselines:

```sh
python3 scripts/build_profiles.py --out dist/qualification-products
python3 scripts/prepare_upgrade_baselines.py
python3 scripts/verify_profiles.py dist/qualification-products \
  --python .venv/bin/python \
  --upgrade-from dist/upgrade-baselines/superforecasting_agent-0.19.0-py3-none-any.whl \
  --terminal-upgrade-from dist/upgrade-baselines/superforecasting_agent_tui-0.1.0-py3-none-any.whl \
  --report qualification/upgrade-report.json
```

Use the native interpreter path on Windows. The baseline builder fetches a pinned
Git commit and downloads the checksum-verified release wheel. It does not modify
the active user profile or publish packages.
