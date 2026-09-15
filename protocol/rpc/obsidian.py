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

    limit: int = 100


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

    limit: int = 50

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


class ObsidianWriteRequest(WireModel):
    rel_path: str
    content: str
    expected_content: str | None = None


class ObsidianCreateRequest(WireModel):
    rel_path: str
    content: str = ""
    title: str = ""


class ObsidianAppendRequest(WireModel):
    rel_path: str
    text: str


class ObsidianWriteResponse(WireModel):
    ok: bool
    rel_path: str
    size: int | None = wire_optional()


class ObsidianSetupResponse(WireModel):
    ok: bool
    vault: str
    created: list[str]
    skipped: list[str]
