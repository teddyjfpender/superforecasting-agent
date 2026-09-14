"""Check wire contracts without replacing handlers' documented domain errors."""

import json
import os
from functools import wraps
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from protocol import EVENT_SPECS, RPC_BY_METHOD

_EVENTS = {event.name: event.model for event in EVENT_SPECS}


class ContractViolation(AssertionError):
    """A successful handler or emitted event disagrees with its declaration."""


def check(model: type[BaseModel], value: Any, label: str) -> None:
    try:
        model.model_validate_json(json.dumps(value), strict=True)
    except ValidationError as exc:
        # Do not log values: payloads can contain passwords and provider keys.
        paths = [
            ".".join(str(part) for part in err["loc"])
            for err in exc.errors(include_input=False)
        ]
        message = f"{label} violates wire contract at {', '.join(paths)}"
        raise ContractViolation(message) from None


def contract_handler(name: str, handler: Callable[..., Any]) -> Callable[..., Any]:
    spec = RPC_BY_METHOD.get(name)
    if spec is None:
        # Runtime extensions remain separately owned. Completeness tests require
        # all bundled methods to have declarations before publication.
        return handler

    handler_fields = spec.handler_validated_parameters

    @wraps(handler)
    def wrapped(rid: Any, params: dict[str, Any]) -> Any:
        if not spec.handler_validates_request:
            if isinstance(params, dict):
                unknown = params.keys() - spec.request.model_fields.keys()
                if unknown:
                    return {
                        "jsonrpc": "2.0",
                        "id": rid,
                        "error": {
                            "code": spec.invalid_params_code,
                            "message": f"unknown parameters for {name}: {', '.join(sorted(unknown))}",
                        },
                    }
            try:
                spec.request.model_validate_json(json.dumps(params), strict=True)
            except ValidationError as exc:
                # Missing fields and invalid domain selectors remain the handler's
                # documented errors. Wrong JSON types must never reach side effects.
                structural = [
                    error
                    for error in exc.errors(include_input=False)
                    if error["type"].endswith(("_type", "_parsing"))
                    and (not error["loc"] or error["loc"][0] not in handler_fields)
                ]
                if structural:
                    field = str(structural[0]["loc"][0]) if structural[0]["loc"] else ""
                    code = dict(spec.parameter_error_codes).get(
                        field, spec.invalid_params_code
                    )
                    return {
                        "jsonrpc": "2.0",
                        "id": rid,
                        "error": {
                            "code": code,
                            "message": f"invalid parameter types for {name}",
                        },
                    }
        response = handler(rid, params)
        if isinstance(response, dict) and "result" in response:
            try:
                if params.keys() - spec.request.model_fields.keys():
                    raise ContractViolation(f"accepted unknown parameters for {name}")
                check(spec.request, params, f"accepted parameters for {name}")
                check(spec.response, response["result"], f"result of {name}")
            except ContractViolation:
                if os.environ.get("PYTEST_CURRENT_TEST"):
                    raise
                return {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "error": {
                        "code": -32603,
                        "message": f"Gateway contract violation: {name}",
                    },
                }
        return response

    return wrapped


def check_event(name: str, payload: dict[str, Any] | None) -> None:
    model = _EVENTS.get(name)
    if model is not None:
        check(model, payload or {}, f"event {name}")
