"""Quorum call-count / preset-cap / trial-count machinery (carved from ``quorum.py``).

The Wave-4 §W3.a ``estimation`` leaf: the pre-run call-count estimate, the
cost-cap downgrade ladder (``cap_preset_by_calls`` + its tier tables), the
``resolve_quorum_defaults`` layered-config resolver, and the BLF multi-trial
count machinery (``resolve_trial_count`` / ``cap_trials_by_calls``). Imported
back into :mod:`forecasting.quorum.core` for ``run_quorum`` and the ``__all__``
surface, and re-exported by the package façade unchanged. The shared
``preset_model_count`` primitive stays in ``core`` (both this leaf and ``panels``
call it — the caller-exclusivity rule keeps the shared name in core, which also
breaks the panels↔estimation import cycle).
"""
from __future__ import annotations

from typing import Any

from forecasting.quorum.core import (
    QUORUM_PRESETS,
    _DEFAULT_TRIALS,
    _HIGH_IMPACT_TRIALS,
    preset_model_count,
)
from forecasting.quorum.panels import models_reachable

def estimate_quorum_calls(
    *, model_count: int, delphi_rounds: int, has_judge: bool = True, trials: int = 1
) -> int:
    """Pre-run model-call estimate for a quorum.

    Each round dispatches ``model_count`` panelists — each run ``trials`` times per
    seat (BLF A2 multi-trial; ``trials=1`` is the default and byte-identical) — plus
    (if wired) one judge. A Delphi run adds a second full round (``delphi_rounds`` in
    {0, 1}). Supervisor fresh-search, when enabled, adds further full rounds — it is
    OPT-IN/OFF by default and reported separately, so it is deliberately excluded
    here (the estimate is the guaranteed floor, not the search-enabled ceiling)."""

    rounds = max(1, int(delphi_rounds) + 1)
    per_round = max(1, int(model_count)) * max(1, int(trials)) + (1 if has_judge else 0)
    return per_round * rounds


# Cost/size tiers for the downgrade ladder. A cap must never route a request to a
# MORE EXPENSIVE tier than the one asked for — that would invert the cost cap
# (e.g. "downgrading" a cheap self-fusion onto the 10-model premium `wide` panel).
# The tiers rank by call count AND per-call model cost: `self` (one active model,
# cheapest) < `budget` (3 cheap models) < `frontier` (2 premium models) < `wide`
# (~10 mixed premium draws, most expensive).
_DOWNGRADE_PRESETS = ("wide", "budget", "self", "frontier")
_PRESET_TIER: dict[str, int] = {"self": 0, "budget": 1, "frontier": 2, "wide": 3}


def cap_preset_by_calls(
    preset: str,
    delphi_rounds: int,
    *,
    max_calls: int,
    samples: int = 3,
) -> tuple[str, int, int, int, str | None]:
    """Bound a (preset, delphi, samples) choice by ``max_calls``; downgrade if it overruns.

    Returns ``(preset, delphi_rounds, samples, estimated_calls, note)``. When the
    requested choice fits, ``note`` is ``None`` and nothing changes. Otherwise the
    LARGEST still-fitting choice is picked WITHOUT ever escalating to a costlier
    preset tier than the one requested (``self`` < ``budget`` < ``frontier`` <
    ``wide``) — so lowering the cap or raising ``--samples`` can only ever make a
    run CHEAPER, never route a routine ``self`` request onto a premium panel. Order
    of attack: (1) drop the Delphi round; (2) step DOWN the preset ladder / reduce
    ``self``'s sample count to the largest affordable panel AT OR BELOW the
    requested tier. A pathologically small ``max_calls`` falls open to the cheapest
    real panel (``self`` sampled once, no delphi) rather than blocking the run.
    """

    max_calls = int(max_calls)
    samples = max(1, int(samples))

    def _calls(cand: str, d: int, s: int) -> int:
        return estimate_quorum_calls(
            model_count=preset_model_count(cand, samples=s), delphi_rounds=d
        )

    est = _calls(preset, delphi_rounds, samples)
    if est <= max_calls:
        return preset, delphi_rounds, samples, est, None

    requested_tier = _PRESET_TIER.get(preset, 0)

    # (1) Drop the Delphi round first — it doubles cost for the same panel width.
    if delphi_rounds:
        est0 = _calls(preset, 0, samples)
        if est0 <= max_calls:
            return (
                preset,
                0,
                samples,
                est0,
                f"downgraded: dropped Delphi revision to fit max_calls={max_calls} "
                f"(would have been {est})",
            )

    # (2) Enumerate downgrade candidates — NEVER above the requested tier. For
    #     ``self`` (the cheapest tier) the only lever is fewer samples, so we keep
    #     it self-fusion of the active model rather than switching to a premium
    #     model list. Pick the LARGEST call-count that still fits within that
    #     bounded set (best affordable panel); ties break toward the cheaper tier.
    candidates: list[tuple[int, int, str, int, int]] = []
    for cand in _DOWNGRADE_PRESETS:
        cand_tier = _PRESET_TIER.get(cand, 0)
        if cand_tier > requested_tier:
            continue
        sample_options = range(samples, 0, -1) if cand == "self" else (samples,)
        for s in sample_options:
            for d in {delphi_rounds, 0}:
                calls = _calls(cand, d, s)
                if calls <= max_calls and calls < est:
                    candidates.append((calls, -cand_tier, cand, d, s))
    if candidates:
        calls, _neg_tier, cand, d, s = max(candidates)
        if cand != preset:
            note = (
                f"downgraded {preset}→{cand} (delphi={d}, samples={s}) to fit "
                f"max_calls={max_calls} (would have been {est})"
            )
        else:
            note = (
                f"downgraded {preset}: samples→{s} (delphi={d}) to fit "
                f"max_calls={max_calls} (would have been {est})"
            )
        return cand, d, s, calls, note

    # Nothing fits — fail OPEN to the cheapest real panel (self sampled once)
    # rather than blocking the run or escalating to a premium preset.
    floor = _calls("self", 0, 1)
    return (
        "self",
        0,
        1,
        floor,
        f"max_calls={max_calls} below any panel's floor; using self/1-sample/no-delphi ({floor} calls)",
    )


def resolve_quorum_defaults(
    question: Any,
    *,
    available_providers: set[str] | None = None,
    active_model: str | None = None,
    samples: int = 3,
) -> dict[str, Any]:
    """Map a question's impact + type onto a quorum preset/delphi/trim triple.

    The single place default quorum shape is decided, shared by BOTH the manual
    ``forecast quorum`` default resolution and the autonomous auto-run path, so a
    picked default is identical and printable ("using preset X: N models + judge,
    delphi=1 — why").

      * ``high`` impact (or a contested type) → ``frontier`` panel, one Delphi
        revision round, trim the extreme — the widest independent read.
      * ``medium`` impact → ``budget`` panel, one Delphi revision round, trim.
      * routine / low / unset → ``self`` fusion, no revision, no trim — cheap.

    DELPHI TRIGGER (the audit's finding #1: Delphi had fired 0/223 while gated to
    high/contested only): the anonymous revision round is defaulted ON for every
    LIVE **multi-model** panel (``frontier`` + ``budget``), because a genuine second
    read of independent panelists is where an anonymous revision earns its extra
    round. It stays OFF for single-model ``self`` fusion (N samples of ONE model —
    a revision among clones of the same model buys little and doubles cost) and is
    still cost-capped: ``cap_preset_by_calls`` drops the Delphi round FIRST when a
    run would overrun ``max_calls``.

    Then the SINGLE-KEY REALITY GUARD (item 3): when the resolved multi-provider
    preset spans a provider that is not reachable (only one provider key present,
    no OpenRouter), it falls back to ``self`` (the active model sampled) with a
    note — a panel that would silently error every non-local panelist is worse
    than an honest self-fusion. Because that fallback makes the run single-model,
    the Delphi round is dropped with it (Delphi is a multi-model default).

    Returns ``{"preset", "delphi_rounds", "trim", "reason"}``. Does NOT apply the
    max_calls cap — the caller composes :func:`cap_preset_by_calls` after (so the
    cap note and the resolution note stay separately attributable).
    """

    impact = (getattr(question, "impact", None) or "").strip().lower()
    try:
        qtype = (getattr(getattr(question, "outcome_space", None), "type", None) or "").strip().lower()
    except Exception:  # noqa: BLE001 — a malformed question must never crash resolution
        qtype = ""

    contested = qtype in {"vote_share", "multiple_choice", "thesis"}
    if impact == "high" or contested:
        preset, delphi_rounds, trim = "frontier", 1, 1
        tier = "high-impact" if impact == "high" else f"contested ({qtype})"
    elif impact == "medium":
        # Multi-model budget panel → Delphi ON (a real second read of independent
        # panelists earns the anonymous revision round; the cap drops it if over budget).
        preset, delphi_rounds, trim = "budget", 1, 1
        tier = "medium-impact"
    else:
        preset, delphi_rounds, trim = "self", 0, 0
        tier = "routine"

    reason_parts = [f"impact={impact or 'unset'}→{tier}"]

    if preset != "self":
        preset_models = list(QUORUM_PRESETS[preset]["models"])
        if not models_reachable(preset_models, available_providers):
            if active_model:
                preset = "self"
                # A self-fusion run is single-model, so drop the Delphi revision that
                # only makes sense across independent panelists.
                delphi_rounds = 0
                reason_parts.append(
                    "single provider key reachable → self-fusion fallback"
                )
            else:
                # Single-key host with no active model to self-fuse: keep the
                # preset so the job still runs (unreachable panelists error and the
                # run is labeled degraded) rather than dead-ending.
                reason_parts.append(
                    "single provider key but no active model — keeping preset "
                    "(panelists may degrade)"
                )

    return {
        "preset": preset,
        "delphi_rounds": delphi_rounds,
        "trim": trim,
        "reason": "; ".join(reason_parts),
    }


def resolve_trial_count(
    question: Any,
    *,
    high_impact_trials: int = _HIGH_IMPACT_TRIALS,
    default_trials: int = _DEFAULT_TRIALS,
    override: int | None = None,
) -> tuple[int, str]:
    """Map a question's IMPACT onto K trials-per-panelist (BLF A2).

    ``high`` impact runs ``high_impact_trials`` draws per seat (default 3 — a
    contested, expensive-to-be-wrong question deserves the variance-reduced pool);
    every other question stays ``default_trials`` (1 — a single draw, byte-identical
    to a pre-A2 panelist). An explicit ``override`` (a per-run spec value) always
    wins. Returns ``(K, reason)`` so the printable defaults line can name why. The
    resolved K is bounded downstream by :func:`cap_trials_by_calls` + the policy
    matrix's LLM_SPEND cap — the same brakes that bound panel width."""

    if override is not None:
        return max(1, int(override)), f"trials override={int(override)}"
    impact = (getattr(question, "impact", None) or "").strip().lower()
    if impact == "high":
        return max(1, int(high_impact_trials)), (
            f"impact=high → K={max(1, int(high_impact_trials))} trials/panelist"
        )
    return max(1, int(default_trials)), (
        f"impact={impact or 'unset'} → K={max(1, int(default_trials))} trial/panelist"
    )


def cap_trials_by_calls(
    *,
    preset: str | None,
    delphi_rounds: int,
    samples: int,
    trials: int,
    max_calls: int,
    has_judge: bool = True,
) -> tuple[int, str | None]:
    """Bound K trials-per-panelist to fit ``max_calls`` given the (already-capped)
    panel shape.

    Extra trials of the SAME seats are the cheapest lever to cut, so this runs AFTER
    :func:`cap_preset_by_calls` has fixed the panel width/Delphi/samples: it steps K
    down to the largest value whose total call estimate still fits ``max_calls``,
    never below 1. Returns ``(trials, note)`` — ``note`` is ``None`` when the
    requested K already fit (nothing changed), so a default K=1 run is untouched."""

    model_count = preset_model_count(preset, samples=samples)
    requested = max(1, int(trials))
    k = requested
    while k > 1 and estimate_quorum_calls(
        model_count=model_count, delphi_rounds=delphi_rounds, has_judge=has_judge, trials=k
    ) > int(max_calls):
        k -= 1
    if k == requested:
        return requested, None
    return k, f"trials {requested}→{k} to fit max_calls={int(max_calls)}"
