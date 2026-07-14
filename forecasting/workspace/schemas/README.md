# Forecast workspace schemas

`forecast-workspace-v1.schema.json` defines the portable repository manifest.
`portable-records-v1.schema.json` defines every generated JSON record type:
ledger revisions, question packets, changesets, contributor attestations,
provenance summaries, decision records, transcript manifests, review policy,
and the ordered extension lock.
Generated JSON uses UTF-8, sorted keys, two-space indentation, and one trailing
newline. Each manifest file digest is SHA-256 over its exact bytes; the manifest
`content_digest` is SHA-256 over the canonical sorted path-to-digest mapping.
Live databases, credentials, raw traces, caches, and unapproved source bodies
are outside this format.

Path-to-schema mapping is deterministic: `ledger/revisions.json` uses
`revisions`; `ledger/questions/*.json` uses `question`;
`changesets/*/changeset.json` uses `changeset`; files below `attestations/`
use `contributors`, `provenance`, or `decisions`; files below `transcripts/`
use `transcriptManifest`; and the policy/extension files use their same-named
definitions. The runtime validator also recomputes changeset, operation,
decision-record, contributor-attestation, manifest-file, and manifest-content
digests before bootstrap or publication.
