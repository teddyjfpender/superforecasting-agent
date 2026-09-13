"""Concurrent watched-source acquisition; callers own evidence ledger writes."""

from __future__ import annotations

from typing import Any

from forecasting.sources.dispatch import load_source_items
from forecasting.sources.evidence import source_evidence_payload


def fetch_watched_source_payloads(
    specs: list[dict[str, Any]], *, concurrency: int = 4
) -> list[dict[str, Any]]:
    """Re-fetch a list of watched sources and build add_evidence payloads.

    This is the dependency injected into ``ForecastLedger.refresh_forecast`` so
    the ledger never imports acquisition orchestration. Each spec is
    ``{"source_type": <adapter name>, "source": <id/slug>, "args"?: {...}}``.
    Returns, per spec, ``{"source_type", "source", "success", "payloads",
    "error"}`` where ``payloads`` is a list of kwargs dicts for
    ``ledger.add_evidence`` (each carrying ``metadata.adapter_item``). Pure
    fetch — performs NO ledger writes (preserves SQLite's single writer).
    """

    from concurrent.futures import ThreadPoolExecutor

    def _one(spec: dict[str, Any]) -> dict[str, Any]:
        adapter = str(spec.get("source_type") or "").strip()
        source = str(spec.get("source") or "").strip()
        result = {
            "source_type": adapter,
            "source": source,
            "success": False,
            "payloads": [],
            "error": None,
        }
        try:
            adapter_args = dict(spec.get("args") or {})
            items = load_source_items(adapter, source, adapter_args)
            result["payloads"] = [
                source_evidence_payload(adapter, source, item, adapter_args)
                for item in items
            ]
            result["success"] = True
        except Exception as exc:  # noqa: BLE001 — one bad source must not abort the refresh
            result["error"] = str(exc)
        return result

    if not specs:
        return []
    workers = max(1, min(int(concurrency), len(specs)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # Iterate in submission order so imported evidence is deterministic.
        return list(pool.map(_one, specs))
