"""Market-liquidity stratification — don't let a thin or stale market inflate a
tail just because it has an outcome listed.

A prediction-market price is only as informative as the market behind it. A deep,
active, recently-traded market is strong evidence; a thin, stale, or placeholder
market is a price nobody is defending, and pooling it at full weight lets noise
masquerade as signal (and, on a long-tail outcome, inflates the tail). This
module classifies a market reading by depth + recency and returns an ADVISORY
weight multiplier in [0, 1] to apply when the market enters an ensemble pool —
never a silent edit, always a recommendation the forecaster can see and override.

Pure logic: the ledger/adapters supply volume + last-update timestamp; the
thresholds live here so they are unit-testable.

Tiers (most → least informative):
  liquid      — deep + recently traded; full weight.
  moderate    — usable depth/recency; mild discount.
  thin        — low volume; heavy discount.
  stale       — not traded recently; heavy discount regardless of depth.
  placeholder — ~no volume; near-zero weight (a listed price nobody holds).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# Volume tiers (in the market's own quote/contract units — adapters normalize
# to a float). Defaults are deliberately conservative; override per venue.
DEFAULT_LIQUID_VOLUME = 50_000.0
DEFAULT_THIN_VOLUME = 5_000.0
DEFAULT_PLACEHOLDER_VOLUME = 100.0
# Recency: a market not traded/updated within this many days is stale.
DEFAULT_STALE_DAYS = 7.0
DEFAULT_MODERATE_AGE_DAYS = 2.0
# Weight multipliers per tier.
_TIER_WEIGHTS = {
    "liquid": 1.0,
    "moderate": 0.7,
    "thin": 0.35,
    "stale": 0.25,
    "placeholder": 0.05,
}


@dataclass
class MarketReading:
    source: str
    probability: float | None = None
    volume: float | None = None
    age_days: float | None = None  # how old the last update is, in days


@dataclass
class MarketQuality:
    source: str
    tier: str
    weight: float
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "tier": self.tier,
            "weight": self.weight,
            "reasons": list(self.reasons),
        }


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None  # drop NaN


def age_days_from_timestamp(updated_at: str | None, now: str | None = None) -> float | None:
    """Days between ``updated_at`` and ``now`` (both ISO-8601). None when the
    timestamp is missing or unparseable — recency then simply isn't scored."""
    if not updated_at:
        return None

    def _parse(ts: str) -> datetime | None:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    then = _parse(updated_at)
    if then is None:
        return None
    ref = _parse(now) if now else datetime.now(timezone.utc)
    if ref is None:
        return None
    return max(0.0, (ref - then).total_seconds() / 86400.0)


def classify_market(
    reading: MarketReading,
    *,
    liquid_volume: float = DEFAULT_LIQUID_VOLUME,
    thin_volume: float = DEFAULT_THIN_VOLUME,
    placeholder_volume: float = DEFAULT_PLACEHOLDER_VOLUME,
    stale_days: float = DEFAULT_STALE_DAYS,
    moderate_age_days: float = DEFAULT_MODERATE_AGE_DAYS,
) -> MarketQuality:
    """Stratify a single market reading into a tier + advisory weight.

    Staleness dominates depth (a deep market nobody has touched in weeks is not
    a live price), and the final weight is the LOWER of the volume-tier and
    recency-tier multipliers so neither dimension can rescue the other.
    """
    reasons: list[str] = []
    volume = _coerce_float(reading.volume)
    age = _coerce_float(reading.age_days)

    # Volume tier.
    if volume is None:
        vol_tier = "moderate"
        reasons.append("volume unknown — treated as moderate")
    elif volume <= placeholder_volume:
        vol_tier = "placeholder"
        reasons.append(f"volume {volume:.0f} <= {placeholder_volume:.0f}: placeholder price")
    elif volume < thin_volume:
        vol_tier = "thin"
        reasons.append(f"volume {volume:.0f} < {thin_volume:.0f}: thin")
    elif volume < liquid_volume:
        vol_tier = "moderate"
        reasons.append(f"volume {volume:.0f} < {liquid_volume:.0f}: moderate depth")
    else:
        vol_tier = "liquid"
        reasons.append(f"volume {volume:.0f} >= {liquid_volume:.0f}: liquid")

    # Recency tier.
    if age is None:
        rec_tier = "moderate"
        reasons.append("recency unknown — treated as moderate")
    elif age > stale_days:
        rec_tier = "stale"
        reasons.append(f"last update {age:.1f}d ago > {stale_days:.0f}d: stale")
    elif age > moderate_age_days:
        rec_tier = "moderate"
        reasons.append(f"last update {age:.1f}d ago: moderately recent")
    else:
        rec_tier = "liquid"
        reasons.append(f"last update {age:.1f}d ago: fresh")

    # Combine: the binding constraint wins (lowest weight).
    candidates = {vol_tier, rec_tier}
    if "placeholder" in candidates:
        tier = "placeholder"
    elif "stale" in candidates:
        tier = "stale"
    elif "thin" in candidates:
        tier = "thin"
    elif candidates == {"liquid"}:
        tier = "liquid"
    else:
        tier = "moderate"

    return MarketQuality(source=reading.source, tier=tier, weight=_TIER_WEIGHTS[tier], reasons=reasons)


def reading_from_evidence(row: dict[str, Any], *, now: str | None = None) -> MarketReading:
    """Build a MarketReading from a market evidence/import row (the adapters
    expose ``volume``/``total_volume`` and ``updated_at``)."""
    volume = row.get("volume")
    if volume is None:
        volume = row.get("total_volume")
    return MarketReading(
        source=str(row.get("source") or row.get("source_ref") or row.get("name") or "market"),
        probability=_coerce_float(row.get("probability") or row.get("value")),
        volume=_coerce_float(volume),
        age_days=age_days_from_timestamp(row.get("updated_at") or row.get("available_at"), now),
    )


def recommended_market_weight(reading: MarketReading, **kwargs: Any) -> float:
    """Convenience: the advisory pooling-weight multiplier for one reading."""
    return classify_market(reading, **kwargs).weight
