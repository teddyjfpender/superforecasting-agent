"""Connected-panel selection rules, independent of provider discovery and IO.

Callers supply an ordered credential snapshot and native default model IDs.
The selected panel is a routing proposal, not proof of successful model calls.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_AGGREGATOR_PROVIDER_SLUGS = frozenset({"openrouter", "nous", "ai-gateway"})
_NON_PANEL_PROVIDER_SLUGS = frozenset({"custom"})


def select_connected_panel(
    detail: Sequence[Mapping[str, Any]] | None,
    *,
    panel_size: int,
    active_model: str | None,
    active_provider: str | None = None,
    samples: int = 3,
) -> dict[str, Any]:
    """Choose a panel from supplied evidence; None means detection unavailable.

    Missing authentication fields preserve the authenticated-row input contract.
    Explicitly negative or malformed status never grants a provider a seat.
    """
    base = {
        "rebuilt": False,
        "self_fusion": False,
        "models": None,
        "judge": None,
        "label": None,
        "providers_used": [],
    }
    if detail is None:
        # Unknown provider picture — fail open, keep the preset verbatim.
        return base

    detail = [
        row
        for row in detail
        if row.get("id") and row.get("authenticated", True) is True
    ]
    authed = {str(p["id"]) for p in detail}
    base["providers_used"] = sorted(authed)
    # An aggregator key serves the hardcoded preset ids as-is — no rebuild.
    if authed & _AGGREGATOR_PROVIDER_SLUGS:
        return base

    # Distinct native providers, canonical order, each with its own default model.
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in detail:
        slug = str(row.get("id"))
        if slug in _NON_PANEL_PROVIDER_SLUGS or slug in _AGGREGATOR_PROVIDER_SLUGS:
            continue
        if slug in seen:
            continue
        model = row.get("default_model")
        if not model:
            continue
        seen.add(slug)
        pairs.append((slug, f"{slug}:{model}"))

    if len(pairs) >= 2:
        want = max(2, min(panel_size, len(pairs)))
        chosen = pairs[:want]
        models = [qm for _, qm in chosen]
        active_norm = (active_provider or "").strip().lower()
        judge = next((qm for slug, qm in chosen if slug == active_norm), models[0])
        label = f"{len(chosen)} providers connected -> multi-model panel: " + ", ".join(
            slug for slug, _ in chosen
        )
        return {
            "rebuilt": True,
            "self_fusion": False,
            "models": models,
            "judge": judge,
            "label": label,
            "providers_used": [slug for slug, _ in chosen],
        }

    # ZERO usable providers: the docstring's contract — nothing usable was
    # found -> rebuilt=False (fail-open, preset verbatim). Claiming
    # "1 provider connected" here would be a lie, and self-fusing an active
    # model with no live provider behind it reproduces the empty-response
    # failure this function exists to prevent.
    if not pairs and not authed:
        return base

    # Exactly 1 native provider reachable — honest single-provider self-fusion.
    if active_model:
        n = max(1, int(samples))
        label = (
            "1 provider connected -> self-fusion; multi-model needs a second provider"
        )
        return {
            "rebuilt": True,
            "self_fusion": True,
            "models": [active_model] * n,
            "judge": active_model,
            "label": label,
            "providers_used": [pairs[0][0]] if pairs else sorted(authed),
        }

    # Nothing usable to rebuild with (no aggregator, <2 providers, no active model).
    return base
