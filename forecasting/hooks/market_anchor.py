"""G8 · market-anchor universality — the commit-time market-link detector + the
deviation-comparison reader, shared by both HookContext builders and the
``create_snapshot`` deviation-bet wiring so the gate and the ledger never disagree
about whether a question watches a market or whether a commit engaged it.

The blind→reconcile market-anchor DISCIPLINE lives in the quorum job
(``forecasting.jobs.types.quorum`` / ``forecasting.quorum``); this module is the
lightweight, IO-free (given its inputs) surface the commit gate uses so a commit
that skips the quorum still records the market price + deviation as a first-class
``deviation_bets`` row — the seam that had 0 rows because only quorum jobs wrote it.

stdlib-only; no ledger handle (callers pass the already-read component / watched /
baseline data), mirroring the dependency-light discipline of the hooks package.
"""

from __future__ import annotations

import math
from typing import Any

# Market source-slug prefixes (kept in sync with
# ``forecasting.jobs.types.quorum._MARKET_SOURCE_PREFIXES``). A component / watched
# source / baseline whose slug or type starts with one of these is a market anchor.
MARKET_SOURCE_PREFIXES: tuple[str, ...] = ("polymarket", "kalshi", "manifold", "metaculus", "market")
_MARKET_BASELINE_TYPES: frozenset[str] = frozenset({"market_price", "market", "imported_market"})


def _slug_is_market(slug: Any) -> bool:
    s = str(slug or "").strip().lower()
    return bool(s) and any(s.startswith(pfx) for pfx in MARKET_SOURCE_PREFIXES)


def component_market_source(components: Any) -> str | None:
    """The first market-prefixed source slug in an ensemble_components blob (a list
    of rows, or the ``{components: [...]}`` wrapper), or None. Best-effort."""
    rows: Any = components
    if isinstance(rows, dict):
        rows = rows.get("components", rows)
        if isinstance(rows, dict):
            rows = list(rows.values())
    if not isinstance(rows, (list, tuple)):
        return None
    for row in rows:
        if isinstance(row, dict) and _slug_is_market(row.get("source")):
            return str(row.get("source")).strip()
    return None


def detect_linked_market(
    *,
    components: Any = None,
    watched_source_slugs: Any = None,
    baseline_types: Any = None,
) -> tuple[bool, str | None]:
    """Whether the question watches a market, and which source. A market is linked
    when ANY of: a market-prefixed ensemble component, an active watched source whose
    slug/type is market-prefixed, or a market-typed baseline comparison. Returns
    ``(linked, source_label)``; ``source_label`` is a human hint for the message."""
    src = component_market_source(components)
    if src:
        return True, src
    for slug in watched_source_slugs or ():
        if _slug_is_market(slug):
            return True, str(slug).strip()
    for btype in baseline_types or ():
        if str(btype or "").strip().lower() in _MARKET_BASELINE_TYPES:
            return True, str(btype).strip()
    return False, None


def _num(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return float(value)
    return None


def market_comparison_from_metadata(metadata: Any) -> dict[str, Any] | None:
    """The committer-stamped ``metadata.market_comparison = {price, deviation_pp,
    justification?}`` if it carries a finite market price, else None. Tolerant of the
    ``market_price`` alias for ``price``."""
    if not isinstance(metadata, dict):
        return None
    raw = metadata.get("market_comparison")
    if not isinstance(raw, dict):
        return None
    price = _num(raw.get("price"))
    if price is None:
        price = _num(raw.get("market_price"))
    if price is None:
        return None
    out: dict[str, Any] = {"price": price}
    dev = _num(raw.get("deviation_pp"))
    if dev is not None:
        out["deviation_pp"] = dev
    just = raw.get("justification") or raw.get("named_edge")
    out["justification"] = str(just).strip() if just else None
    return out


def panel_run_records_market(panel_run: Any) -> bool:
    """Whether a linked panel-run dict carries a market_anchor annotation with a
    non-null market_price (the quorum discipline recorded the comparison). The quorum
    job stamps it into ``spread_summary['market_anchor']``; fall back to a top-level /
    metadata annotation for robustness."""
    if not isinstance(panel_run, dict):
        return False
    for holder in (panel_run.get("spread_summary"), panel_run, panel_run.get("metadata")):
        anchor = holder.get("market_anchor") if isinstance(holder, dict) else None
        if isinstance(anchor, dict) and _num(anchor.get("market_price")) is not None:
            return True
    return False
