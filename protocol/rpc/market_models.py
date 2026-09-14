"""Market-model operation envelopes; model packets retain their versioned data."""

from typing import Any

from protocol.types import WireModel, wire_optional


class ModelIdentityRequest(WireModel):
    id: str


class ModelSessionRequest(ModelIdentityRequest):
    session_id: str | None = None


class ModelParameters(WireModel):
    analysis_type: str = ""
    assumptions: str = ""
    depth: str = "standard"
    horizon: str = ""
    question: str = ""
    tickers: list[str] = []
    title: str | None = wire_optional()
    tags: list[str] | None = wire_optional()


class ModelCreateRequest(WireModel):
    question: str
    session_id: str | None = None
    params: ModelParameters | None = None


class ModelChatRequest(ModelSessionRequest):
    message: str
    params: ModelParameters | None = None


class ModelGetRequest(ModelSessionRequest):
    version: int | None = None


class ModelListRequest(WireModel):
    status: str | None = "active"
    limit: int = 200


class ModelBuildResponse(WireModel):
    model_id: str
    status: str
    version: int | None = wire_optional(nullable=True)
    presentation: dict[str, Any] | None = wire_optional(nullable=True)
    renarrated: bool | None = wire_optional()


class ModelListResponse(WireModel):
    models: list[dict[str, Any]]


class ModelGetResponse(WireModel):
    packet: dict[str, Any]


class ModelExportResponse(WireModel):
    path: str
    bytes: int


class ModelDeleteResponse(WireModel):
    deleted: bool


class ModelForecastResponse(WireModel):
    model_id: str
    question_id: str | None
    model_run_id: str | None
    reference_class_id: str | None
    seed: dict[str, Any] | None
