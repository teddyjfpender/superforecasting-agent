# Feed message fixtures

`v1.json` is the transport-neutral `sfa.feed` snapshot used by Python schema
and TUI codec tests. It includes a negative reading and a missing period.
Snapshots are claims from a sender, not verified settlement evidence.

`v2.json` preserves multiple same-day price observations as canonical UTC timestamps, including a missing reading. Both Python and TypeScript validate it; v1 remains calendar-only.
