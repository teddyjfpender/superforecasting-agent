---
title: "Installation"
description: "Install the assigned beta artifacts in an isolated environment."
---

# Installation

The [beta tester guide](./tester-pilot.md) is the maintained installation and
first-run path. It covers the assigned artifact bundle, provider setup, an isolated
synthetic forecast, recovery and versioned diagnostic reports.

Follow it in order; do not substitute a moving snapshot checkout or install the
full development dependency set for a beta test. See [beta support scope](./beta-scope.md)
for qualified platforms and experimental integrations.

Developers working from source should use the repository's contributor guide and
`scripts/run_tests.sh`. The source-only `scripts/forecast_smoke_test.py` is an
engineering harness, not a prerequisite shipped with the installed beta wheels.
