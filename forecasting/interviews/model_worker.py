"""One isolated provider call; the parent owns cancellation and the wall deadline."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

MAX_RESPONSE_BYTES = 256_000


def call(payload: dict[str, Any]) -> dict[str, Any]:
    from agent.auxiliary_client import call_llm, extract_content_or_reasoning

    options = payload["options"]
    receipt: dict[str, Any] = {}
    response = call_llm(
        task="forecast_interview",
        strict_request=True,
        request_receipt=receipt,
        provider=options.get("provider"),
        model=options.get("model"),
        messages=payload["messages"],
        max_tokens=options["max_tokens"],
        temperature=0,
        timeout=options["timeout_seconds"],
    )
    content = extract_content_or_reasoning(response)
    if (
        not isinstance(content, str)
        or len(content.encode("utf-8")) > MAX_RESPONSE_BYTES
    ):
        raise ValueError("model response exceeded interview response limit")
    usage = getattr(response, "usage", None)
    tokens = getattr(usage, "completion_tokens", None)
    return {
        "content": content,
        "request_receipt": receipt,
        "response_model": str(getattr(response, "model", None) or "unreported"),
        "output_tokens": tokens if type(tokens) is int else None,
    }


def main() -> None:
    source, destination = map(Path, sys.argv[1:3])
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        result = call(payload)
    except Exception as exc:
        # Provider exceptions can contain credentials or request bodies. Return
        # useful failure class/status without copying their potentially secret text.
        status = getattr(exc, "status_code", None)
        result = {
            "error": type(exc).__name__,
            "status": status if type(status) is int else None,
        }
    encoded = json.dumps(result, allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_RESPONSE_BYTES:
        encoded = json.dumps({"error": "ResponseTooLarge", "status": None})
    destination.write_text(encoded, encoding="utf-8")


if __name__ == "__main__":
    main()
