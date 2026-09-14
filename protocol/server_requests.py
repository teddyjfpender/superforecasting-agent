"""Correlated interactive requests; legacy notifications use the same payloads."""

from typing import Literal

from protocol.events.prompts import (
    ApprovalRequest,
    ClarifyRequest,
    SecretRequest,
    SudoRequest,
)
from protocol.types import WireModel


class ClarifyResult(WireModel):
    answer: str


class SudoResult(WireModel):
    password: str


class SecretResult(WireModel):
    value: str


class ApprovalResult(WireModel):
    choice: Literal["once", "session", "always", "deny"]


SERVER_REQUESTS: dict[str, tuple[type[WireModel], type[WireModel]]] = {
    "clarify": (ClarifyRequest, ClarifyResult),
    "sudo": (SudoRequest, SudoResult),
    "secret": (SecretRequest, SecretResult),
    "approval": (ApprovalRequest, ApprovalResult),
}
