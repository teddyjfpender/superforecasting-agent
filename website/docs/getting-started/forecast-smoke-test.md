---
title: "Forecast Smoke Test"
description: "Verify an installed beta with a synthetic forecast."
---

# Forecast smoke test

For installed beta wheels, complete the [synthetic walkthrough](./tester-pilot.md#3-complete-one-synthetic-forecast).
It checks persistence, resolution, scoring and postmortem creation in an isolated
profile without spending provider credits. It does not establish forecast quality.

The repository's `scripts/forecast_smoke_test.py` is a source-only engineering
harness. It is not included in the installed products and is not required for
beta onboarding. Contributors should use the repository development guide and
`scripts/run_tests.sh` for engineering verification.

## Contributor evidence

The [historical smoke transcript](https://github.com/teddyjfpender/superforecasting-agent/blob/superforecasting-agent-snapshot/docs/plans/2026-05-24-forecast-cli-smoke-transcript.md)
records an earlier source build, not the installed beta candidate.

When changing these guides, run the website production build and check for
broken-link or broken-anchor warnings. Treat any new docs-link warning as a regression.
