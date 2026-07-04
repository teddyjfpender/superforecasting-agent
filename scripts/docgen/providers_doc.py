"""Render ``docs/reference/providers.md`` from the data-plane provider registries.

Two registries feed this page:
  * market-DATA quote providers — ``forecasting/marketdata/service.py``
    (``_default_providers``) + ``forecasting/marketdata/keys.py`` (``PROVIDER_ENV``).
  * prediction-market venues — ``forecasting/pm/`` (the per-venue ``VENUE``
    constant + base-URL constants on ``kalshi`` / ``polymarket``).
"""

from __future__ import annotations

from scripts.docgen.common import header

SOURCE = "forecasting/marketdata/service.py + keys.py; forecasting/pm/{kalshi,polymarket}.py"

# The read-only PM data path takes no API keys; each venue module carries its
# canonical VENUE id and the REST base URLs it reads. Aliases come from
# PMService._client (polymarket also answers to "poly"/"pm").
_PM_VENUES = [
    ("forecasting.pm.polymarket", ("GAMMA_BASE", "CLOB_BASE"), ("poly", "pm")),
    ("forecasting.pm.kalshi", ("KALSHI_BASE",), ()),
]


def render() -> str:
    from forecasting.marketdata.keys import PROVIDER_ENV
    from forecasting.marketdata.service import _default_providers

    providers = _default_providers()

    blocks: list[str] = [
        header(
            "Data-Plane Providers",
            SOURCE,
            blurb=(
                "The server-side data plane (Arc C) turns external numbers into"
                " structured quotes and de-vigged market distributions. Two"
                " registries: **market-data quote providers** (FX, econ series,"
                " crypto, equities) and **prediction-market venues** (order books +"
                " price history). Evidence-import adapters (FRED, GDELT, arXiv, …)"
                " are a separate, larger set driven by the CLI `import`/`sources`"
                " commands and the tool's `source_type` parameter."
            ),
        )
    ]

    # ── market-data quote providers ──────────────────────────────────────────
    blocks.append("## Market-data quote providers\n")
    blocks.append(
        f"**{len(providers)} providers**, resolved by `MarketDataService`. `needs"
        " key` providers are skipped when no key resolves; the others degrade to a"
        " keyless path where noted in the source."
    )
    rows = ["| id | needs key | env var | class |", "| --- | --- | --- | --- |"]
    for pid in sorted(providers):
        prov = providers[pid]
        env = PROVIDER_ENV.get(pid, "—")
        needs = "yes" if getattr(prov, "needs_key", False) else "no"
        rows.append(f"| `{pid}` | {needs} | `{env}` | `{type(prov).__name__}` |")
    blocks.append("\n".join(rows))

    # ── prediction-market venues ─────────────────────────────────────────────
    blocks.append("## Prediction-market venues\n")
    blocks.append(
        f"**{len(_PM_VENUES)} venues**, browsed read-only (no API keys on the data"
        " path). Served through `PMService` and the `pm.*` RPCs; also reachable from"
        " the agent via the tool's `pm_query` action."
    )
    vrows = ["| venue | aliases | REST base URLs |", "| --- | --- | --- |"]
    for mod_path, base_attrs, aliases in _PM_VENUES:
        import importlib

        mod = importlib.import_module(mod_path)
        venue = getattr(mod, "VENUE")
        bases = ", ".join(f"`{getattr(mod, a)}`" for a in base_attrs if hasattr(mod, a))
        alias_txt = ", ".join(f"`{a}`" for a in aliases) if aliases else "—"
        vrows.append(f"| `{venue}` | {alias_txt} | {bases} |")
    blocks.append("\n".join(vrows))

    return "\n\n".join(blocks) + "\n"
