"""Wire models for the ``voice.*`` RPCs (Arc A4). Transcribed from the deleted
``gatewayTypes.ts`` mirrors (the ``voice.status`` / ``voice.transcript`` EVENTS
are modelled separately in ``protocol/events/voice.py``)."""

from __future__ import annotations

from typing import Literal

from protocol.types import WireModel, wire_optional


class VoiceToggleRequest(WireModel):
    TS_NAME = "VoiceToggleRequest"

    session_id: str | None = None


class VoiceToggleResponse(WireModel):
    TS_NAME = "VoiceToggleResponse"

    audio_available: bool | None = wire_optional()
    available: bool | None = wire_optional()
    details: str | None = wire_optional()
    enabled: bool | None = wire_optional()
    record_key: str | None = wire_optional()
    stt_available: bool | None = wire_optional()
    tts: bool | None = wire_optional()


class VoiceRecordRequest(WireModel):
    TS_NAME = "VoiceRecordRequest"

    session_id: str | None = None


class VoiceRecordResponse(WireModel):
    TS_NAME = "VoiceRecordResponse"

    status: Literal["busy", "recording", "stopped"] | None = wire_optional()
    text: str | None = wire_optional()


__all__ = [
    "VoiceToggleRequest",
    "VoiceToggleResponse",
    "VoiceRecordRequest",
    "VoiceRecordResponse",
]
