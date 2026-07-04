"""Wire models for the ``rollback.*`` RPCs (Arc A4). Transcribed from the deleted
``gatewayTypes.ts`` mirrors."""

from __future__ import annotations

from protocol.types import WireModel, wire_optional


class RollbackCheckpoint(WireModel):
    TS_NAME = "RollbackCheckpoint"

    hash: str
    message: str | None = wire_optional()
    timestamp: str | None = wire_optional()


class RollbackListRequest(WireModel):
    TS_NAME = "RollbackListRequest"


class RollbackListResponse(WireModel):
    TS_NAME = "RollbackListResponse"

    checkpoints: list[RollbackCheckpoint] | None = wire_optional()
    enabled: bool | None = wire_optional()


class RollbackDiffRequest(WireModel):
    TS_NAME = "RollbackDiffRequest"

    hash: str | None = None


class RollbackDiffResponse(WireModel):
    TS_NAME = "RollbackDiffResponse"

    diff: str | None = wire_optional()
    rendered: str | None = wire_optional()
    stat: str | None = wire_optional()


class RollbackRestoreRequest(WireModel):
    TS_NAME = "RollbackRestoreRequest"

    hash: str | None = None


class RollbackRestoreResponse(WireModel):
    TS_NAME = "RollbackRestoreResponse"

    error: str | None = wire_optional()
    history_removed: int | None = wire_optional()
    message: str | None = wire_optional()
    reason: str | None = wire_optional()
    restored_to: str | None = wire_optional()
    success: bool | None = wire_optional()


__all__ = [
    "RollbackCheckpoint",
    "RollbackListRequest",
    "RollbackListResponse",
    "RollbackDiffRequest",
    "RollbackDiffResponse",
    "RollbackRestoreRequest",
    "RollbackRestoreResponse",
]
