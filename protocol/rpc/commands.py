"""Command catalog, completions and discriminated dispatch outcomes.

Python declarations own the command variants and generated TypeScript consumers.
"""

from __future__ import annotations

from typing import Literal

from pydantic import RootModel

from protocol.types import WireModel, wire_optional


class SlashCategory(WireModel):
    TS_NAME = "SlashCategory"

    name: str
    pairs: list[tuple[str, str]]


class GatewayCompletionItem(WireModel):
    TS_NAME = "GatewayCompletionItem"

    display: str
    text: str
    meta: str | None = wire_optional()


class CommandsCatalogRequest(WireModel):
    TS_NAME = "CommandsCatalogRequest"


class CommandsCatalogResponse(WireModel):
    TS_NAME = "CommandsCatalogResponse"

    canon: dict[str, str] | None = wire_optional()
    categories: list[SlashCategory] | None = wire_optional()
    pairs: list[tuple[str, str]] | None = wire_optional()
    skill_count: int | None = wire_optional()
    sub: dict[str, list[str]] | None = wire_optional()
    warning: str | None = wire_optional()


class CompletionRequest(WireModel):
    TS_NAME = "CompletionRequest"

    word: str | None = None

    text: str | None = None


class CompletionResponse(WireModel):
    TS_NAME = "CompletionResponse"

    items: list[GatewayCompletionItem] | None = wire_optional()
    replace_from: int | None = wire_optional()


class SlashExecRequest(WireModel):
    TS_NAME = "SlashExecRequest"

    command: str | None = None
    session_id: str | None = None


class SlashExecResponse(WireModel):
    TS_NAME = "SlashExecResponse"

    output: str | None = wire_optional()
    warning: str | None = wire_optional()


__all__ = [
    "SlashCategory",
    "GatewayCompletionItem",
    "CommandsCatalogRequest",
    "CommandsCatalogResponse",
    "CompletionRequest",
    "CompletionResponse",
    "SlashExecRequest",
    "SlashExecResponse",
]


class CommandDispatchRequest(WireModel):
    name: str
    arg: str = ""
    session_id: str | None = None


class CommandExecResult(WireModel):
    type: Literal["exec", "plugin"]
    output: str


class CommandAliasResult(WireModel):
    type: Literal["alias"]
    target: str


class CommandSkillResult(WireModel):
    type: Literal["skill"]
    name: str
    message: str


class CommandSendResult(WireModel):
    type: Literal["send"]
    message: str
    notice: str | None = wire_optional()


class CommandDispatchResponse(
    RootModel[
        CommandExecResult | CommandAliasResult | CommandSkillResult | CommandSendResult
    ]
):
    """Discriminated command outcomes, shared by Python and TypeScript consumers."""


class PasteCollapseRequest(WireModel):
    text: str


class PasteCollapseResponse(WireModel):
    placeholder: str
    path: str
    lines: int
