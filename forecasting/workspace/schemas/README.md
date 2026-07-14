# Forecast workspace schemas

`forecast-workspace-v1.schema.json` defines the portable repository manifest.
Generated JSON uses UTF-8, sorted keys, two-space indentation, and one trailing
newline. Each manifest file digest is SHA-256 over its exact bytes; the manifest
`content_digest` is SHA-256 over the canonical sorted path-to-digest mapping.
Live databases, credentials, raw traces, caches, and unapproved source bodies
are outside this format.
