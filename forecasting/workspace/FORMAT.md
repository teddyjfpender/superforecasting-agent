# Portable forecast workspace format v1

The runtime SQLite ledger is authoritative. This repository is a deterministic,
reviewable projection used for backup, pull-request review, and reconstruction;
merging Git does not itself mutate the live ledger.

## Layout

```text
forecast-workspace.yaml          # identity, format, revision, file digests
.gitignore                       # excludes secrets, databases, traces, caches
ledger/revisions.json
ledger/questions/<id>.json
changesets/<id>/changeset.json   # operations and review attestations
documents/                       # portable document projections, when present
policies/review-policy.json
transcripts/<id>/manifest.json   # metadata/consent; content only when approved
attestations/<id>/contributors.json
attestations/<id>/provenance.json
attestations/<id>/decisions.json
extensions/lock.json             # ordered overlay refs, never credentials
```

Generated JSON is UTF-8 with sorted keys, two-space indentation, and one final
newline. Timestamps are normalized ledger values. Each manifest file digest is
SHA-256 over exact bytes; `content_digest` covers the canonical sorted mapping
of relative paths to those digests. See `schemas/` for JSON Schema definitions.

Validation is fail-closed for unsupported format versions, path traversal,
symlinks, binaries, oversized files, unexpected paths, databases, credentials,
secret-like content, malformed records, and broken nested attestations. Import
treats repository content only as data: it does not run workflows, extensions,
hooks, filters, submodules, or committed scripts.
