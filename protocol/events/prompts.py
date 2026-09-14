"""Wire models for the blocking-prompt events (``tui_gateway/server.py``).

These are the compatibility notification payloads and the shared inputs for
correlated requests. New prompts carry an owned request ID; legacy approval
notifications may omit it. Answers are validated by protocol.server_requests.
"""

from __future__ import annotations

from typing import Any

from protocol.types import WireModel, wire_optional


class ClarifyRequest(WireModel):
    """``clarify.request`` — the agent asks a disambiguating question."""

    TS_NAME = "ClarifyRequestPayload"

    request_id: str
    question: str
    choices: list[str] | None


class ApprovalRequest(WireModel):
    """``approval.request`` — a dangerous command needs operator approval."""

    TS_NAME = "ApprovalRequestPayload"

    command: str
    description: str
    request_id: str | None = wire_optional()


class SudoRequest(WireModel):
    """``sudo.request`` — a sudo password is required."""

    TS_NAME = "SudoRequestPayload"

    request_id: str


class SecretRequest(WireModel):
    """``secret.request`` — capture a secret into an env var (never persisted plain)."""

    TS_NAME = "SecretRequestPayload"

    request_id: str
    prompt: str
    env_var: str
    metadata: dict[str, Any] | None = wire_optional()


__all__ = ["ClarifyRequest", "ApprovalRequest", "SudoRequest", "SecretRequest"]
