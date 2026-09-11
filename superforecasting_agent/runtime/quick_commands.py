"""Compose shared command execution with profile environment and redaction."""

from __future__ import annotations

import asyncio
import os

from superforecasting_agent.hosting.commands import (
    TIMEOUT_SECONDS,
    CommandResult,
)
from superforecasting_agent.hosting.commands import (
    execute as _execute,
)


async def execute(command: str, *, timeout: float = TIMEOUT_SECONDS) -> CommandResult:
    from agent.redact import redact_sensitive_text
    from tools.environments.local import _sanitize_subprocess_env

    return await _execute(
        command,
        timeout=timeout,
        environment=_sanitize_subprocess_env(os.environ.copy()),
        redact=redact_sensitive_text,
    )


def execute_sync(command: str) -> CommandResult:
    return asyncio.run(execute(command))
