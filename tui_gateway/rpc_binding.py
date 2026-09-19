"""Bind synchronous RPC work to one admitted runtime-host lifetime."""

from collections.abc import Callable
from typing import Any, Protocol

from superforecasting_agent.hosting.runtime import RuntimeHost
from superforecasting_agent.hosting.workers import HostStopping

RpcHandler = Callable[[Any, dict[str, Any]], dict[str, Any]]
Registrar = Callable[[str], Callable[[RpcHandler], RpcHandler]]


class ErrorResponse(Protocol):
    def __call__(self, rid: Any, code: int, message: str) -> dict[str, Any]: ...


def bind_host_handler(
    host: Callable[[], RuntimeHost],
    error: ErrorResponse,
    handler: Callable[[RuntimeHost, Any, dict[str, Any]], dict[str, Any]],
) -> RpcHandler:
    def invoke(rid: Any, params: dict[str, Any]) -> dict[str, Any]:
        try:
            owner = host()
            with owner.workers.operation():
                return handler(owner, rid, params)
        except HostStopping:
            return error(rid, 5030, "runtime host is stopping")

    return invoke
