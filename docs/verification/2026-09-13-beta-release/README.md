# Beta release verification

## Scope and owners

Backend 0.22.1 and terminal 0.1.1 are published together through
`production-release.yml`. Tag-triggered runs default to beta; stable publication
requires an explicit `channel=stable` dispatch. Beta releases never advance
GitHub or container `latest` aliases. Publication waits for six native jobs to
verify checksummed draft downloads, fresh installations, historical upgrades,
profile/skill/plugin migrations and terminal recovery.

## Dependency remediation

The 28 previously open alerts affected these lockfiles. All four now report zero
npm audit vulnerabilities; counts describe registry audit coverage, not a security
proof or live qualification of optional integrations.

| Owner | Exposure | Remediation |
| --- | --- | --- |
| `ui-tui` | Development dependencies (ESLint YAML parsing, Vitest/mocker and filesystem tooling); not the bundled runtime dependency graph | Compatible lockfile updates |
| `web` | Dashboard dependency graph, including HTML sanitization and color parsing; YAML is build tooling | Compatible lockfile updates |
| `website` | Documentation build/dev server dependencies, including SVG processing, YAML, URI parsing, browser queries and request parsing | Compatible updates and `qs` 6.16.0 override for Express's older transitive pin |
| `scripts/whatsapp-bridge` | Optional runtime, including native image processing and Express request parsing | Compatible updates and the same patched `qs` override |

Run `npm audit` from each directory to reproduce the registry check. The bridge
remains outside supported beta scope; dependency remediation does not qualify a
live messaging integration.

## CI diagnosis

- Bedrock tests imported an SDK absent from the full-test dependency group; the
  group now includes the bounded SDK pin already used by the Bedrock extra.
- The Copilot removal test patched a compatibility module after production code
  moved to the canonical credential owner. Its resolver is now patched where used.
- CI bypassed the canonical test runner and omitted terminal dependencies. Shared
  isolation, bounded workers and current TUI builds now apply in CI as locally.
- Windows checks flagged intentionally Linux-only TLS cleanup and guarded alarm
  access. The Linux restriction is explicit; optional signal lookup is portable.
- Nix built the package but failed its version-content check. Capture complete
  output before matching to avoid early-reader pipe termination and expose actual
  errors. Nix remains experimental for this beta; dependency updates also require
  refreshed Nix fixed-output hashes before a new Nix qualification claim.

## Release evidence

Publication receipts and final artifact checksums will be linked here after the
formal workflow completes. Existing candidate artifacts are not release evidence.
