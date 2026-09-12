"""Live native command events, distinct from durable forecast-turn records."""

from typing import Literal

from protocol.types import WireModel


class CommandStarted(WireModel):
    command_id: str
    request_id: str
    name: str


class CommandOutput(WireModel):
    command_id: str
    stream: Literal["stdout", "stderr"]
    text: str


class CommandFinished(WireModel):
    command_id: str
    status: Literal["finished", "cancelled", "failed"]
