"""Wire models for the interaction / utility RPCs (Arc A4): prompt submission,
the blocking-prompt ack responses, shell / clipboard / image / input, tools
configure, reload / process control, browser manage, and the ``skin.changed``
payload (``GatewaySkin``). Transcribed from the deleted ``gatewayTypes.ts``
mirrors.

``GatewaySkin`` is the ``skin.changed`` event payload as the TUI reads it (nested
under the ``GatewayEvent`` union); it is a leaner sibling of the server-emitted
``SkinPayload`` (``protocol/events/gateway.py``) — kept distinct so the union
references the exact client-side shape (``colors`` typed ``Record<string,string>``)."""

from __future__ import annotations

from protocol.rpc.session import SessionInfo
from protocol.types import WireModel, wire_optional


class GatewaySkin(WireModel):
    TS_NAME = "GatewaySkin"

    appearance: str | None = wire_optional()
    banner_hero: str | None = wire_optional()
    banner_logo: str | None = wire_optional()
    branding: dict[str, str] | None = wire_optional()
    colors: dict[str, str] | None = wire_optional()
    help_header: str | None = wire_optional()
    tool_prefix: str | None = wire_optional()


class OkResponse(WireModel):
    """A bare ``{ok?}`` acknowledgement — shared by prompt.submit / terminal.resize
    / the blocking-prompt *.respond RPCs. Each keeps its own TS name so consumers
    reference a stable per-RPC type."""

    ok: bool | None = wire_optional()


class PromptSubmitRequest(WireModel):
    TS_NAME = "PromptSubmitRequest"

    text: str | None = None
    session_id: str | None = None


class PromptSubmitResponse(OkResponse):
    TS_NAME = "PromptSubmitResponse"


class PromptBackgroundRequest(WireModel):
    TS_NAME = "PromptBackgroundRequest"

    text: str | None = None
    session_id: str | None = None


class BackgroundStartResponse(WireModel):
    TS_NAME = "BackgroundStartResponse"

    task_id: str | None = wire_optional()


class ClarifyRespondRequest(WireModel):
    TS_NAME = "ClarifyRespondRequest"

    request_id: str | None = None
    session_id: str | None = None


class ClarifyRespondResponse(OkResponse):
    TS_NAME = "ClarifyRespondResponse"


class ApprovalRespondResponse(OkResponse):
    TS_NAME = "ApprovalRespondResponse"


class SudoRespondResponse(OkResponse):
    TS_NAME = "SudoRespondResponse"


class SecretRespondResponse(OkResponse):
    TS_NAME = "SecretRespondResponse"


class RespondRequest(WireModel):
    TS_NAME = "RespondRequest"

    request_id: str | None = None
    session_id: str | None = None


class ShellExecRequest(WireModel):
    TS_NAME = "ShellExecRequest"

    command: str | None = None


class ShellExecResponse(WireModel):
    TS_NAME = "ShellExecResponse"

    code: int
    stderr: str | None = wire_optional()
    stdout: str | None = wire_optional()


class ClipboardPasteRequest(WireModel):
    TS_NAME = "ClipboardPasteRequest"

    session_id: str | None = None


class ClipboardPasteResponse(WireModel):
    TS_NAME = "ClipboardPasteResponse"

    attached: bool | None = wire_optional()
    count: int | None = wire_optional()
    height: int | None = wire_optional()
    message: str | None = wire_optional()
    token_estimate: int | None = wire_optional()
    width: int | None = wire_optional()


class InputDetectDropRequest(WireModel):
    TS_NAME = "InputDetectDropRequest"

    text: str | None = None


class InputDetectDropResponse(WireModel):
    TS_NAME = "InputDetectDropResponse"

    height: int | None = wire_optional()
    is_image: bool | None = wire_optional()
    matched: bool | None = wire_optional()
    name: str | None = wire_optional()
    text: str | None = wire_optional()
    token_estimate: int | None = wire_optional()
    width: int | None = wire_optional()


class TerminalResizeRequest(WireModel):
    TS_NAME = "TerminalResizeRequest"

    cols: int | None = None
    rows: int | None = None
    session_id: str | None = None


class TerminalResizeResponse(OkResponse):
    TS_NAME = "TerminalResizeResponse"


class ImageAttachRequest(WireModel):
    TS_NAME = "ImageAttachRequest"

    session_id: str | None = None


class ImageAttachResponse(WireModel):
    TS_NAME = "ImageAttachResponse"

    height: int | None = wire_optional()
    name: str | None = wire_optional()
    remainder: str | None = wire_optional()
    token_estimate: int | None = wire_optional()
    width: int | None = wire_optional()


class ToolsConfigureRequest(WireModel):
    TS_NAME = "ToolsConfigureRequest"

    action: str | None = None
    names: list[str] | None = None
    session_id: str | None = None


class ToolsConfigureResponse(WireModel):
    TS_NAME = "ToolsConfigureResponse"

    changed: list[str] | None = wire_optional()
    enabled_toolsets: list[str] | None = wire_optional()
    info: SessionInfo | None = wire_optional()
    missing_servers: list[str] | None = wire_optional()
    reset: bool | None = wire_optional()
    unknown: list[str] | None = wire_optional()


class ReloadMcpRequest(WireModel):
    TS_NAME = "ReloadMcpRequest"


class ReloadMcpResponse(WireModel):
    TS_NAME = "ReloadMcpResponse"

    message: str | None = wire_optional()
    status: str | None = wire_optional()


class ReloadEnvRequest(WireModel):
    TS_NAME = "ReloadEnvRequest"


class ReloadEnvResponse(WireModel):
    TS_NAME = "ReloadEnvResponse"

    updated: int | None = wire_optional()


class ProcessStopRequest(WireModel):
    TS_NAME = "ProcessStopRequest"

    session_id: str | None = wire_optional()


class ProcessStopResponse(WireModel):
    TS_NAME = "ProcessStopResponse"

    killed: int | None = wire_optional()


class BrowserManageRequest(WireModel):
    TS_NAME = "BrowserManageRequest"

    action: str | None = None


class BrowserManageResponse(WireModel):
    TS_NAME = "BrowserManageResponse"

    connected: bool | None = wire_optional()
    messages: list[str] | None = wire_optional()
    url: str | None = wire_optional()


__all__ = [
    "GatewaySkin",
    "PromptSubmitRequest",
    "PromptSubmitResponse",
    "PromptBackgroundRequest",
    "BackgroundStartResponse",
    "ClarifyRespondRequest",
    "ClarifyRespondResponse",
    "ApprovalRespondResponse",
    "SudoRespondResponse",
    "SecretRespondResponse",
    "RespondRequest",
    "ShellExecRequest",
    "ShellExecResponse",
    "ClipboardPasteRequest",
    "ClipboardPasteResponse",
    "InputDetectDropRequest",
    "InputDetectDropResponse",
    "TerminalResizeRequest",
    "TerminalResizeResponse",
    "ImageAttachRequest",
    "ImageAttachResponse",
    "ToolsConfigureRequest",
    "ToolsConfigureResponse",
    "ReloadMcpRequest",
    "ReloadMcpResponse",
    "ReloadEnvRequest",
    "ReloadEnvResponse",
    "ProcessStopRequest",
    "ProcessStopResponse",
    "BrowserManageRequest",
    "BrowserManageResponse",
]
