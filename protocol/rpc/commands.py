"""Wire models for the command-catalog / completion / slash RPCs (Arc A4).

``SlashCategory`` moves here from ``ui-tui/src/types.ts`` (it was hand-written
there and referenced by both ``CommandsCatalogResponse`` and the app-internal
``SlashCatalog``); the protocol is now its source of truth and ``types.ts``
re-exports it. NOTE: ``command.dispatch`` returns a 4-arm discriminated UNION
(``CommandDispatchResponse``) that has no single-model form — it stays a TS-only
alias in ``gatewayTypes.ts`` and is deliberately NOT modelled here."""

from __future__ import annotations

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
