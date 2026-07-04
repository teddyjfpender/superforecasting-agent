"""Living reference-doc generator for the Superforecasting Agent.

Every file under ``docs/reference/`` is GENERATED from the same Python sources the
code itself compiles from — the protocol registry, the forecast-tool action
schema, the jobs registry, the market-data / prediction-market providers, the
CLI argparse tree, and the built-in forecast hooks. The point is auto-evolution:
when the code grows a new RPC, action, job type, provider, command, or rule, the
reference regenerates and a ``--check`` staleness gate turns any drift into a
build error instead of stale prose.

Usage
-----
    python -m scripts.docgen            # (re)write docs/reference/*.md
    python -m scripts.docgen --check    # exit nonzero if any file is stale

This mirrors the protocol TypeScript codegen (``python -m protocol.codegen``):
deterministic output (sorted), no timestamps, diff-stable, one gate.
"""

from __future__ import annotations

from scripts.docgen.registry import GENERATORS, Generated, render_all

__all__ = ["GENERATORS", "Generated", "render_all"]
