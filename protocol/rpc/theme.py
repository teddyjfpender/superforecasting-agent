"""Wire models for ``theme.list`` (Arc A4). Transcribed from the deleted
``gatewayTypes.ts`` ``ThemeOption`` / ``ThemeListResponse`` mirrors."""

from __future__ import annotations

from protocol.types import WireModel, wire_optional


class ThemeOption(WireModel):
    TS_NAME = "ThemeOption"

    name: str
    branding: dict[str, str] | None = wire_optional()
    colors: dict[str, str] | None = wire_optional()
    description: str | None = wire_optional()
    source: str | None = wire_optional()


class ThemeListRequest(WireModel):
    TS_NAME = "ThemeListRequest"


class ThemeListResponse(WireModel):
    TS_NAME = "ThemeListResponse"

    active: str | None = wire_optional()
    appearance: str | None = wire_optional()
    themes: list[ThemeOption] | None = wire_optional()


__all__ = ["ThemeOption", "ThemeListRequest", "ThemeListResponse"]
