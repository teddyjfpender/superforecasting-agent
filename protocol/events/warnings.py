"""DEPRECATED legacy-alias events for the warning-automode job (Arc B compat).

The warning-automode type on the detached-job runtime emits the canonical
``jobs.progress`` / ``jobs.complete`` / ``jobs.error`` events AND — because it
declares an ``alias_namespace`` — these legacy ``forecast.warnings.automode.*``
frames alongside them (``tui_gateway/jobs_rpc.py``), so the alerts view keeps
working unchanged. New consumers should read ``jobs.*``; these are typed here
only so the legacy consumer references generated constants, not raw strings.
"""

from __future__ import annotations

from typing import Any

from protocol.types import WireModel, wire_optional


class AutomodeProgress(WireModel):
    """DEPRECATED ``forecast.warnings.automode.progress`` — use ``jobs.progress``."""

    TS_NAME = "AutomodeProgressPayload"

    job_id: str
    phase: str | None = wire_optional()
    done: int | None = wire_optional()
    total: int | None = wire_optional()
    remaining: int | None = wire_optional()
    alert_id: str | None = wire_optional()
    reason: str | None = wire_optional()
    status: str | None = wire_optional()
    cancelled: bool | None = wire_optional()
    dry_run: bool | None = wire_optional()


class AutomodeComplete(WireModel):
    """DEPRECATED ``forecast.warnings.automode.complete`` — use ``jobs.complete``."""

    TS_NAME = "AutomodeCompletePayload"

    job_id: str
    processed: int | None = wire_optional()
    total: int | None = wire_optional()
    cancelled: bool | None = wire_optional()
    dry_run: bool | None = wire_optional()
    tally: dict[str, Any] | None = wire_optional()


class AutomodeError(WireModel):
    """DEPRECATED ``forecast.warnings.automode.error`` — use ``jobs.error``."""

    TS_NAME = "AutomodeErrorPayload"

    job_id: str
    message: str | None = wire_optional()


__all__ = ["AutomodeProgress", "AutomodeComplete", "AutomodeError"]
