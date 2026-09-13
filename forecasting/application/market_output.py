"""Thread-owned transfer of the latest market artifact from tools to orchestration."""

from __future__ import annotations

import threading
from typing import Any

_output = threading.local()


def record_emitted(presentation: dict[str, Any], spec: dict[str, Any]) -> None:
    """Replace prior repair attempts; consumers only use the final emission."""
    _output.value = {"presentation": presentation, "spec": spec}


def reset_emitted() -> None:
    _output.value = None


def take_emitted() -> dict[str, Any] | None:
    result = getattr(_output, "value", None)
    reset_emitted()
    return result
