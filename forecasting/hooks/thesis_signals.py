"""Thesis-remediation hook signals — computed READ-ONLY from a thesis's current
snapshot + members, for the event-band-honesty gate family.

These feed four gates that make three silent thesis defects visible:

  * ``event_band_earned`` — a thesis with members but no configured event (name
    ``set-event``), or an event band whose member-interval coverage is too thin
    (a default-width band masquerading as measured uncertainty).
  * ``health_not_probability`` — a mean-index HEALTH value presented without the
    index label and without an event band (the index-as-probability lie).
  * ``thesis_correlation_transparency`` — a low n_eff / member ratio (a
    co-directional cluster: one bet dressed as many).

Pure-ish (the ledger handle + stdlib): no writes, no LLM. Absence is always the
PASSING state, so a bare/legacy thesis never false-fires.
"""

from __future__ import annotations

from typing import Any


def _payload_of(snapshot: Any) -> dict[str, Any]:
    pod = getattr(snapshot, "probability_or_distribution", None)
    return pod if isinstance(pod, dict) else {}


def snapshot_reference_class_count(snapshot: Any) -> int:
    """The TRUE count of reference classes linked on this snapshot (unmasked)."""
    refs = getattr(snapshot, "reference_class_refs", None) or []
    try:
        return len([r for r in refs if r])
    except TypeError:
        return 0


def thesis_remediation_signals(ledger, question: Any, snapshot: Any) -> dict[str, Any]:
    """Compute the thesis-remediation gate signals from a thesis's current state.

    Returns a dict of HookContext field values. Only meaningful for a thesis/factor
    question; the caller gates on ``is_thesis_or_factor`` before applying the rules,
    so the defaults returned here (has_event True, full coverage, labeled) are the
    passing state for anything that is not a thesis.
    """
    out: dict[str, Any] = {
        "thesis_has_event": True,
        "thesis_member_count": 0,
        "thesis_event_interval_coverage": None,
        "thesis_health_present": False,
        "thesis_health_index_labeled": True,
        "thesis_n_eff": None,
        "thesis_n_eff_ratio": None,
    }
    payload = _payload_of(snapshot)
    meta = getattr(snapshot, "metadata", None)
    meta = meta if isinstance(meta, dict) else {}

    # member count
    try:
        out["thesis_member_count"] = len(ledger.list_thesis_members(question.id))
    except Exception:
        out["thesis_member_count"] = 0

    # event presence: a configured spec OR a stamped event_probability headline
    has_event = False
    try:
        has_event = ledger._thesis_event_spec(question) is not None
    except Exception:
        has_event = False
    has_event = has_event or ("event_probability" in payload)
    out["thesis_has_event"] = has_event

    # member-interval coverage of the event band (fraction of participants that
    # carry their OWN published interval; the rest ride the default width).
    event_meta = meta.get("event") if isinstance(meta.get("event"), dict) else {}
    band = event_meta.get("band") if isinstance(event_meta.get("band"), dict) else {}
    if band:
        with_iv = band.get("members_with_interval")
        defaulted = band.get("members_defaulted")
        if isinstance(with_iv, (int, float)) and isinstance(defaulted, (int, float)):
            participants = float(with_iv) + float(defaulted)
            out["thesis_event_interval_coverage"] = (float(with_iv) / participants) if participants > 0 else None

    # health present + index label. The aggregate stamps ``thesis_headline_kind``
    # into the snapshot metadata ("index" when there is no event, "event_probability"
    # when there is); the label being present-and-index is the passing state.
    out["thesis_health_present"] = payload.get("health") is not None
    headline_kind = meta.get("thesis_headline_kind")
    out["thesis_health_index_labeled"] = headline_kind == "index" or has_event

    # correlation transparency: n_eff / member_count
    n_eff = payload.get("n_eff")
    if isinstance(n_eff, (int, float)) and not isinstance(n_eff, bool):
        out["thesis_n_eff"] = float(n_eff)
        mc = out["thesis_member_count"] or 0
        if mc > 0:
            out["thesis_n_eff_ratio"] = float(n_eff) / mc
    return out
