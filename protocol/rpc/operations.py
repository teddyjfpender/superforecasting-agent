"""Small support operations exposed by the bundled gateway.

Provider and plugin payloads stay opaque where their schemas are extension-owned.
The operation envelopes and stable fields are owned here.
"""

from typing import Any

from protocol.types import WireModel, wire_optional


class EmptyRequest(WireModel):
    pass


class OperationSessionRequest(WireModel):
    session_id: str | None = None


class OneShotRequest(OperationSessionRequest):
    input: str = ""
    instructions: str = ""
    template: str | None = None
    variables: dict[str, Any] | None = None
    task: str = "title_generation"
    max_tokens: int = 1024
    temperature: float | None = None


class TextResponse(WireModel):
    text: str


class PluginItem(WireModel):
    name: str
    version: str
    enabled: bool


class PluginsResponse(WireModel):
    plugins: list[PluginItem]


class SectionsResponse(WireModel):
    sections: list[dict[str, Any]]


class CliExecRequest(WireModel):
    argv: list[str] = []
    timeout: int = 240


class CliExecResponse(WireModel):
    blocked: bool
    code: int
    output: str
    hint: str | None = wire_optional()


class CommandResolveRequest(WireModel):
    name: str


class CommandResolveResponse(WireModel):
    canonical: str
    description: str
    category: str


class ToolsetsResponse(WireModel):
    toolsets: list[dict[str, Any]]


class CronManageRequest(WireModel):
    action: str = "list"
    name: str = ""
    schedule: str = ""
    prompt: str = ""


class CronManageResponse(WireModel):
    status: str | None = wire_optional()
    error: str | None = wire_optional()
    message: str | None = wire_optional()
    job: dict[str, Any] | None = wire_optional()
    jobs: list[dict[str, Any]] | None = wire_optional()
    count: int | None = wire_optional()
    success: bool | None = wire_optional()


class VoiceTtsRequest(OperationSessionRequest):
    text: str


class VoiceTtsResponse(WireModel):
    status: str


class InsightsRequest(WireModel):
    days: int = 30
    source: str | None = None


class InsightsResponse(WireModel):
    days: int
    sessions: int
    messages: int


class NewsArticle(WireModel):
    title: str = ""
    summary: str = ""
    source: str = ""


class NewsSearchRequest(WireModel):
    query: str
    articles: list[NewsArticle]
    limit: int = 25


class NewsSearchResponse(WireModel):
    results: list[dict[str, Any]]
    engine: str


class EventsReplayRequest(WireModel):
    session_id: str
    since_id: int = 0
    types: list[str] | str | None = None
    limit: int = 1000


class EventsReplayResponse(WireModel):
    session_id: str
    frames: list[dict[str, Any]]
    records: list[dict[str, Any]]
    count: int
    since_id: int
    last_id: int
