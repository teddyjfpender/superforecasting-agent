"""Wire models for the ``config.*`` + ``setup.status`` RPCs (Arc A4).

Transcribed from the deleted ``ui-tui/src/gatewayTypes.ts`` mirrors. The display
config carries several genuinely-multi-typed keys (``mouse_tracking`` may be a
bool / number / string / null when hand-edited); those are modelled as the exact
unions the mirror declared so the generated TS keeps its runtime-validation
contract.
"""

from __future__ import annotations

from typing import Any, Literal

from protocol.rpc.session import SessionInfo
from protocol.types import WireModel, wire_optional


class ConfigDisplayConfig(WireModel):
    TS_NAME = "ConfigDisplayConfig"

    bell_on_complete: bool | None = wire_optional()
    busy_input_mode: str | None = wire_optional()
    details_mode: str | None = wire_optional()
    inline_diffs: bool | None = wire_optional()
    # Raw yaml value — may be non-bool if hand-edited (normalized at runtime).
    mouse_tracking: bool | int | str | None = wire_optional(nullable=True)
    sections: dict[str, str] | None = wire_optional()
    show_cost: bool | None = wire_optional()
    show_reasoning: bool | None = wire_optional()
    streaming: bool | None = wire_optional()
    thinking_mode: str | None = wire_optional()
    tui_auto_resume_recent: bool | None = wire_optional()
    tui_compact: bool | None = wire_optional()
    # Legacy alias for display.mouse_tracking.
    tui_mouse: bool | int | str | None = wire_optional(nullable=True)
    # Forward-compat: an unknown indicator style falls back at runtime; typed str.
    tui_status_indicator: str | None = wire_optional()
    tui_statusbar: Literal["bottom", "off", "on", "top"] | bool = wire_optional()


class ConfigVoiceConfig(WireModel):
    TS_NAME = "ConfigVoiceConfig"

    # Raw yaml.safe_load() value; may be non-string if hand-edited.
    record_key: Any = wire_optional()


class ConfigFullConfig(WireModel):
    TS_NAME = "ConfigFullConfig"

    display: ConfigDisplayConfig | None = wire_optional()
    voice: ConfigVoiceConfig | None = wire_optional()


class ConfigFullRequest(WireModel):
    TS_NAME = "ConfigFullRequest"


class ConfigFullResponse(WireModel):
    TS_NAME = "ConfigFullResponse"

    config: ConfigFullConfig | None = wire_optional()


class ConfigMtimeResponse(WireModel):
    TS_NAME = "ConfigMtimeResponse"

    mtime: int | None = wire_optional()


class ConfigGetValueRequest(WireModel):
    TS_NAME = "ConfigGetValueRequest"

    key: str | None = None


class ConfigGetValueResponse(WireModel):
    TS_NAME = "ConfigGetValueResponse"

    display: str | None = wire_optional()
    home: str | None = wire_optional()
    value: str | None = wire_optional()


class ConfigSetRequest(WireModel):
    TS_NAME = "ConfigSetRequest"

    key: str | None = None
    value: str | None = None
    session_id: str | None = None


class ConfigSetResponse(WireModel):
    TS_NAME = "ConfigSetResponse"

    credential_warning: str | None = wire_optional()
    history_reset: bool | None = wire_optional()
    info: SessionInfo | None = wire_optional()
    value: str | None = wire_optional()
    warning: str | None = wire_optional()


class SetupStatusRequest(WireModel):
    TS_NAME = "SetupStatusRequest"


class SetupStatusResponse(WireModel):
    TS_NAME = "SetupStatusResponse"

    provider_configured: bool | None = wire_optional()


class ConfigProviderEntry(WireModel):
    """Catalog identity; a configuration read never authenticates a provider."""

    id: str
    label: str
    aliases: list[str]
    authenticated: None = None


class ConfigProviderResponse(WireModel):
    """Configured selection, distinct from the credential-resolved live route."""

    model: str
    provider: str
    authentication_status: Literal["not_checked"]
    providers: list[ConfigProviderEntry]


__all__ = [
    "ConfigDisplayConfig",
    "ConfigVoiceConfig",
    "ConfigFullConfig",
    "ConfigProviderEntry",
    "ConfigProviderResponse",
    "ConfigFullRequest",
    "ConfigFullResponse",
    "ConfigMtimeResponse",
    "ConfigGetValueRequest",
    "ConfigGetValueResponse",
    "ConfigSetRequest",
    "ConfigSetResponse",
    "SetupStatusRequest",
    "SetupStatusResponse",
]
