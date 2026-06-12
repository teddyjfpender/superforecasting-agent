"""Measured component track record → advisory ensemble/panel weights.

"Weight by track record" is a core superforecasting discipline, but until now
every ensemble component and panel perspective carried weight 1.0 — the claim
was gestural. This module turns scored history into evidence-based weights:

* For each resolved binary question, pair every component's own probability
  (ensemble components from the committed snapshot; perspective estimates from
  the panel run) with the committed aggregate on the SAME question, and Brier-
  score both against the confirmed outcome.
* A component's **edge** is ``mean(aggregate_brier - component_brier)`` over
  its paired observations — positive means the component beat the number the
  desk actually committed.
* Edges are shrunk toward zero with a pseudo-count prior (small samples barely
  move the weight) and mapped to a clipped multiplicative weight.

Anti-over-biasing posture (same philosophy as the calibration-bias loop):
weights are ADVISORY — nothing applies them silently. Components below the
sample-size gate report ``insufficient_track_record`` and weight 1.0. The
ledger does the IO (:meth:`ForecastLedger.component_track_record`); this
module is pure math so the gates are unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Defaults chosen so a real edge needs both size and consistency to move a
# weight far from 1.0: with shrink_n0=10, five observations keep only 1/3 of
# the raw edge; the clip stops any component from dominating or vanishing.
DEFAULT_MIN_COUNT = 5
DEFAULT_SHRINK_N0 = 10.0
DEFAULT_EDGE_SCALE = 4.0  # weight = 1 + scale * shrunk_edge (Brier edges are small)
DEFAULT_WEIGHT_CLIP = (0.25, 4.0)


@dataclass
class ComponentObservation:
    """One paired (component vs committed aggregate) scoring observation."""

    name: str
    kind: str  # "ensemble" | "panel"
    question_id: str
    component_brier: float
    aggregate_brier: float

    @property
    def edge(self) -> float:
        return self.aggregate_brier - self.component_brier


@dataclass
class ComponentTrackRecord:
    name: str
    kind: str
    count: int
    component_brier_mean: float
    aggregate_brier_mean: float
    edge_mean: float
    edge_shrunk: float
    recommended_weight: float
    status: str  # "measured" | "insufficient_track_record"
    question_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "count": self.count,
            "component_brier_mean": self.component_brier_mean,
            "aggregate_brier_mean": self.aggregate_brier_mean,
            "edge_mean": self.edge_mean,
            "edge_shrunk": self.edge_shrunk,
            "recommended_weight": self.recommended_weight,
            "status": self.status,
            "question_ids": list(self.question_ids),
        }


def shrink_edge(edge_mean: float, count: int, *, shrink_n0: float = DEFAULT_SHRINK_N0) -> float:
    """Shrink a raw mean edge toward zero by sample size (pseudo-count prior)."""
    if count <= 0:
        return 0.0
    return edge_mean * (count / (count + shrink_n0))


def edge_to_weight(
    edge_shrunk: float,
    *,
    scale: float = DEFAULT_EDGE_SCALE,
    clip: tuple[float, float] = DEFAULT_WEIGHT_CLIP,
) -> float:
    """Map a shrunk Brier edge to a multiplicative weight around 1.0."""
    low, high = clip
    return max(low, min(high, 1.0 + scale * edge_shrunk))


def summarize_components(
    observations: list[ComponentObservation],
    *,
    min_count: int = DEFAULT_MIN_COUNT,
    shrink_n0: float = DEFAULT_SHRINK_N0,
    edge_scale: float = DEFAULT_EDGE_SCALE,
    weight_clip: tuple[float, float] = DEFAULT_WEIGHT_CLIP,
) -> list[ComponentTrackRecord]:
    """Reduce paired observations into per-component track records.

    Components with fewer than ``min_count`` observations fail safe: status
    ``insufficient_track_record`` and weight exactly 1.0 (the shrunk edge is
    still reported so the table shows direction-of-travel).
    """
    by_key: dict[tuple[str, str], list[ComponentObservation]] = {}
    for obs in observations:
        by_key.setdefault((obs.kind, obs.name), []).append(obs)

    records: list[ComponentTrackRecord] = []
    for (kind, name), rows in sorted(by_key.items()):
        count = len(rows)
        component_mean = sum(r.component_brier for r in rows) / count
        aggregate_mean = sum(r.aggregate_brier for r in rows) / count
        edge_mean = sum(r.edge for r in rows) / count
        shrunk = shrink_edge(edge_mean, count, shrink_n0=shrink_n0)
        sufficient = count >= min_count
        records.append(
            ComponentTrackRecord(
                name=name,
                kind=kind,
                count=count,
                component_brier_mean=component_mean,
                aggregate_brier_mean=aggregate_mean,
                edge_mean=edge_mean,
                edge_shrunk=shrunk,
                recommended_weight=(
                    edge_to_weight(shrunk, scale=edge_scale, clip=weight_clip)
                    if sufficient
                    else 1.0
                ),
                status="measured" if sufficient else "insufficient_track_record",
                question_ids=sorted({r.question_id for r in rows}),
            )
        )
    # Strongest positive edge first; insufficient rows sink to the bottom.
    records.sort(key=lambda r: (r.status != "measured", -r.edge_shrunk, r.name))
    return records


def weights_by_name(
    records: list[ComponentTrackRecord],
    *,
    kind: str | None = None,
    measured_only: bool = True,
) -> dict[str, float]:
    """Return ``{component_name: recommended_weight}`` for downstream use."""
    out: dict[str, float] = {}
    for record in records:
        if kind is not None and record.kind != kind:
            continue
        if measured_only and record.status != "measured":
            continue
        out[record.name] = record.recommended_weight
    return out
