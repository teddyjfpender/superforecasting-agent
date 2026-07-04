"""Wire models for the sessionless forecast-desk events (``tui_gateway/server.py``).

``cron.fired`` (the background cron ticker fired N jobs), ``review.sweep`` (the
due-sweeper's started/done lifecycle), and ``review.summary`` (a self-improvement
review's persistent note). All are sessionless (no ``session_id``).
"""

from __future__ import annotations

from protocol.types import WireModel, wire_optional


class CronFired(WireModel):
    """``cron.fired`` — the background cron ticker fired ``count`` scheduled jobs."""

    TS_NAME = "CronFiredPayload"

    count: int | None = wire_optional()


class ReviewSweep(WireModel):
    """``review.sweep`` — the due-sweeper lifecycle, discriminated on ``phase``.

    ``phase='started'`` carries ``due_count``; ``phase='done'`` carries
    ``refreshed`` / ``alerts`` / ``duration_ms`` (``_emit_review_sweep``).
    """

    TS_NAME = "ReviewSweepPayload"

    phase: str
    due_count: int | None = wire_optional()
    refreshed: int | None = wire_optional()
    alerts: int | None = wire_optional()
    duration_ms: int | None = wire_optional()


class ReviewSummary(WireModel):
    """``review.summary`` — a persistent summary of what a background review saved."""

    TS_NAME = "ReviewSummaryPayload"

    text: str | None = wire_optional()


__all__ = ["CronFired", "ReviewSweep", "ReviewSummary"]
