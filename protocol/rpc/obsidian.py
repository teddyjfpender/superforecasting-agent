"""Wire models for the ``obsidian.*`` vault RPCs (Arc A4). Transcribed from the
deleted ``gatewayTypes.ts`` mirrors."""

from __future__ import annotations

from protocol.types import WireModel, wire_optional


class ObsidianNote(WireModel):
    TS_NAME = "ObsidianNote"

    excerpt: str | None = wire_optional()
    folder: str | None = wire_optional()
    links: list[str] | None = wire_optional()
    modified: str | None = wire_optional()
    rel_path: str | None = wire_optional()
    size: int | None = wire_optional()
    title: str | None = wire_optional()


class ObsidianStatusRequest(WireModel):
    TS_NAME = "ObsidianStatusRequest"


class ObsidianStatusResponse(WireModel):
    TS_NAME = "ObsidianStatusResponse"

    count: int | None = wire_optional()
    exists: bool | None = wire_optional()
    notes: list[ObsidianNote] | None = wire_optional()
    vault: str | None = wire_optional(nullable=True)


class ObsidianNoteRequest(WireModel):
    TS_NAME = "ObsidianNoteRequest"

    rel_path: str | None = None


class ObsidianNoteResponse(WireModel):
    TS_NAME = "ObsidianNoteResponse"

    content: str | None = wire_optional()
    rel_path: str | None = wire_optional()
    size: int | None = wire_optional()
    truncated: bool | None = wire_optional()


class ObsidianSearchRequest(WireModel):
    TS_NAME = "ObsidianSearchRequest"

    query: str | None = None


class ObsidianSearchResult(WireModel):
    TS_NAME = "ObsidianSearchResult"

    line: int | None = wire_optional()
    matched_terms: int | None = wire_optional()
    rel_path: str | None = wire_optional()
    score: float | None = wire_optional()
    snippet: str | None = wire_optional()
    title: str | None = wire_optional()


class ObsidianSearchResponse(WireModel):
    TS_NAME = "ObsidianSearchResponse"

    count: int | None = wire_optional()
    query: str | None = wire_optional()
    results: list[ObsidianSearchResult] | None = wire_optional()


__all__ = [
    "ObsidianNote",
    "ObsidianStatusRequest",
    "ObsidianStatusResponse",
    "ObsidianNoteRequest",
    "ObsidianNoteResponse",
    "ObsidianSearchRequest",
    "ObsidianSearchResult",
    "ObsidianSearchResponse",
]
