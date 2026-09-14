"""Skill catalog and management response fields shared with the TUI."""

from typing import Any, Literal

from protocol.types import WireModel, wire_optional


class SkillsManageRequest(WireModel):
    session_id: str | None = None
    action: Literal["list", "search", "install", "browse", "inspect"] = "list"
    query: str = ""
    page: int = 0
    page_size: int = 20


class SkillItem(WireModel):
    name: str
    description: str | None = wire_optional()
    source: str | None = wire_optional()
    trust: str | None = wire_optional()


class SkillsManageResponse(WireModel):
    skills: dict[str, list[str]] | None = wire_optional()
    info: dict[str, Any] | None = wire_optional()
    results: list[SkillItem] | None = wire_optional()
    installed: bool | None = wire_optional()
    name: str | None = wire_optional()

    items: list[SkillItem] | None = wire_optional()
    page: int | None = wire_optional()
    total_pages: int | None = wire_optional()
    total: int | None = wire_optional()


class SkillsReloadRequest(WireModel):
    pass


class SkillsReloadResponse(WireModel):
    output: str
    result: dict[str, Any]
