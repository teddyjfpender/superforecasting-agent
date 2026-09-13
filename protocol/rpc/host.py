"""Host compatibility admission, shared by local and remote transports."""
from pydantic import ConfigDict, Field

from protocol.types import WireModel


class HostNegotiateRequest(WireModel):
    TS_NAME = "HostNegotiateRequest"
    model_config = ConfigDict(extra="forbid", strict=True)

    protocol_version: int = Field(ge=1)
    required_capabilities: list[str] = Field(default_factory=list)


class HostNegotiateResponse(WireModel):
    TS_NAME = "HostNegotiateResponse"

    protocol_version: int
    min_protocol_version: int
    capabilities: list[str]
