"""Wire models for ``model.options`` (Arc A4). The model-picker payload,
transcribed from the deleted ``gatewayTypes.ts`` mirrors."""

from __future__ import annotations

from protocol.types import WireModel, wire_optional


class ModelOptionProvider(WireModel):
    TS_NAME = "ModelOptionProvider"

    name: str
    slug: str
    auth_type: str | None = wire_optional()
    authenticated: bool | None = wire_optional()
    is_current: bool | None = wire_optional()
    key_env: str | None = wire_optional()
    models: list[str] | None = wire_optional()
    reasoning_effort_models: list[str] | None = wire_optional()
    reasoning_efforts: list[str] | None = wire_optional()
    supports_reasoning_effort: bool | None = wire_optional()
    total_models: int | None = wire_optional()
    warning: str | None = wire_optional()


class ModelOptionsRequest(WireModel):
    TS_NAME = "ModelOptionsRequest"


class ModelOptionsResponse(WireModel):
    TS_NAME = "ModelOptionsResponse"

    model: str | None = wire_optional()
    provider: str | None = wire_optional()
    providers: list[ModelOptionProvider] | None = wire_optional()
    reasoning_effort: str | None = wire_optional()


__all__ = ["ModelOptionProvider", "ModelOptionsRequest", "ModelOptionsResponse"]
