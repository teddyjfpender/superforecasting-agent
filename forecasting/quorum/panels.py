"""Quorum model / provider / panel resolution (carved from ``quorum.py``).

The Wave-4 §W3.a ``panels`` leaf: preset→model resolution, provider reachability,
and the connected-provider / configured-panel rebuild (``resolve_models``,
``resolve_connected_panel``, ``resolve_configured_panel``, ``available_provider_slugs``
& friends), plus the ``QUORUM_PANEL_MODELS``/``QUORUM_JUDGE_MODEL`` config-key
constants. Imported back into :mod:`forecasting.quorum.core` for the ``__all__``
surface and re-exported by the package façade, so ``from forecasting.quorum
import resolve_connected_panel`` (and the object-form patches of
``available_provider_slugs`` / ``available_providers_detail``) are unchanged.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from forecasting.models import ValidationError
from forecasting.quorum.core import QUORUM_PRESETS, _UNSET_CONFIG, preset_model_count

def resolve_models(
    preset: str | None,
    models: Sequence[str] | None,
    *,
    active_model: str | None = None,
) -> tuple[list[str], str | None]:
    """Resolve the panelist model list + judge from a preset and/or overrides.

    Explicit ``models`` always win. Otherwise a named preset is expanded; the
    ``self`` preset fills its model list from ``active_model`` repeated
    ``samples`` times. Returns ``(models, judge_model_or_None)``.
    """

    if models:
        return list(models), None
    if not preset:
        preset = "frontier"
    spec = QUORUM_PRESETS.get(preset)
    if spec is None:
        raise ValidationError(
            f"unknown quorum preset '{preset}'. Known: "
            + ", ".join(sorted(QUORUM_PRESETS))
        )
    judge = spec.get("judge")
    if preset == "self":
        if not active_model:
            raise ValidationError(
                "the 'self' preset needs an active model to sample; pass --models "
                "or set a default model"
            )
        samples = int(spec.get("samples", 3))
        return [active_model] * samples, judge or active_model
    return list(spec["models"]), judge


def quorum_auto_indicated(
    config: Mapping[str, Any] | None,
    *,
    panel_indicated: bool,
    has_prior_snapshot: bool,
) -> bool:
    """Decide whether a quorum should auto-run at the update stage.

    Honours the user's ``quorum.default_enabled`` / ``quorum.default_scope``
    config. The quorum rides the *existing* deliberative-panel trigger
    (``panel_indicated`` is :func:`forecasting.panel.should_run_panel`) so a
    quorum never fires where a panel wouldn't, keeping the multi-model spend
    bounded — unless the user widens the scope to ``always``.

      * ``high_impact`` (default) — only when a panel is already indicated
        (high-impact or first forecast).
      * ``first_only`` — only the first forecast for a question.
      * ``always`` — every probability-bearing update.
    """

    cfg = dict(config or {})
    if not cfg.get("default_enabled"):
        return False
    scope = str(cfg.get("default_scope", "high_impact"))
    if scope == "always":
        return True
    if scope == "first_only":
        return not has_prior_snapshot
    return bool(panel_indicated)  # high_impact


# ── Autonomy: default resolution, provider reality, cost bounding ─────────────
#
# One-size-fits-all quorum defaults are wrong: a high-impact contested question
# deserves a wide/frontier panel with a Delphi revision round; a routine update
# should stay cheap (self-fusion, no revision). resolve_quorum_defaults maps the
# question's IMPACT (and its question_type) onto a preset/delphi/trim triple, then
# two guards keep the choice honest and bounded: the single-key reality guard
# (item 3 — never resolve a multi-provider preset when only one provider key is
# reachable) and the max_calls cost cap (item 4 — downgrade a preset whose
# pre-run call estimate blows the budget).


def available_provider_slugs() -> set[str] | None:
    """Authenticated LLM-provider slugs, or ``None`` when detection is unavailable.

    Reuses the same :func:`superforecasting_agent.runtime.models.list_available_providers` seam the
    ``/model`` picker uses (which itself checks ``get_auth_status`` / the
    ``OPENROUTER_API_KEY``). Returning ``None`` on any failure is the FAIL-OPEN
    signal: an unknown provider picture must never spuriously downgrade a panel to
    self-fusion — the guards below treat ``None`` as "assume reachable".
    """

    try:
        from superforecasting_agent.runtime.models import list_available_providers

        slugs = {
            str(p.get("id"))
            for p in list_available_providers()
            if p.get("authenticated")
        }
    except Exception:  # noqa: BLE001 — detection is best-effort; unknown ⇒ fail-open
        return None
    # An EMPTY set is indistinguishable from "detection is unreliable here" (no
    # host creds, a sandboxed test, etc.), so treat it as UNKNOWN (fail-open) rather
    # than "single/zero key" — otherwise we would spuriously downgrade every panel
    # to self-fusion. Only a POSITIVELY detected provider picture guards the panel.
    return slugs or None


def _model_reachable(model: str, available: set[str]) -> bool:
    """Whether one ``vendor/model`` id can be served given the available providers.

    A bare id (no ``vendor/`` prefix) routes through the active provider, so it is
    assumed reachable. A prefixed id (``anthropic/…``) is reachable when that
    vendor's provider is authenticated — matched LENIENTLY, since a provider slug
    may carry a suffix (``openai`` ⇄ ``openai-codex``). (OpenRouter — a universal
    server — is handled by the caller as a short-circuit.)
    """

    if "/" not in model:
        return True
    prefix = model.split("/", 1)[0].strip().lower()
    return any(
        prefix == a or a.startswith(prefix) or prefix.startswith(a) for a in available
    )


def models_reachable(models: Sequence[str], available: set[str] | None) -> bool:
    """True when the panel can plausibly be served by the available providers.

    This is deliberately the CONSERVATIVE *single-key* guard the task calls for —
    it only rejects a multi-provider panel when we POSITIVELY know the host has a
    lone (non-OpenRouter) provider that cannot serve every model. Anything less
    certain fails OPEN (keeps the panel), because the vendor-prefix→slug mapping is
    too coarse to reject on:

      * ``available is None`` (detection unavailable / empty) ⇒ ``True``.
      * an OpenRouter key (universal server) ⇒ ``True``.
      * two-or-more distinct providers authenticated ⇒ ``True`` (not a single-key
        host; individual unreachable panelists simply error and the run is labeled
        degraded rather than mis-downgraded here).
      * exactly ONE provider ⇒ reachable only if every model maps to it.
    """

    if available is None:
        return True
    if "openrouter" in available:
        return True
    if len(available) >= 2:
        return True
    return all(_model_reachable(m, available) for m in models)


# ── FIX A: resolve presets to ACTUALLY-connected providers ───────────────────
#
# The built-in budget/frontier/wide presets name OpenRouter-format model ids
# (``anthropic/claude-opus-4-8`` …). On a host with no OpenRouter key those ids
# route to nothing and EVERY panelist fails ("agent protocol response is empty").
# resolve_connected_panel rebuilds a preset's panel from the user's ACTUALLY-authed
# providers — each provider's own default model, dispatched natively via the
# ``provider:model`` runner split — and falls back to an HONESTLY-labeled
# single-provider self-fusion when only one provider is reachable. It NEVER names a
# model the user cannot call.

# Aggregator providers serve many vendors' models under one key, so the hardcoded
# preset ids ARE callable when one is authed — no rebuild needed (OpenRouter/Nous/
# Vercel become "just another provider IF a key exists").
_AGGREGATOR_PROVIDER_SLUGS = frozenset({"openrouter", "nous", "ai-gateway"})
# Provider slugs that are not a distinct model source for panel diversity.
_NON_PANEL_PROVIDER_SLUGS = frozenset({"custom"})


def available_providers_detail() -> list[dict[str, Any]] | None:
    """Authenticated-provider detail rows, or ``None`` when detection is unavailable.

    Reuses the same :func:`superforecasting_agent.runtime.models.list_available_providers` seam as
    :func:`available_provider_slugs` but keeps the ORDER + labels (so the panel is
    built deterministically from the canonical provider order). ``None`` on any
    failure is the FAIL-OPEN signal — an unknown provider picture must never
    rebuild a panel; the caller keeps the preset verbatim.
    """

    try:
        from superforecasting_agent.runtime.models import list_available_providers

        rows = [
            dict(p) for p in list_available_providers() if p.get("authenticated")
        ]
    except Exception:  # noqa: BLE001 — detection is best-effort; unknown ⇒ fail-open
        return None
    return rows or None


def _provider_default_model(slug: str) -> str | None:
    """The provider's own default/best model id (native form), or ``None``."""

    try:
        from superforecasting_agent.runtime.models import get_default_model_for_provider

        model = (get_default_model_for_provider(slug) or "").strip()
    except Exception:  # noqa: BLE001 — best-effort; a provider with no default is skipped
        return None
    return model or None


def _split_provider_model(model_id: str) -> tuple[str | None, str]:
    """Split a ``provider:model`` panel id into ``(provider, model)``.

    Only splits when the token before the FIRST colon is a KNOWN provider name —
    so a native/OpenRouter id that merely contains a colon (e.g.
    ``anthropic/claude-3.5-sonnet:beta``) is left intact and routed by
    auto-resolution. Returns ``(None, model_id)`` when there is no provider prefix.
    """

    from superforecasting_agent.configuration.providers import split_provider_model

    try:
        from superforecasting_agent.runtime.models import _KNOWN_PROVIDER_NAMES
    except Exception:  # noqa: BLE001 — without the catalog, never split
        return None, model_id
    return split_provider_model(model_id, _KNOWN_PROVIDER_NAMES)


def resolve_connected_panel(
    preset: str,
    *,
    active_model: str | None,
    active_provider: str | None = None,
    providers: Sequence[Mapping[str, Any]] | None = None,
    samples: int = 3,
) -> dict[str, Any]:
    """Rebuild a multi-provider preset panel from the user's ACTUALLY-authed providers.

    Returns ``{"rebuilt", "self_fusion", "models", "judge", "label", "providers_used"}``.

      * ``rebuilt=False`` — keep the preset's own model ids verbatim. Happens when
        detection is unavailable (fail-open), an AGGREGATOR key is present (the
        preset ids are callable), or nothing usable was found.
      * multi-provider (``rebuilt=True``, ``self_fusion=False``) — >=2 distinct
        native providers, each contributing its own default model as a
        ``provider:model`` id; ``label`` names them.
      * self-fusion (``rebuilt=True``, ``self_fusion=True``) — exactly one provider
        reachable: ``active_model`` sampled ``samples`` times, with the HONEST label
        "1 provider connected -> self-fusion; multi-model needs a second provider".

    Never names a model the user cannot call: a rebuilt multi-provider panel uses
    each provider's OWN default model, and the self-fusion fallback uses the active
    model routed through its active provider.
    """

    detail = (
        [dict(p) for p in providers]
        if providers is not None
        else available_providers_detail()
    )
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

    authed = {str(p.get("id")) for p in detail}
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
        model = _provider_default_model(slug)
        if not model:
            continue
        seen.add(slug)
        pairs.append((slug, f"{slug}:{model}"))

    if len(pairs) >= 2:
        want = max(2, min(preset_model_count(preset, samples=samples), len(pairs)))
        chosen = pairs[:want]
        models = [qm for _, qm in chosen]
        active_norm = (active_provider or "").strip().lower()
        judge = next(
            (qm for slug, qm in chosen if slug == active_norm), models[0]
        )
        label = (
            f"{len(chosen)} providers connected -> multi-model panel: "
            + ", ".join(slug for slug, _ in chosen)
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


# ── Operator-pinned panel (QUORUM_PANEL_MODELS) ──────────────────────────────
#
# The connected-provider rebuild picks each provider's OWN default model, which is
# right for a hands-off desk but wrong when an operator KNOWS a provider's default
# is unreachable (a dead token, a zero-quota preview model) or simply wants a
# specific line-up. QUORUM_PANEL_MODELS / QUORUM_JUDGE_MODEL let the operator pin
# exactly which ``provider:model`` seats sit in the panel; it takes PRECEDENCE over
# both the preset expansion and the connected-provider rebuild. Every pinned entry
# is validated against the actually-callable providers so a non-callable entry
# ERRORS NAMING ITSELF rather than silently dropping out at dispatch time.

# Config keys (mirrored in forecasting.appconfig's registry so the doctor knows them).
QUORUM_PANEL_MODELS_KEY = "QUORUM_PANEL_MODELS"
QUORUM_JUDGE_MODEL_KEY = "QUORUM_JUDGE_MODEL"


def parse_panel_models_config(raw: str | None) -> list[str]:
    """Parse a ``QUORUM_PANEL_MODELS`` comma list into clean ``provider:model`` entries."""

    if not raw:
        return []
    return [entry.strip() for entry in str(raw).split(",") if entry.strip()]


def validate_panel_models(
    models: Sequence[str],
    *,
    providers: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    """Validate pinned panel entries against the ACTUALLY-callable providers.

    Raises :class:`ValidationError` naming EVERY entry whose ``provider:`` prefix is
    not a connected/callable provider — never silently drops one. A bare id (no
    known provider prefix) routes through the active provider, so it is accepted
    (its reachability cannot be judged here). When the provider picture is UNKNOWN
    (detection unavailable) validation fails OPEN — the same fail-open contract the
    rest of the module keeps — so a sandboxed/headless host is never blocked. An
    aggregator key (OpenRouter/Nous/AI-Gateway) serves any id, so all entries pass.
    """

    detail = (
        [dict(p) for p in providers]
        if providers is not None
        else available_providers_detail()
    )
    if detail is None:
        return  # unknown provider picture — cannot prove non-callability, fail open
    authed = {str(p.get("id")) for p in detail}
    if authed & _AGGREGATOR_PROVIDER_SLUGS:
        return  # a universal aggregator serves every pinned id
    bad: list[str] = []
    for entry in models:
        prefix, _bare = _split_provider_model(entry)
        if prefix is None:
            continue  # bare id → active provider; reachability not decidable here
        if prefix not in authed:
            bad.append(entry)
    if bad:
        raise ValidationError(
            f"{QUORUM_PANEL_MODELS_KEY} names entr"
            + ("ies" if len(bad) > 1 else "y")
            + " whose provider is not connected/callable: "
            + ", ".join(bad)
            + ". Connected providers: "
            + (", ".join(sorted(authed)) or "(none)")
            + f". Fix {QUORUM_PANEL_MODELS_KEY} or connect the provider."
        )


def resolve_configured_panel(
    *,
    providers: Sequence[Mapping[str, Any]] | None = None,
    panel_models: str | None = _UNSET_CONFIG,
    judge_model: str | None = _UNSET_CONFIG,
) -> dict[str, Any] | None:
    """The operator-pinned panel from ``QUORUM_PANEL_MODELS`` / ``QUORUM_JUDGE_MODEL``.

    Returns ``{"models": [...], "judge": str | None}`` when ``QUORUM_PANEL_MODELS``
    is set (validated — a non-callable entry raises :class:`ValidationError`), or
    ``None`` when it is unset so the caller falls through to the preset / connected
    resolution. ``panel_models`` / ``judge_model`` are injectable for tests; unset
    (the default) reads them from the layered appconfig loader (registry default <
    config-file ``env:`` section < ``os.environ`` < override).
    """

    if panel_models is _UNSET_CONFIG:
        from forecasting import appconfig

        panel_models = appconfig.get_str(QUORUM_PANEL_MODELS_KEY, None)
    models = parse_panel_models_config(panel_models)
    if not models:
        return None
    validate_panel_models(models, providers=providers)
    if judge_model is _UNSET_CONFIG:
        from forecasting import appconfig

        judge_model = appconfig.get_str(QUORUM_JUDGE_MODEL_KEY, None)
    judge = (str(judge_model).strip() if judge_model else "") or None
    if judge:
        validate_panel_models([judge], providers=providers)
    return {"models": models, "judge": judge}
