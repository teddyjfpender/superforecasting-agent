"""Per-question minimum-requirement THRESHOLDS for forecast hooks.

The built-in gates in ``builtins.py`` carry hard-coded numeric floors/ceilings
(MIN_PERSPECTIVES, MAX_WIDTH_RATIO, MIN_SHARPNESS, NULL_EXCESS_TOLERANCE,
reasoning min-counts, tail tolerances). This module makes those tunable
PER-FORECAST: a question may carry ``metadata['forecast_hooks']['thresholds']``
overriding any of them. Each gate reads ``ctx.threshold(key) ?? <CONSTANT>``.

The registry is the SINGLE source of truth for the threshold schema — its
metadata (default, label, bounds, direction) is consumed both by the gates and
by the ledger's ``resolve_question_config`` (so the TUI renders the same set with
the same defaults + can flag a LOOSER override). ``direction='lower_looser'``
means a SMALLER value is a laxer requirement (e.g. fewer perspectives demanded);
``direction='higher_looser'`` means a LARGER value is laxer (e.g. a wider
allowed interval, more tolerated null-tail mass).

stdlib-only, mirroring the dependency-light discipline of the rest of the hooks
package.
"""

from __future__ import annotations

from dataclasses import dataclass

# Defaults — kept byte-identical to the legacy constants in builtins.py so an
# un-overridden question behaves EXACTLY as before.
DEFAULT_MIN_PERSPECTIVES = 3
DEFAULT_MAX_WIDTH_RATIO = 1.0
DEFAULT_MIN_SHARPNESS = 0.05
DEFAULT_NULL_EXCESS_TOLERANCE = 0.05
# Terminal Platt-calibration slope applied to the panel pool AFTER aggregation.
# 1.0 is the IDENTITY (an un-configured question is byte-identical to the bare
# pool); >1 sharpens away from 0.5, <1 flattens toward it. Composed
# multiplicatively with any learned logit_scale (both are alpha-style log-odds
# slopes): combined_alpha = alpha_extremize * learned_scale.
DEFAULT_ALPHA_EXTREMIZE = 1.0


@dataclass(frozen=True)
class ThresholdSpec:
    key: str
    label: str
    default: float
    minimum: float
    maximum: float
    # which gate(s) consume it (informational, for the inspector)
    rule_ids: tuple[str, ...]
    # 'lower_looser' -> a value BELOW the default relaxes the gate (e.g. demanding
    # fewer perspectives); 'higher_looser' -> a value ABOVE the default relaxes it
    # (e.g. allowing a wider interval / more null-tail mass).
    direction: str
    integer: bool = False
    help: str = ""

    def clamp(self, value: float) -> float:
        v = max(self.minimum, min(self.maximum, float(value)))
        return float(round(v)) if self.integer else float(v)

    def is_looser(self, value: float) -> bool:
        """True when ``value`` is a LAXER requirement than the default."""
        v = float(value)
        if self.direction == "lower_looser":
            return v < float(self.default)
        return v > float(self.default)


# Ordered for stable rendering in the TUI.
THRESHOLD_SPECS: tuple[ThresholdSpec, ...] = (
    ThresholdSpec(
        key="min_perspectives",
        label="Min panel perspectives",
        default=DEFAULT_MIN_PERSPECTIVES,
        minimum=1,
        maximum=12,
        rule_ids=("quorum_participation",),
        direction="lower_looser",
        integer=True,
        help="Distinct viewpoints (panel perspectives OR quorum models) a deliberation must carry.",
    ),
    ThresholdSpec(
        key="min_reasoning_methods",
        label="Min distinct reasoning methods",
        default=0,  # resolved from the profile unless explicitly overridden
        minimum=0,
        maximum=8,
        rule_ids=("reasoning_composition",),
        direction="lower_looser",
        integer=True,
        help="How many distinct reasoning methods must be declared (overrides the profile floor).",
    ),
    ThresholdSpec(
        key="max_width_ratio",
        label="Max interval width (x range)",
        default=DEFAULT_MAX_WIDTH_RATIO,
        minimum=0.1,
        maximum=10.0,
        rule_ids=("uncertainty_width_sane",),
        direction="higher_looser",
        integer=False,
        help="Widest allowed interval as a multiple of the question range before the width gate warns.",
    ),
    ThresholdSpec(
        key="min_sharpness",
        label="Min sharpness (anti coin-flip)",
        default=DEFAULT_MIN_SHARPNESS,
        minimum=0.0,
        maximum=0.5,
        rule_ids=("confidence_committed",),
        direction="lower_looser",
        integer=False,
        help="Minimum commitment away from a coin flip before the confidence gate nudges.",
    ),
    ThresholdSpec(
        key="null_excess_tolerance",
        label="Null-tail mass tolerance",
        default=DEFAULT_NULL_EXCESS_TOLERANCE,
        minimum=0.0,
        maximum=0.5,
        rule_ids=("tails_justified",),
        direction="higher_looser",
        integer=False,
        help="Allowed mass above the null-model tail before the no-path-tails gate fires.",
    ),
    ThresholdSpec(
        key="alpha_extremize",
        label="Terminal Platt slope (alpha)",
        default=DEFAULT_ALPHA_EXTREMIZE,
        minimum=0.25,
        maximum=4.0,
        # Consumed by panel.aggregate_panel_estimates (terminal calibration),
        # not a builtin gate — no rule_ids.
        rule_ids=(),
        # >1 sharpens (a "stricter"/bolder commitment); treat a value BELOW the
        # identity as the looser (more hedged) direction.
        direction="lower_looser",
        integer=False,
        help="Platt slope applied to the panel pool after aggregation (1.0 = no-op identity).",
    ),
)

THRESHOLD_BY_KEY: dict[str, ThresholdSpec] = {s.key: s for s in THRESHOLD_SPECS}
THRESHOLD_KEYS: tuple[str, ...] = tuple(s.key for s in THRESHOLD_SPECS)


def normalize_thresholds(raw) -> dict[str, float]:
    """Coerce a user-supplied thresholds mapping into a clamped {key: value} dict,
    dropping unknown keys and out-of-vocab values. Used by the ledger writer so a
    bad value can never reach metadata."""
    out: dict[str, float] = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        spec = THRESHOLD_BY_KEY.get(str(key))
        if spec is None:
            continue
        try:
            num = float(value)
        except (TypeError, ValueError):
            continue
        if num != num:  # NaN
            continue
        out[spec.key] = spec.clamp(num)
    return out


def threshold_value(thresholds: dict[str, float] | None, key: str, default: float) -> float:
    """Resolve ``key`` from a per-question thresholds map, falling back to
    ``default`` (the legacy constant). The single read path the gates use."""
    if thresholds:
        v = thresholds.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                return default
    return default


def resolve_alpha_extremize(question_metadata: dict | None) -> float:
    """Resolve the per-question terminal Platt slope from question metadata.

    Reads ``metadata['forecast_hooks']['thresholds']['alpha_extremize']`` and
    falls back to :data:`DEFAULT_ALPHA_EXTREMIZE` (1.0 = identity). DEFAULTING
    to 1.0 is the hard byte-identical invariant: an un-configured question's
    panel pool is unchanged. Any stored value has already been clamped to the
    spec's sane range by :func:`normalize_thresholds` on write; we re-clamp on
    read so a hand-edited DB can never inject a degenerate slope.
    """
    spec = THRESHOLD_BY_KEY["alpha_extremize"]
    if not isinstance(question_metadata, dict):
        return float(spec.default)
    fh = question_metadata.get("forecast_hooks")
    thresholds = fh.get("thresholds") if isinstance(fh, dict) else None
    if not isinstance(thresholds, dict) or "alpha_extremize" not in thresholds:
        return float(spec.default)
    try:
        return spec.clamp(float(thresholds["alpha_extremize"]))
    except (TypeError, ValueError):
        return float(spec.default)
