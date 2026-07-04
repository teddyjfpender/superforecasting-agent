"""Wire models for the voice-mode events (``tui_gateway/server.py``).

``voice.status`` reports the VAD loop state; ``voice.transcript`` delivers a
finished transcription OR the 3-strikes ``no_speech_limit`` signal that flips
continuous mode off.
"""

from __future__ import annotations

from protocol.types import WireModel, wire_optional


class VoiceStatus(WireModel):
    """``voice.status`` — VAD state: listening / transcribing / speaking / idle."""

    TS_NAME = "VoiceStatusPayload"

    state: str | None = wire_optional()


class VoiceTranscript(WireModel):
    """``voice.transcript`` — a transcript (``text``) OR the silence-limit signal."""

    TS_NAME = "VoiceTranscriptPayload"

    text: str | None = wire_optional()
    no_speech_limit: bool | None = wire_optional()


__all__ = ["VoiceStatus", "VoiceTranscript"]
