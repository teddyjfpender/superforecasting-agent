"""Cross-instance collaboration — the ``sfp/1`` card renderers (multiplayer M2).

Renders real ledger objects (a forecast snapshot, an evidence item, a calibration
lesson) into ``sfp/1`` payloads with a human-readable Block Kit surface, per
``docs/plans/2026-07-05-multiplayer-slack-harness.md``. The wire models live in
:mod:`protocol.collab`; the receiving import pipeline + router are M3.
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

__all__ = [
    "RenderedCard",
    "criteria_hash",
    "build_forecast_card_body",
    "render_forecast_card",
    "build_evidence_share_body",
    "render_evidence_share",
    "build_lesson_share_body",
    "render_lesson_share",
]
