"""Cross-instance collaboration — the ``sfp/1`` cards (M2) + import pipeline (M3).

Renders real ledger objects (a forecast snapshot, an evidence item, a calibration
lesson) into ``sfp/1`` payloads with a human-readable Block Kit surface (M2), and
receives peer payloads through the honesty-gated import pipeline + router (M3), per
``docs/plans/2026-07-05-multiplayer-slack-harness.md``. The wire models live in
:mod:`protocol.collab`.
"""

from __future__ import annotations

from forecasting.collab.cards import (
    RenderedCard,
    build_evidence_share_body,
    build_forecast_card_body,
    build_lesson_share_body,
    criteria_hash,
    render_evidence_share,
    render_forecast_card,
    render_lesson_share,
)
from forecasting.collab.directory import (
    allowed_instances,
    build_hello_envelope,
    emit_hello,
    is_allowed,
    load_directory,
    record_agent,
)
from forecasting.collab.imports import (
    ImportResult,
    accept_envelope,
    import_evidence_share,
    import_forecast_card,
    import_lesson_share,
    list_collab_events,
    provenance_of,
)
from forecasting.collab.router import (
    CollabRouter,
    RouteResult,
    extract_sfp_metadata,
    route_slack_metadata_event,
)

__all__ = [
    # M2 cards
    "RenderedCard",
    "criteria_hash",
    "build_forecast_card_body",
    "render_forecast_card",
    "build_evidence_share_body",
    "render_evidence_share",
    "build_lesson_share_body",
    "render_lesson_share",
    # M3 directory
    "load_directory",
    "record_agent",
    "allowed_instances",
    "is_allowed",
    "build_hello_envelope",
    "emit_hello",
    # M3 imports
    "ImportResult",
    "provenance_of",
    "accept_envelope",
    "import_forecast_card",
    "import_evidence_share",
    "import_lesson_share",
    "list_collab_events",
    # M3 router
    "CollabRouter",
    "RouteResult",
    "extract_sfp_metadata",
    "route_slack_metadata_event",
]
